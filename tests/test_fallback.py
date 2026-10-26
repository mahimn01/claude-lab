"""Offline native-UI failover: real filesystem evidence, mocked child processes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fallback',ROOT/'bin/fallback.py')
fallback=importlib.util.module_from_spec(spec);spec.loader.exec_module(fallback)
SID='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'

class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.run=self.base/'run';self.run.mkdir()
        self.config=self.base/'config';self.transcript=self.config/'projects/repo'/f'{SID}.jsonl'
        self.transcript.parent.mkdir(parents=True)
        self.control={'schema':1,'generation':'test','source':'primary','phase':'ready',
                      'reason':'subscription_exhausted','sessionId':SID,'windows':[{'kind':'seven_day','percentUsed':100}]}
    def tearDown(self):self.temp.cleanup()
    def error(self,kind='rate_limit',side=False):
        return {'type':'assistant','error':kind,'isApiErrorMessage':True,'isSidechain':side,
                'timestamp':datetime.now(timezone.utc).isoformat()}
    def test_switch_requires_shared_exhaustion_provider_denial_and_idle_generation(self):
        self.assertTrue(fallback.switch_ready(self.control,'test',True))
        self.assertFalse(fallback.switch_ready(self.control,'test',False))
        self.assertFalse(fallback.switch_ready(self.control,'old',True))
        for update in [{'phase':'pending'},{'source':'token'}, {'windows':[{'kind':'seven_day_opus','percentUsed':100}]},
                       {'windows':[{'kind':'seven_day','percentUsed':99}]}]:
            self.assertFalse(fallback.switch_ready({**self.control,**update},'test',True))
    def test_old_errors_generated_text_auth_errors_and_subagents_cannot_trigger_a_switch(self):
        self.transcript.write_text(json.dumps(self.error())+'\n')
        watch=fallback.TranscriptWatch(self.config)
        self.assertFalse(watch.poll(SID))
        rows=[{'type':'assistant','message':{'content':[{'type':'text','text':'rate_limit 429'}]}},
              self.error('authentication_failed'),self.error(side=True)]
        with self.transcript.open('a') as f:
            for row in rows:f.write(json.dumps(row)+'\n')
        self.assertFalse(watch.poll(SID))
        with self.transcript.open('a') as f:f.write(json.dumps(self.error())+'\n')
        self.assertTrue(watch.poll(SID))
        self.assertFalse(watch.poll(SID,10**16))

    def test_broken_or_unreadable_history_and_disappearing_files_do_not_abort_startup(self):
        broken=self.transcript.parent/'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb.jsonl'
        broken.symlink_to(self.base/'missing-target')
        self.transcript.write_text(json.dumps(self.error())+'\n')
        watch=fallback.TranscriptWatch(self.config)
        self.assertNotIn(broken,watch.offsets)
        for error in [FileNotFoundError(2,'removed during read'),PermissionError(13,'unreadable')]:
            with patch.object(Path,'open',side_effect=error):
                self.assertFalse(watch.poll(SID))
    def test_supervisor_gracefully_resumes_exact_conversation_once_with_native_stdio(self):
        launches=[]
        class Child:
            returncode=None
            def __init__(child,argv,env):
                child.env=env;child.done=False;child.backup=bool(launches)
                launches.append((argv,env))
            def poll(child):
                if child.backup:child.returncode=0;return 0
                if child.done:return child.returncode
                self.transcript.write_text(json.dumps(self.error())+'\n')
                control={**self.control,'generation':child.env['CLAUDE_LAB_AUTH_GENERATION'],'turnStartedAt':0}
                (self.run/'auth-control.json').write_text(json.dumps(control))
                return None
            def terminate(child):child.done=True;child.returncode=0
            def wait(child,timeout=None):return child.returncode
        def backup(sid):return ['claude','--resume',sid,fallback.CONTINUE_PROMPT],{'CLAUDE_LAB_AUTH_SOURCE':'token'}
        code=fallback.supervise(['claude','--session-id',SID],{'CLAUDE_LAB_AUTH_SOURCE':'primary'},self.run,
            self.config,backup,process_factory=Child,sleeper=lambda _:None)
        self.assertEqual(code,0);self.assertEqual(len(launches),2)
        self.assertEqual(launches[1][0][2],SID)
        self.assertIn('do not repeat completed actions',launches[1][0][-1])
        self.assertNotEqual(launches[0][1]['CLAUDE_LAB_AUTH_GENERATION'],launches[1][1]['CLAUDE_LAB_AUTH_GENERATION'])

    def test_real_local_child_process_handoff_preserves_native_stdio_without_a_model(self):
        code="""import json,os,time
