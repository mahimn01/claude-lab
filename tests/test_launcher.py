"""Exercise lab isolation and actual verification in disposable projects."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('lab',ROOT/'bin/lab.py')
lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)

class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.auth_patch=patch.object(lab,'AUTH',Path(self.temp.name)/'auth.json')
        self.auth_patch.start()
        self.registry_patch=patch.object(lab,'ACCOUNT_REGISTRY',Path(self.temp.name)/'accounts.json')
        self.registry_patch.start()
        # A fake, hermetic stand-in for the user's own Claude settings: the tests never read real ones.
        self.claude_home=Path(self.temp.name)/'claude-home';self.claude_home.mkdir()
        (self.claude_home/'settings.json').write_text(json.dumps({
            'permissions':{'allow':['Bash(git status*)'],'deny':[],'ask':['Bash(git push*)']},
            'enabledPlugins':{'noisy-plugin@market':True,'useful-plugin@market':True},
            'hooks':{'PreToolUse':[{'matcher':'Bash','hooks':[{'type':'command','command':'keep-this-guard --check'},
                                                               {'type':'command','command':'drop-this-hook'}]}]}}))
        self.source_patch=patch.object(lab,'SOURCE',self.claude_home/'settings.json');self.source_patch.start()
        self.env_patch=patch.dict(os.environ,{'CLAUDE_LAB_DISABLE_PLUGINS':'noisy-plugin@market','CLAUDE_LAB_KEEP_HOOKS':'keep-this-guard',
                                              'CLAUDE_LAB_MCPORTER_BLOCK':'guarded-server'});self.env_patch.start()
        self.project=Path(self.temp.name)/'project'
        shutil.copytree(ROOT/'demo-project',self.project)
        self.run=Path(self.temp.name)/'run'
        self.before=lab.hashes()
        lab.prepare(self.project,'balanced','auto',self.run)

    def tearDown(self):
        self.assertEqual(self.before,lab.hashes())
        self.auth_patch.stop()
        self.registry_patch.stop()
        self.source_patch.stop()
        self.env_patch.stop()
        self.temp.cleanup()

    def test_session_overrides_do_not_replace_the_original_setup(self):
        settings=json.loads((self.run/'settings.json').read_text())
        self.assertTrue(settings['disableWorkflows'])
        self.assertFalse(settings['enabledPlugins']['noisy-plugin@market'])
        self.assertTrue(settings['enabledPlugins']['useful-plugin@market'])
        self.assertIn('PreToolUse',settings['hooks'])
        self.assertIn('keep-this-guard',json.dumps(settings['hooks']))
        self.assertNotIn('drop-this-hook',json.dumps(settings['hooks']))
        argv,env=lab.launch_command(self.run,'Fix this task')
        self.assertIn('project,local',argv)
        self.assertNotIn('--bare',argv)
        self.assertNotIn('--dangerously-skip-permissions',argv)
        self.assertNotIn('CLAUDE_CONFIG_DIR',settings['env'])
        self.assertIn(str(ROOT/'plugin'),argv)

    def test_checker_records_real_failure_then_success_after_a_fix(self):
        lab.dump(self.run/'acceptance.json',{'checks':[{'argv':['python3','-m','unittest','-q']}],'criteria':['refund reduces total']})
        fail=lab.verify(self.run)
        self.assertFalse(fail['passed']);self.assertEqual(fail['checks'][0]['exitCode'],1)
        old=fail['workspaceFingerprint']
        (self.project/'totals.py').write_text('def total_amount(amounts):\n    return sum(amounts)\n')
        passed=lab.verify(self.run)
        self.assertTrue(passed['passed']);self.assertNotEqual(old,passed['workspaceFingerprint'])

    def test_no_checks_cannot_be_called_verified(self):
        with self.assertRaises(ValueError):lab.verify(self.run)

    def test_a_shell_is_not_a_verification_program(self):
        lab.dump(self.run/'acceptance.json',{'checks':[{'argv':['sh','-c','true']}],'criteria':[]})
        with self.assertRaises(ValueError):lab.verify(self.run)

    def test_readiness_blocks_inactive_plugin_without_running_a_model(self):
        import os
        env={**os.environ,'CLAUDE_LAB_RUN_DIR':str(self.run)}
        result=subprocess.check_output(['python3',str(ROOT/'bin/ready_guard.py')],env=env,text=True)
        self.assertEqual(json.loads(result)['decision'],'block')
        state=json.loads((self.run/'metrics.json').read_text());state['runtimeReady']=True;lab.dump(self.run/'metrics.json',state)
        result=subprocess.check_output(['python3',str(ROOT/'bin/ready_guard.py')],env=env,text=True)
        self.assertEqual(json.loads(result),{})

    def test_launcher_accepts_a_prompt_after_flags_without_starting_claude(self):
        import os
        scratch=tempfile.mkdtemp();self.addCleanup(shutil.rmtree,scratch,True)
        env={k:v for k,v in os.environ.items() if k!='CLAUDE_CODE_AUTO_COMPACT_WINDOW'}
        env.update({'TMPDIR':scratch,'CLAUDE_LAB_STATE_DIR':scratch+'/state','CLAUDE_LAB_CONFIG_DIR':scratch+'/cfg'})
        result=subprocess.run(['python3',str(ROOT/'bin/lab.py'),'--dry-run','--mode','deep','Implement pagination','--project',str(self.project)],text=True,capture_output=True,env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        import uuid
        self.assertEqual(str(uuid.UUID(data['argv'][data['argv'].index('--session-id')+1])),data['argv'][data['argv'].index('--session-id')+1])
        self.assertIsNone(data['limits'])
        self.assertEqual(data['argv'][data['argv'].index('--autocompact')+1],'300k')

    def test_existing_run_and_original_config_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):lab.prepare(self.project,'balanced','auto',self.run)
        with self.assertRaises(ValueError):lab.prepare(self.project,'balanced','auto',self.claude_home)
        with self.assertRaises(ValueError):lab.prepare(self.project,'balanced','auto',self.project/'lab-state')

    def test_home_launch_keeps_native_cwd_and_does_not_scan_the_home_tree(self):
        run=self.project/'.local/state/claude-lab/runs/home-test'
        with patch.object(lab,'USER',self.project), patch.object(lab,'scoped_instructions',return_value=('core','policy')), patch.object(lab,'fingerprint',side_effect=AssertionError('Home must not be scanned')):
            prepared,cfg=lab.prepare(self.project,'balanced','auto',run)
            self.assertEqual(prepared,run.resolve())
            self.assertEqual(cfg['launchCwd'],str(self.project.resolve()))
            self.assertTrue(cfg['homeWorkspace'])
            self.assertIsNone(cfg['verificationProject'])
            self.assertTrue(lab.run_fingerprint(run)['scopeRequired'])
            with self.assertRaisesRegex(ValueError,'Select the code folder'):lab.verify(run)
            argv,_=lab.launch_command(run)
            self.assertIn('home directory',argv[argv.index('--append-system-prompt')+1])
            # In ~ the project settings file is the user's own settings.json, so no settings files load.
            self.assertEqual(argv[argv.index('--setting-sources')+1],'')

    def test_project_launch_keeps_project_settings_and_hides_unused_tools_and_skills(self):
        argv,_=lab.launch_command(self.run,'x',load_auth=False,start_proxy=False)
        self.assertEqual(argv[argv.index('--setting-sources')+1],'project,local')
        settings=json.loads((self.run/'settings.json').read_text())
        for tool in ['Artifact','ScheduleWakeup','ReportFindings','CronCreate','RemoteTrigger','PushNotification']:
            self.assertIn(tool,settings['permissions']['deny'])
        for kept in ['Bash','Read','Edit','Write','Agent','SendMessage','Monitor','AskUserQuestion','WebFetch','WebSearch','LSP']:
            self.assertNotIn(kept,settings['permissions']['deny'])
        overrides=settings['skillOverrides']
        self.assertEqual(set(overrides.values()),{'user-invocable-only'})
        for kept in ['harness-lab:work-task','harness-lab:code-first-data','claude-api','simplify']:
            self.assertNotIn(kept,overrides)
        self.assertIn('dataviz',overrides)
        self.assertIn('chrome-devtools-mcp:troubleshooting',overrides)
        full=lab.settings(self.run,full_tools=True)
        self.assertEqual(full['skillOverrides'],{})
        self.assertFalse(set(lab.HIDDEN_TOOLS)&set(full['permissions']['deny']))
        self.assertIn('Bash(mcporter config*)',full['permissions']['deny'])

    def test_home_launch_keeps_the_home_folders_local_permission_rules(self):
        home=Path(self.temp.name)/'home';(home/'.claude').mkdir(parents=True)
        (home/'.claude/settings.local.json').write_text(json.dumps({'permissions':{'allow':['Bash(make test)'],'deny':['Bash(rm -rf*)']}}))
        with patch.object(lab,'USER',home), patch.object(lab,'SOURCE',home/'.claude/settings.json'):
            home_perms=lab.lab_permissions({'allow':['Read']},home=True)
            project_perms=lab.lab_permissions({'allow':['Read']},home=False)
        self.assertEqual(home_perms['allow'][:2],['Read','Bash(make test)'])
        self.assertIn('Bash(rm -rf*)',home_perms['deny'])
        self.assertNotIn('Bash(make test)',project_perms['allow'])

    def test_home_verification_selects_one_folder_and_detects_its_shell_changes(self):
        home=Path(self.temp.name)/'home';home.mkdir()
        project=home/'repo';shutil.copytree(ROOT/'demo-project',project)
        run=home/'.local/state/claude-lab/runs/home-test'
        with patch.object(lab,'USER',home), patch.object(lab,'scoped_instructions',return_value=('core','policy')):
            lab.prepare(home,'balanced','auto',run)
            selected=lab.select_project(run,project)
            self.assertEqual(selected['project'],str(project.resolve()))
            cfg=json.loads((run/'runtime.json').read_text())
            self.assertEqual(cfg['launchCwd'],str(home.resolve()))
            lab.dump(run/'acceptance.json',{'checks':[{'argv':['python3','-m','unittest','-q']}]})
            self.assertFalse(lab.verify(run)['passed'])
            (project/'totals.py').write_text('def total_amount(amounts):\n    return sum(amounts)\n')
            passed=lab.verify(run)
            self.assertTrue(passed['passed'])
            self.assertNotEqual(selected['sha256'],passed['workspaceFingerprint'])
            with self.assertRaises(ValueError):lab.select_project(run,home)
            with self.assertRaises(ValueError):lab.select_project(run,run.parent)
            with self.assertRaises(ValueError):lab.select_project(run,home/'missing')

    def test_lab_token_is_token_store_only_and_overrides_credentials_only_in_its_child(self):
        token='sk-ant-oat01-'+'x'*60
        store=Mock();store.get.return_value=token
        original={'ANTHROPIC_API_KEY':'other-key','ANTHROPIC_BASE_URL':'https://example.invalid','PATH':'/usr/bin'}
        with patch.object(lab,'token_store',return_value=store):
            lab.set_token(token)
            store.put.assert_called_once_with('lab',token)
            self.assertNotIn(token,lab.AUTH.read_text())
            child=lab.auth_environment(original)
            self.assertEqual(child['CLAUDE_CODE_OAUTH_TOKEN'],token)
            self.assertNotIn('ANTHROPIC_API_KEY',child)
            self.assertNotIn('ANTHROPIC_BASE_URL',child)
            self.assertEqual(original['ANTHROPIC_API_KEY'],'other-key')
            argv,env=lab.launch_command(self.run)
            self.assertNotIn(token,json.dumps(argv))
            self.assertNotIn(token,(self.run/'settings.json').read_text())
            self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'],token)
            result=lab.auth_command('clear')
            store.delete.assert_called_once_with('lab')
            self.assertFalse(lab.AUTH.exists())
            self.assertEqual(lab.auth_environment(original),original)
            self.assertTrue(result['lab_token_removed'])

    def test_malformed_oauth_input_is_never_stored(self):
        with patch.object(lab,'token_store') as store:
            with self.assertRaises(ValueError):lab.set_token('sk-ant-oat01-'+'x'*60+'?')
            store.assert_not_called()
            self.assertFalse(lab.AUTH.exists())

    def test_resuming_a_capped_run_removes_limits_without_erasing_work(self):
        cfg=json.loads((self.run/'runtime.json').read_text())
        cfg['limits']={'workers':6,'mainSteps':40,'workerSteps':18,'totalSteps':120}
        lab.dump(self.run/'runtime.json',cfg)
        state=json.loads((self.run/'metrics.json').read_text());state['steps']=120;state['mainSteps']=40
        lab.dump(self.run/'metrics.json',state)
        before={p.name:p.read_bytes() for p in self.run.iterdir() if p.name not in {'runtime.json','settings.json'}}
        upgraded=lab.upgrade_run(self.run)
        self.assertIsNone(upgraded['limits'])
        self.assertEqual(upgraded['budgetPolicy'],'soft')
        self.assertEqual(upgraded['compactionPolicy'],'300k')
        env=json.loads((self.run/'settings.json').read_text())['env']
        self.assertEqual(env['CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS'],'4')
        self.assertNotIn('CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS',env)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.run.iterdir() if p.name not in {'runtime.json','settings.json'}})
        turns={a.stem:[l for l in a.read_text().splitlines() if l.startswith('maxTurns:')] for a in (ROOT/'plugin/agents').glob('*.md')}
        self.assertEqual(turns,{'implementer':['maxTurns: 40'],'investigator':['maxTurns: 20'],'reviewer':[],'reasoner':[]})

    def test_an_old_native_run_resumes_with_the_capped_window(self):
        cfg=json.loads((self.run/'runtime.json').read_text())
        cfg.update({'budgetPolicy':'unlimited','compactionPolicy':'native'});lab.dump(self.run/'runtime.json',cfg)
        state=json.loads((self.run/'metrics.json').read_text())
        state['route']={'model':'claude-opus-5-5','effort':'xhigh','reason':'uncertain scope; conservative route','financial':False}
        lab.dump(self.run/'metrics.json',state)
        self.assertEqual(lab.upgrade_run(self.run)['compactionPolicy'],'300k')
        argv,_=lab.launch_command(self.run,resume=True,load_auth=False)
        self.assertIn('--resume',argv)
        self.assertEqual(json.loads((self.run/'metrics.json').read_text())['route']['model'],'claude-opus-5-5')

    def test_context_window_is_capped_unless_the_shell_sets_one(self):
        import os
        for mode in lab.MODES:
            cfg=json.loads((self.run/'runtime.json').read_text());cfg['mode']=mode
            lab.dump(self.run/'runtime.json',cfg)
            with patch.dict(os.environ,{},clear=False):
                os.environ.pop('CLAUDE_CODE_AUTO_COMPACT_WINDOW',None)
                argv,env=lab.launch_command(self.run,load_auth=False)
                self.assertEqual(argv[argv.index('--autocompact')+1],'300k')
            with patch.dict(os.environ,{'CLAUDE_CODE_AUTO_COMPACT_WINDOW':'100000'}):
                argv,env=lab.launch_command(self.run,load_auth=False)
                self.assertNotIn('--autocompact',argv)
                self.assertEqual(env['CLAUDE_CODE_AUTO_COMPACT_WINDOW'],'100000')
                self.assertEqual(os.environ['CLAUDE_CODE_AUTO_COMPACT_WINDOW'],'100000')

    def test_lab_settings_route_effort_overhead_and_mcporter_rules_from_a_fake_source(self):
        fake=Path(self.temp.name)/'fake-settings.json'
        original={'model':'opus[1m]','effortLevel':'xhigh','theme':'dark',
                  'permissions':{'allow':['Bash','mcp__guarded-server__read_note','Bash(mcporter *)','Bash(mcporter:*)'],
                                 'deny':['mcp__guarded-server__delete_note'],'ask':['Bash(git push*)'],'defaultMode':'default'},
                  'enabledPlugins':{'plugin-a@market':True,'plugin-b@market':True,'plugin-c@market':True,
                                    'plugin-d@market':True,'lsp-plugin@market':True,'plugin-e@market':True},
                  'hooks':{'SessionStart':[{'matcher':'startup','hooks':[{'type':'command','command':'cd ~/project && ./session-start-brief'}]}]}}
        fake.write_text(json.dumps(original))
        with patch.object(lab,'SOURCE',fake), patch.dict(os.environ,{'CLAUDE_LAB_DISABLE_PLUGINS':'plugin-a,plugin-b,plugin-c,plugin-d,plugin-e@market'}):
            out=lab.settings(self.run)
        self.assertEqual(json.loads(fake.read_text()),original)
        self.assertEqual(out['model'],'claude-sonnet-5-5')
        self.assertEqual(out['advisorModel'],'opus')
        self.assertEqual(out['modelSettings'],{'claude-sonnet-5-5':{'effortLevel':'medium'},'claude-opus-5-5':{'effortLevel':'high'}})
        self.assertNotIn('effortLevel',out)
        self.assertNotIn('subagentPromptCacheTtl',out)
        self.assertEqual((out['bashOutputMaxChars'],out['crossSessionInbound']),(15000,'hold'))
        env=out['env']
        for key,value in {'CLAUDE_CODE_SUBAGENT_MODEL':'claude-sonnet-5-5','CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL':'claude-sonnet-5-5',
                          'CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS':'4','CLAUDE_CODE_FORK_SUBAGENT':'0','CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH':'1',
                          'MAX_MCP_OUTPUT_TOKENS':'8000','CLAUDE_CODE_GOAL_CHECKIN_MINUTES':'0'}.items():
            self.assertEqual(env[key],value)
        perms=out['permissions']
        self.assertEqual(perms['ask'],['Bash(git push*)']);self.assertEqual(perms['defaultMode'],'default')
        self.assertTrue({'Bash','mcp__guarded-server__read_note'}<=set(perms['allow']))
        self.assertIn('mcp__guarded-server__delete_note',perms['deny'])
        for rule in lab.mcporter_deny():self.assertIn(rule,perms['deny'])
        for rule in ['Bash(*mcporter*guarded-server*)','Bash(mcporter config*)','Bash(npx mcporter*guarded-server*)']:self.assertIn(rule,perms['deny'])
        mcporter_allow=[r for r in perms['allow'] if 'mcporter' in r]
        self.assertEqual(mcporter_allow,lab.MCPORTER_ALLOW)
        self.assertTrue(all(r.startswith(('Bash(mcporter call chrome-devtools.','Bash(mcporter list chrome-devtools')) for r in mcporter_allow))
        plugins=out['enabledPlugins']
        self.assertEqual(plugins,{'lsp-plugin@market':True,'plugin-e@market':False})
        self.assertNotIn('SessionStart',out['hooks'])

    def test_code_first_data_skill_is_present_without_a_model_switch(self):
        skill=(ROOT/'plugin/skills/code-first-data/SKILL.md').read_text()
        front=skill.split('---')[1]
        self.assertIn('name: code-first-data',front)
        self.assertIn('3+ dependent tool calls',front)
        self.assertNotIn('model:',front)
        guide=(ROOT/'plugin/skills/code-first-data/mcporter.md').read_text()
        self.assertIn('NEVER call a protected MCP server',guide)
        for path in ['references/coordinator.md','plugin/skills/work-task/SKILL.md']:
            self.assertIn('Multi-step data or bulk output → harness-lab:code-first-data skill; return summaries, not dumps.',(ROOT/path).read_text())
        for agent in ['implementer','investigator']:
            self.assertIn('Return summaries, not dumps.',(ROOT/f'plugin/agents/{agent}.md').read_text())

    def test_fallback_policy_starts_with_saved_login_and_reads_backup_only_after_switch(self):
        token='sk-ant-oat01-'+'x'*60
        store=Mock();store.get.return_value=token
        with patch.object(lab,'token_store',return_value=store):
            lab.set_token(token);lab.auth_command('fallback');store.get.reset_mock()
            env=lab.auth_environment({'CLAUDE_CODE_OAUTH_TOKEN':'old','ANTHROPIC_API_KEY':'other'})
            self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN',env)
            self.assertNotIn('ANTHROPIC_API_KEY',env)
            store.get.assert_not_called()
            _,primary=lab.launch_command(self.run)
            self.assertEqual(primary['CLAUDE_LAB_AUTH_SOURCE'],'primary')
            self.assertEqual(primary['CLAUDE_LAB_AUTH_FALLBACK'],'1')
            _,backup=lab.launch_command(self.run,resume=True,auth_source='token')
            self.assertEqual(backup['CLAUDE_CODE_OAUTH_TOKEN'],token)
            self.assertEqual(backup['CLAUDE_LAB_AUTH_SOURCE'],'token')
            self.assertNotIn(token,lab.AUTH.read_text())

    def test_owned_account_tokens_and_both_backups_use_their_exact_token_entries(self):
        spec=importlib.util.spec_from_file_location('test_account_metadata',ROOT/'bin/accounts.py')
        accounts=importlib.util.module_from_spec(spec);spec.loader.exec_module(accounts)
        accounts.save(accounts.use_owned(accounts.defaults()),lab.ACCOUNT_REGISTRY)
        store=Mock();store.get.side_effect=lambda name:'offline-'+name
        with patch.object(lab,'token_store',return_value=store):
            for source,entry in [('primary','primary-token'),('secondary','secondary-token'),('token','lab'),('token-last','backup-last')]:
                env=lab.auth_environment({'CLAUDE_CODE_OAUTH_TOKEN':'inherited-dummy'},source)
                self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'],'offline-'+entry)
            self.assertEqual(store.get.call_count,4)

if __name__=='__main__':unittest.main()
