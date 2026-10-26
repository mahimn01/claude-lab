"""Keep native Claude's terminal UI while switching accounts at idle boundaries.

No credentials are read here. The launcher supplies child environments in memory.
Quota evidence comes from native usage windows plus a structured provider error,
never generated prose. Only new transcript rows are inspected, and none are copied.
"""
import json
import math
import os
import signal
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

CONTINUE_PROMPT = ('Continue the interrupted task from this saved conversation. The previous account '
                   'reached its subscription usage limit and the user authorized account switching. '
                   'Inspect recorded tool results and current files; preserve the original task and '
                   'permissions, and do not repeat completed actions.')


class TranscriptWatch:
    def __init__(self, config_dir):
        self.base=Path(config_dir)/'projects'
        self.offsets={}
        for path in self.base.glob('*/*.jsonl'):
            try:
                if path.is_file():self.offsets[path]=path.stat().st_size
            except (FileNotFoundError,PermissionError,NotADirectoryError):continue
        self.denied={}

    def poll(self, session_id, since=0):
        try: session_id=str(uuid.UUID(session_id))
        except (ValueError,TypeError,AttributeError):return False
        for path in self.base.glob('*/'+session_id+'.jsonl'):
            try:source=path.open('rb')
            except (FileNotFoundError,PermissionError,IsADirectoryError,NotADirectoryError):continue
            with source:
                source.seek(self.offsets.get(path,0))
                while True:
                    start=source.tell();line=source.readline()
                    if not line or not line.endswith(b'\n'):
                        self.offsets[path]=start;break
                    self.offsets[path]=source.tell()
                    try:row=json.loads(line)
                    except (ValueError,UnicodeDecodeError):continue
                    if (row.get('type')=='assistant' and row.get('error')=='rate_limit'
                            and row.get('isApiErrorMessage') is not False and not row.get('isSidechain')):
                        try:stamp=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).timestamp()*1000
                        except (KeyError,ValueError,AttributeError):continue
                        self.denied[session_id]=stamp
        return self.denied.get(session_id,-1)>=since


def valid_control(control,generation,source):
    if (not isinstance(control,dict) or control.get('schema') not in {1,2}
            or control.get('generation')!=generation or control.get('source')!=source):return False
    try:uuid.UUID(control['sessionId'])
    except (KeyError,ValueError,TypeError):return False
    return True


def switch_ready(control, generation, provider_denied, source='primary'):
    if not isinstance(control,dict) or not provider_denied:return False
    if (not valid_control(control,generation,source) or control.get('phase')!='ready'
            or control.get('reason')!='subscription_exhausted'):return False
    return any(w.get('kind') in {'five_hour','seven_day'}
               and type(w.get('percentUsed')) in {int,float} and w['percentUsed']>=100
               for w in control.get('windows',[]) if isinstance(w,dict))


def idle_control(control,generation,source):
    return (valid_control(control,generation,source) and control.get('schema')==2
            and control.get('phase') in {'idle','ready'} and control.get('leadIdle') is True
            and control.get('workersIdle') is True and control.get('hasMainTurn') is True)


def retry_at(windows,now,delay=300):
    """Wait for every exhausted shared window; unknown reset times use a cooldown."""
    deadlines=[]
    for window in windows:
        if (not isinstance(window,dict) or window.get('kind') not in {'five_hour','seven_day'}
                or type(window.get('percentUsed')) not in {int,float} or window['percentUsed']<100):continue
        try:
            stamp=datetime.fromisoformat(window['resetsAt'].replace('Z','+00:00'))
            reset=stamp.timestamp() if stamp.tzinfo else 0
            deadlines.append(reset+2 if math.isfinite(reset) and reset>now else now+delay)
        except (KeyError,ValueError,TypeError,AttributeError,OverflowError):deadlines.append(now+delay)
    return max(deadlines or [now+delay])


class AccountRouter:
    """No model probes or work caps: retry only at reset times and idle boundaries."""
    def __init__(self,auto_return=False,retry_delay=300):
        self.auto_return=auto_return;self.retry_delay=retry_delay
        self.blocked_until={};self.seen=set();self.return_attempted=False;self.switched_once=False
        self.order=['primary','token'];self.temporary=None;self.retried_sources=set()

    def configure(self,policy,now):
        self.order=list(policy.get('priority',['primary','token']))
        self.temporary=policy.get('temporary')
        for source,reset in policy.get('availability',{}).items():
            self.blocked_until[source]=max(reset,self.blocked_until.get(source,0))
        if self.temporary and self.temporary['source']!='primary':
            until=datetime.fromisoformat(self.temporary['until'].replace('Z','+00:00')).timestamp()
            if until>now:self.blocked_until['primary']=max(until,self.blocked_until.get('primary',0))

    def preference(self,now):
        if self.temporary:
            until=datetime.fromisoformat(self.temporary['until'].replace('Z','+00:00')).timestamp()
            if until>now:return [self.temporary['source']]+[s for s in self.order if s!=self.temporary['source']]
        return self.order

    def choose(self,control,generation,source,denied,now):
        if not self.auto_return and self.switched_once:return None
        exhausted=switch_ready(control,generation,denied,source)
        if exhausted:
            key=(generation,control.get('turnId'),control.get('turnStartedAt',0))
            if key not in self.seen:
                self.seen.add(key)
                reset=retry_at(control.get('windows',[]),now,self.retry_delay)
                if source in self.retried_sources or (source=='primary' and self.return_attempted):reset=max(reset,now+self.retry_delay)
                self.blocked_until[source]=max(reset,self.blocked_until.get(source,0))
        preference=self.preference(now)
        available=lambda s:s!=source and now>=self.blocked_until.get(s,0)
        if exhausted:
            destination=next((s for s in preference if available(s)),None)
            if destination:return (destination,True,'subscription_exhausted')
        if self.auto_return and source in preference and idle_control(control,generation,source):
            for destination in preference[:preference.index(source)]:
                if available(destination):
                    return (destination,False,'primary_retry_due' if destination=='primary' else 'preferred_account_ready')
        return None

    def switched(self,source):
        self.switched_once=True
        self.retried_sources.add(source)
        if source=='primary':self.return_attempted=True


