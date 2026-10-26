"""Run lab-usage-scan on a synthetic transcript tree; no real transcripts are read."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCAN=ROOT/'bin/lab-usage-scan'
LAB='11111111-1111-4111-8111-111111111111'
NORMAL='22222222-2222-4222-8222-222222222222'
EVIDENCE='33333333-3333-4333-8333-333333333333'
TS='2026-10-20T12:00:00Z'

def assistant(mid,model,blocks,ts=TS,usage=None):
    return {'type':'assistant','timestamp':ts,'message':{'id':mid,'model':model,'content':blocks,
            'usage':usage or {'input_tokens':10,'cache_creation_input_tokens':20,'cache_read_input_tokens':100,'output_tokens':5}}}

def result(tool_id,content,ts=TS):
    return {'type':'user','timestamp':ts,'message':{'role':'user','content':[{'type':'tool_result','tool_use_id':tool_id,'content':content}]}}

def write(path,records,extra=''):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(json.dumps(r) for r in records)+'\n'+extra)

class UsageScanTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name)
        self.projects=base/'projects';self.runs=base/'runs';(self.runs/LAB).mkdir(parents=True)
        image={'type':'image','source':{'type':'base64','data':'A'*400}}
        # Lab main thread: one Opus call streamed as two records, an image Read and a Bash call.
        write(self.projects/'proj-a'/f'{LAB}.jsonl',[
            assistant('m1','claude-opus-5-5',[{'type':'tool_use','id':'t1','name':'Read','input':{'file_path':'/x/shot.png'}}]),
            assistant('m1','claude-opus-5-5',[{'type':'tool_use','id':'t2','name':'Bash','input':{'command':'ls'}}]),
            assistant('m2','claude-opus-5-5',[{'type':'tool_use','id':'t7','name':'Read','input':{'file_path':'/x/clipboard'}}]),
            result('t1',[image]),result('t2','x'*50),result('t7',[{'type':'image','source':{'data':'C'*100}}])])
        # Lab subagent: one Sonnet implementer call.
        sub=self.projects/'proj-a'/LAB/'subagents'/'agent-a1.jsonl'
        write(sub,[assistant('s1','claude-sonnet-5-5',[{'type':'tool_use','id':'t3','name':'Read','input':{'file_path':'/x/a.py'}}]),result('t3','y'*30)])
        sub.with_name('agent-a1.meta.json').write_text(json.dumps({'agentType':'harness-lab:implementer'}))
        # Normal session: a notes MCP call, a PDF read, a synthetic reply, an old record and a broken line.
        write(self.projects/'proj-b'/f'{NORMAL}.jsonl',[
            assistant('n1','claude-sonnet-5-5',[{'type':'tool_use','id':'t4','name':'mcp__notes-server__read_note','input':{}},
                                                {'type':'tool_use','id':'t5','name':'Read','input':{'file_path':'/x/r.pdf'}}]),
            result('t4','z'*70),result('t5',[{'type':'document','source':{'data':'B'*90}}]),
            assistant('n2','<synthetic>',[]),
            assistant('old','claude-opus-5-5',[],ts='2026-09-01T00:00:00Z')],extra='{not json "usage"\n')
        # A session outside the run directory that uses a harness-lab agent still counts as lab.
        write(self.projects/'proj-c'/f'{EVIDENCE}.jsonl',[
            assistant('e1','claude-opus-5-5',[{'type':'tool_use','id':'t6','name':'Agent','input':{'subagent_type':'harness-lab:reviewer','prompt':'p'}}])])

    def tearDown(self):self.temp.cleanup()

    def run_scan(self,*args):
        out=subprocess.run(['python3',str(SCAN),'--projects',str(self.projects),'--runs',str(self.runs),'--since','2026-10-13',*args],
                           text=True,capture_output=True,check=True)
        return out.stdout

    def test_groups_models_tools_and_media_are_counted(self):
        report=json.loads(self.run_scan('--json'))
        lab,normal=report['groups']['LAB'],report['groups']['NORMAL']
        self.assertEqual((lab['sessions'],normal['sessions']),(2,1))
        self.assertEqual((lab['servedCalls'],lab['opusCalls'],lab['opusSharePct']),(4,3,75.0))
        self.assertEqual(lab['byModel']['claude-sonnet-5-5']['subagent'],1)
        self.assertEqual(lab['inputSideTokens'],520)
        self.assertEqual(lab['tools']['Read:image'],{'calls':2,'resultChars':500})
        self.assertEqual(lab['tools']['Bash'],{'calls':1,'resultChars':50})
        self.assertEqual(lab['tools']['Read:text']['resultChars'],30)
        self.assertEqual(lab['agentTypes']['harness-lab:implementer'],{'claude-sonnet-5-5':1})
        self.assertEqual((normal['servedCalls'],normal['opusCalls'],normal['syntheticMessages'],normal['badLines']),(1,0,1,1))
        self.assertEqual(normal['tools']['Read:pdf'],{'calls':1,'resultChars':90})
        self.assertEqual(normal['mcpByServer'],{'mcp:notes-server':{'calls':1,'resultChars':70}})

    def test_summary_is_short_and_out_writes_the_full_report(self):
        out=Path(self.temp.name)/'report.json'
        text=self.run_scan('--out',str(out))
        self.assertLessEqual(len(text.splitlines()),40)
        self.assertIn('LAB: 2 sessions',text)
        self.assertEqual(json.loads(out.read_text())['groups']['LAB']['servedCalls'],4)

if __name__=='__main__':unittest.main()