from pathlib import Path
from datetime import datetime,timezone
p=Path(os.environ['TEST_TRANSCRIPT']);p.write_text(json.dumps({'type':'assistant','error':'rate_limit','isApiErrorMessage':True,'timestamp':datetime.now(timezone.utc).isoformat()})+'\\n')
control={'schema':1,'generation':os.environ['CLAUDE_LAB_AUTH_GENERATION'],'source':'primary','phase':'ready','reason':'subscription_exhausted','sessionId':os.environ['TEST_SID'],'turnStartedAt':0,'windows':[{'kind':'five_hour','percentUsed':100}]}
Path(os.environ['TEST_RUN'],'auth-control.json').write_text(json.dumps(control))
time.sleep(10)
"""
        import os
        env={**os.environ,'TEST_TRANSCRIPT':str(self.transcript),'TEST_SID':SID,'TEST_RUN':str(self.run)}
        continued=[]
        def backup(sid):
            continued.append(sid)
            return [sys.executable,'-c','print("Local child handoff verified; no model called.")'],env
        result=fallback.supervise([sys.executable,'-c',code],env,self.run,self.config,backup)
        self.assertEqual(result,0);self.assertEqual(continued,[SID])

    def idle(self,source='token',**changes):
        return {**self.control,'schema':2,'source':source,'phase':'idle','reason':'observation',
                'leadIdle':True,'workersIdle':True,'hasMainTurn':True,'mainReason':'answer',**changes}

    def test_return_waits_for_all_exhausted_windows_and_a_safe_idle_boundary(self):
        def iso(stamp):return datetime.fromtimestamp(stamp,timezone.utc).isoformat()
        windows=[{'kind':'five_hour','percentUsed':100,'resetsAt':iso(110)},
                 {'kind':'seven_day','percentUsed':100,'resetsAt':iso(200)}]
        router=fallback.AccountRouter(True)
        primary={**self.control,'windows':windows}
        self.assertEqual(router.choose(primary,'test','primary',True,100)[0],'token')
        router.switched('token');idle=self.idle()
        self.assertIsNone(router.choose(idle,'test','token',False,150))
        self.assertIsNone(router.choose({**idle,'workersIdle':False},'test','token',False,203))
        self.assertIsNone(router.choose({**idle,'leadIdle':False},'test','token',False,203))
        self.assertIsNone(router.choose({**idle,'hasMainTurn':False},'test','token',False,203))
        self.assertIsNone(router.choose(idle,'old','token',False,203))
        self.assertEqual(router.choose(idle,'test','token',False,203),('primary',False,'primary_retry_due'))

    def test_only_an_interrupted_quota_failure_is_continued_on_return(self):
        router=fallback.AccountRouter(True);router.blocked_until['primary']=100
        idle=self.idle()
        for reason in ['answer','aborted','error']:
            self.assertFalse(router.choose({**idle,'mainReason':reason},'test','token',False,101)[1])
        failed=self.idle(phase='ready',reason='subscription_exhausted',mainReason='error')
        self.assertTrue(router.choose(failed,'test','token',True,101)[1])

    def test_rejected_returns_use_a_cooldown_without_a_switch_count_limit(self):
        router=fallback.AccountRouter(True,retry_delay=300)
        for n in range(4):
            generation=f'primary-{n}';now=100+n*400
            failed={**self.control,'generation':generation}
            self.assertEqual(router.choose(failed,generation,'primary',True,now)[0],'token')
            router.switched('token')
            deadline=router.blocked_until['primary']
            self.assertIsNone(router.choose(failed,generation,'token',False,now+1))
            idle=self.idle(generation=f'token-{n}')
            self.assertIsNone(router.choose(idle,f'token-{n}','token',False,deadline-1))
            self.assertEqual(router.choose(idle,f'token-{n}','token',False,deadline)[0],'primary')
            router.switched('primary')

    def test_both_accounts_exhausted_wait_without_restarting_or_sliding_the_reset(self):
        router=fallback.AccountRouter(True);router.blocked_until={'primary':200,'token':500}
        failed=self.idle(phase='ready',reason='subscription_exhausted',mainReason='error')
        router.choose(failed,'test','token',True,100)
        token_deadline=router.blocked_until['token']
        self.assertIsNone(router.choose(failed,'test','token',True,150))
        self.assertEqual(router.blocked_until['token'],token_deadline)
        self.assertEqual(router.choose(failed,'test','token',True,201)[0],'primary')
        router.switched('primary')
        self.assertIsNone(router.choose(self.control,'test','primary',True,202))

    def test_no_provider_rejection_or_generated_text_can_authorize_fallback(self):
        router=fallback.AccountRouter(True)
        self.assertIsNone(router.choose(self.control,'test','primary',False,100))
        self.assertEqual(router.blocked_until,{})
        self.assertEqual(fallback.retry_at([{'kind':'five_hour','percentUsed':100,'resetsAt':'invalid'}],100),400)
        self.assertEqual(fallback.retry_at([{'kind':'seven_day_opus','percentUsed':100}],100),400)
        (self.run/'auth-control.json').write_text('[]')
        self.assertEqual(fallback.read_control(self.run),{})

    def test_temporary_last_backup_returns_to_main_at_expiry_and_preserves_normal_priority(self):
        router=fallback.AccountRouter(True)
        policy={'priority':['primary','secondary','token','token-last'],
                'availability':{'primary':400,'secondary':800},
                'temporary':{'source':'token-last','until':'1970-01-01T00:06:40+00:00'}}
        router.configure(policy,100)
        idle=self.idle(source='token-last')
        self.assertIsNone(router.choose(idle,'test','token-last',False,200))
        self.assertEqual(router.choose(idle,'test','token-last',False,400),('primary',False,'primary_retry_due'))
        failed=self.idle(source='token-last',phase='ready',reason='subscription_exhausted',mainReason='error')
        self.assertEqual(router.choose(failed,'test','token-last',True,200)[0],'token')
        self.assertEqual(router.order,['primary','secondary','token','token-last'])

    def test_policy_reload_defers_a_user_selection_until_a_safe_boundary(self):
        router=fallback.AccountRouter(True)
        policy={'priority':['primary','secondary','token','token-last'],
                'temporary':{'source':'token-last','until':'1970-01-01T00:06:40+00:00'}}
        router.configure(policy,100)
        busy=self.idle(source='token',leadIdle=False,phase='pending')
        self.assertIsNone(router.choose(busy,'test','token',False,200))
        self.assertEqual(router.choose(self.idle(),'test','token',False,200),('token-last',False,'preferred_account_ready'))
        router.configure({**policy,'temporary':None},300)
        self.assertEqual(router.choose(self.idle(source='token-last'),'test','token-last',False,300)[0],'secondary')

    def test_real_process_round_trip_returns_idle_without_starting_another_task(self):
        import os
        env={**os.environ,'TEST_TRANSCRIPT':str(self.transcript),'TEST_SID':SID,
             'TEST_RUN':str(self.run),'CLAUDE_LAB_AUTH_SOURCE':'primary'}
        primary_code="""import json,os,time