def write_state(run,source,router,labels):
    data={'schema':1,'active':source,'label':labels[source],'auto_return':router.auto_return,
          'unavailable_until':router.blocked_until,'model_probe_requests':0,
          'priority':router.order,'temporary':router.temporary,'supervisor_pid':os.getpid()}
    path=Path(run)/'account-state.json';temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2)+'\n');temp.chmod(0o600);temp.replace(path)


def read_control(run):
    try:
        data=json.loads((Path(run)/'auth-control.json').read_text())
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}


def supervise(argv, env, run, config_dir, backup_command, *, process_factory=subprocess.Popen,
              watch_factory=TranscriptWatch, sleeper=time.sleep, label='Claude Lab',
              primary_command=None,account_policy=None,clock=time.time,
              account_command=None,policy_loader=None):
    """Inherit the terminal directly; change accounts at an idle, saved boundary."""
    generation=str(uuid.uuid4());env=dict(env)
    env['CLAUDE_LAB_AUTH_GENERATION']=generation
    policy=account_policy or {};labels={s:policy.get('accounts',{}).get(s,{}).get('label',s) for s in policy.get('priority',['primary','token'])}
    router=AccountRouter(bool((primary_command or account_command) and policy.get('auto_return')),policy.get('retry_delay_seconds',300))
    router.configure(policy,clock());reload_at=0
    source=env.get('CLAUDE_LAB_AUTH_SOURCE','primary');last_state=None
    old_handler=signal.signal(signal.SIGINT,lambda *_:None)
    def exit_signal(*_):raise SystemExit(143)
    old_term=signal.signal(signal.SIGTERM,exit_signal)
    terminal=None
    try:
        import sys,termios
        if sys.stdin.isatty():terminal=(sys.stdin.fileno(),termios.tcgetattr(sys.stdin.fileno()))
    except (ImportError,OSError):pass
    process=None
    try:
        while True:
            watch=watch_factory(config_dir)  # A previous process's errors cannot justify a new switch.
            process=process_factory(argv,env=env)  # native stdin/stdout/stderr and permissions
            while process.poll() is None:
                now=clock()
                if policy_loader and now>=reload_at:
                    reload_at=now+1
                    try:
                        policy=policy_loader();router.configure(policy,now)
                        router.auto_return=bool((primary_command or account_command) and policy.get('auto_return'))
                        labels={s:policy.get('accounts',{}).get(s,{}).get('label',s) for s in router.order}
                    except (OSError,ValueError,TypeError):pass
                control=read_control(run)
                denied=watch.poll(control.get('sessionId'),control.get('turnStartedAt',0))
                decision=router.choose(control,generation,source,denied,now)
                state=(source,tuple(sorted(router.blocked_until.items())),tuple(router.order),str(router.temporary))
                if state!=last_state:write_state(run,source,router,labels);last_state=state
                if decision:
                    destination,continue_turn,reason=decision
                    sid=control['sessionId']
                    process.terminate()  # native graceful shutdown saves the transcript
                    try:process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        print(label + ': shutdown is still running; backup was not started. Resume after it exits.',flush=True)
                        return 1  # never force-kill or replay while tools might remain
                    if terminal:
                        import termios
                        termios.tcsetattr(terminal[0],termios.TCSADRAIN,terminal[1])
                    if not any((Path(config_dir)/'projects').glob('*/'+sid+'.jsonl')):
                        raise ValueError('No saved conversation exists; refusing to replay work under another account')
                    if account_command:argv,env=account_command(sid,destination,continue_turn)
                    else:argv,env=backup_command(sid) if destination=='token' else primary_command(sid,continue_turn)
                    generation=str(uuid.uuid4());env=dict(env);env['CLAUDE_LAB_AUTH_GENERATION']=generation
                    source=destination;router.switched(source)
                    write_state(run,source,router,labels);last_state=None
                    if reason=='subscription_exhausted':
                        print(f'{label}: allowance exhausted; resuming with {labels[source]}.',flush=True)
                    else:
                        print(f'{label}: account preference updated; resumed with {labels[source]} between turns.',flush=True)
                    break
                sleeper(.25)
            else:
                return process.returncode
    finally:
        signal.signal(signal.SIGINT,old_handler)
        signal.signal(signal.SIGTERM,old_term)
        if process is not None and process.poll() is None:
            # Cleanup on an exceptional supervisor exit, without escalating to SIGKILL.
            process.terminate()
        if terminal:
            import termios
            termios.tcsetattr(terminal[0],termios.TCSADRAIN,terminal[1])