from pathlib import Path
from datetime import datetime,timezone
p=Path(os.environ['TEST_TRANSCRIPT']);p.write_text(json.dumps({'type':'assistant','error':'rate_limit','isApiErrorMessage':True,'timestamp':datetime.now(timezone.utc).isoformat()})+'\\n')
reset=datetime.fromtimestamp(time.time()+1,timezone.utc).isoformat()
c={'schema':2,'generation':os.environ['CLAUDE_LAB_AUTH_GENERATION'],'source':'primary','phase':'ready','reason':'subscription_exhausted','sessionId':os.environ['TEST_SID'],'turnStartedAt':0,'windows':[{'kind':'five_hour','percentUsed':100,'resetsAt':reset}],'leadIdle':True,'workersIdle':True}
Path(os.environ['TEST_RUN'],'auth-control.json').write_text(json.dumps(c))
time.sleep(15)
"""
        backup_code="""import json,os,time
from pathlib import Path
c={'schema':2,'generation':os.environ['CLAUDE_LAB_AUTH_GENERATION'],'source':'token','phase':'pending','reason':'observation','sessionId':os.environ['TEST_SID'],'turnStartedAt':0,'windows':[],'leadIdle':True,'workersIdle':False}
p=Path(os.environ['TEST_RUN'],'auth-control.json');p.write_text(json.dumps(c))
time.sleep(3.1)
Path(os.environ['TEST_RUN'],'worker-finished').write_text('done')
c.update(phase='idle',workersIdle=True,mainReason='answer',hasMainTurn=True);p.write_text(json.dumps(c))
time.sleep(15)
"""
        def backup(sid):
            self.assertEqual(sid,SID)
            return [sys.executable,'-c',backup_code],{**env,'CLAUDE_LAB_AUTH_SOURCE':'token'}
        returned=[]
        def primary(sid,continue_turn):
            self.assertEqual(sid,SID);self.assertFalse(continue_turn)
            self.assertTrue((self.run/'worker-finished').exists())
            returned.append(sid)
            return [sys.executable,'-c','print("Idle return verified; no new task or model request.")'],env
        result=fallback.supervise([sys.executable,'-c',primary_code],env,self.run,self.config,backup,
            primary_command=primary,account_policy={'auto_return':True})
        self.assertEqual(result,0);self.assertEqual(returned,[SID])
        self.assertEqual(json.loads((self.run/'account-state.json').read_text())['active'],'primary')

if __name__=='__main__':unittest.main()
