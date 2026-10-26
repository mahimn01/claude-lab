import {expect, mock, test} from 'claude-code/testing';
import {route, evidenceComplete, redact, exhaustedWindows, spawnModel, usageSummary, budgetWarnings, mcporterDenial, configure} from '../hooks/register.js';

function fixture(on, overrides = {}, config = {}, env = {}) {
  const f = {files:new Map(), models:[], efforts:[], calls:[], hash:'source-a', spawns:0, spawnModels:[]};
  const state = {schema:1,workers:0,steps:0,mainSteps:0,agents:{},models:{},revision:0,
    codeEdited:false,verification:null,review:null,route:null,stopNudged:false,checkpoint:false,
    workspaceFingerprint:'source-a',taskSerial:0,runtimeReady:false,...overrides};
  f.files.set('/lab/run/runtime.json', JSON.stringify({project:'/project',mode:'balanced',modelOverride:'auto',limits:{workers:6,mainSteps:40,workerSteps:18,totalSteps:120},...config}));
  f.files.set('/lab/run/metrics.json',JSON.stringify(state));
  f.files.set('/lab/run/financial-policy.md','Use the actual current financial policy; notes are not trade authorization.');
  mock.env(on,{CLAUDE_LAB_ROOT:'/lab/root',CLAUDE_LAB_RUN_DIR:'/lab/run',...env});
  on('fs.read',($,e) => ({value:f.files.get(e.path) || ''}));
  on('fs.write',($,e) => {f.files.set(e.path,e.text); return {value:undefined};});
  on('command.register',() => ({value:undefined}));
  on('tool.register',() => ({value:undefined}));
  on('ui.log',() => ({value:undefined}));
  on('session.start',($,e) => ({cwd:e.cwd}));
  on('session.end',() => ({sessionId:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}));
  on('session.id',() => ({value:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}));
  on('session.usage',() => ({value:{context:{tokens:0,window:1000000,percent:0},rateLimits:f.windows || [{kind:'weekly',percentUsed:60,resetsAt:0}]}}));
  on('session.measure',($,e) => ({changed:e.changed}));
  on('turn.start',($,e) => ({turnId:e.turnId}));
  on('prompt.submit',($,e) => ({text:e.text,context:e.context}));
  on('agent.list',() => ({value:f.liveAgents || []}));
  on('agent.spawn',($,e) => {f.spawns++;f.spawnModels.push(e.model);return {model:e.model || 'claude-sonnet-5-5',agentId:'worker-'+f.spawns};});
  on('process.run',($,e) => {
    const cfg=JSON.parse(f.files.get('/lab/run/runtime.json'));
    if(e.argv.includes('scope')) {
      cfg.verificationProject=e.argv[e.argv.indexOf('--project')+1];
      f.files.set('/lab/run/runtime.json',JSON.stringify(cfg));
    }
    const unscoped=cfg.homeWorkspace && !cfg.verificationProject;
    return {value:{exitCode:0,stdout:JSON.stringify({sha256:unscoped ? null : f.hash,sourceFiles:unscoped ? 0 : 2,scopeRequired:unscoped,project:cfg.verificationProject || (unscoped ? null : cfg.project)}),stderr:''}};
  });
  on('turn.step',async function* ($,e) {
    f.models.push(e.model);f.efforts.push(e.effort);
    yield {kind:'text',index:0,text:'checked'};
    return {turnId:e.turnId,index:e.index,answer:'checked',toolUses:[],stopReason:'end_turn',
      usage:{model:e.model,input_tokens:10,output_tokens:5,cache_read_input_tokens:100,cache_creation_input_tokens:20}};
  });
  on('turn.complete',() => ({text:''}));
  on('classic.Stop',() => ({}));
  on('tool.call',($,e) => {f.calls.push(e.tool);return {result:{stdout:f.stdout || 'ok',stderr:f.stderr || '',interrupted:false}};});
  return f;
}

async function start($) {return $.session.start({cwd:'/project',surface:'terminal',isInteractive:true});}
async function prompt($,text) {return $.prompt.submit({text,origin:{kind:'human'},wait:false});}
async function step($,agentId = undefined,index = 0,model = 'claude-sonnet-5-5') {
  const stream = $.turn.step({turnId:'turn-1',index,model,messageCount:1,...(agentId ? {agentId}: {})});
  let item = await stream.next();
  while (!item.done) item = await stream.next();
  return item.value;
}
const SONNET='claude-sonnet-5-5', OPUS='claude-opus-5-5';

test('routing defaults to Sonnet; hard words only flag a reasoner hint; broker work is Sonnet high',async () => {
  expect(route('Implement pagination in the existing API')).toMatchObject({model:SONNET,effort:'medium',hard:false});
  expect(route('Find the race condition between the workers')).toMatchObject({model:SONNET,effort:'medium',hard:true});
  expect(route('Prove this theorem').model).toBe(SONNET);
  expect(route('unclear goal')).toMatchObject({model:SONNET,effort:'medium'});
  expect(route('Review current IBKR orders')).toMatchObject({model:SONNET,effort:'high',financial:true});
  expect(route('fix the trading-dashboard README').financial).toBe(false);
  expect(route('rebalance the portfolio margin page layout').financial).toBe(false);
  expect(route('configure the Kafka broker and the Celery brokers').financial).toBe(false);
  expect(route('pick an options strategy for next month').financial).toBe(true);
  expect(route('roll the short call on my account').financial).toBe(true);
  configure({financialTerms:['acme-broker','my.strategy']});
  expect(route('check the acme-broker positions').financial).toBe(true);
  expect(route('explain my.strategy').financial).toBe(true);
  expect(route('explain myXstrategy').financial).toBe(false);
  configure({});
  expect(route('check the acme-broker positions').financial).toBe(false);
  expect(route('anything','opus')).toMatchObject({model:OPUS,effort:'xhigh'});
  expect(route('anything','auto',true)).toMatchObject({model:SONNET,effort:'high',financial:true});
});

test('spawn models: the router picks every worker model; Opus only for reviewer and reasoner',async () => {
  expect(spawnModel('harness-lab:reviewer')).toBe(OPUS);
  expect(spawnModel('harness-lab:reasoner')).toBe(OPUS);
  expect(spawnModel('staff-reviewer')).toBe(OPUS);
  expect(spawnModel('other-plugin:finish-reviewer')).toBe(SONNET);
  expect(spawnModel('harness-lab:implementer')).toBe(SONNET);
  expect(spawnModel('harness-lab:investigator')).toBe(SONNET);
  expect(spawnModel('harness-lab:implementer','opus')).toBe(SONNET);
  for (const type of ['general-purpose','Explore','Plan','fork','finance-analyst','unknown-agent']) expect(spawnModel(type)).toBe(SONNET);
  expect(spawnModel('general-purpose','opus')).toBe(SONNET);
  expect(spawnModel('general-purpose','haiku')).toBe('haiku');
});

test('native startup activates the readiness marker and retains normal next behavior',async ($,on) => {
  const f=fixture(on); await start($);
  expect(JSON.parse(f.files.get('/lab/run/metrics.json')).runtimeReady).toBe(true);
});

test('the lead stays on Sonnet across prompts; a hard prompt adds a reasoner hint instead of a switch',async ($,on) => {
  const f=fixture(on);await start($);
  await prompt($,'Implement pagination');await step($);
  const hard=await prompt($,'Investigate a race condition');await step($,undefined,1);
  await prompt($,'Update the documentation');await step($,undefined,2);
  expect(f.models).toEqual([SONNET,SONNET,SONNET]);
  expect(f.efforts).toEqual(['medium','medium','medium']);
  expect(hard.context.join('\n').includes('spawn harness-lab:reasoner once')).toBe(true);
  expect(hard.context.join('\n').includes('usage counters never stop work')).toBe(false);
  const again=await prompt($,'Now find the root cause of the deadlock');
  expect(again.context.join('\n').includes('spawn harness-lab:reasoner once')).toBe(false);
});

test('routing ignores the project path, so a repository with a trading-style name is not a financial task',async ($,on) => {
  const f=fixture(on,{verificationProject:'/home/me/trading-dashboard'},{project:'/home/me/trading-dashboard'});await start($);
  const answer=await prompt($,'Fix the README typo');await step($);
  expect(answer.context.join('\n').includes('SCOPED FINANCIAL POLICY')).toBe(false);
  expect(f.models).toEqual([SONNET]);
  expect(JSON.parse(f.files.get('/lab/run/metrics.json')).route.financial).toBe(false);
});

test('financial context is scoped to a financial prompt, runs Sonnet high and requires an Opus review',async ($,on) => {
  const f=fixture(on);await start($);
  const normal=await prompt($,'Fix the CSS spacing');
  expect(normal.context.join('\n').includes('SCOPED FINANCIAL POLICY')).toBe(false);
  const financial=await prompt($,'Review IBKR margin');await step($);
  expect(financial.context.join('\n').includes('SCOPED FINANCIAL POLICY')).toBe(true);
  expect(financial.context.join('\n').includes('harness-lab:reviewer (Opus) review')).toBe(true);
  expect(f.models).toEqual([SONNET]);expect(f.efforts).toEqual(['high']);
  const follow=await prompt($,'and the next one?');
  expect(follow.context.join('\n').includes('SCOPED FINANCIAL POLICY')).toBe(false);
  const state=JSON.parse(f.files.get('/lab/run/metrics.json'));
  expect(state.route.financial).toBe(true);
  expect(evidenceComplete({...state,checkpoint:true},null)).toBe(false);
  expect(evidenceComplete({...state,checkpoint:true,review:{approved:true}},null)).toBe(true);
});

test('a lab-model choice waits for the next task unless "now" is given',async ($,on) => {
  const f=fixture(on);await start($);
  await prompt($,'Implement pagination');await step($);
  const answer=await $.command.run({command:'lab-model',args:'opus'});
  expect(answer.text.includes('next task')).toBe(true);
  await prompt($,'continue');await step($,undefined,1);
  await $.command.run({command:'lab-new',args:''});
  await prompt($,'Implement the next feature');await step($,undefined,2);
  await $.command.run({command:'lab-model',args:'sonnet now'});
  await step($,undefined,3);
  expect(f.models).toEqual([SONNET,SONNET,OPUS,SONNET]);
  expect(f.efforts[2]).toBe('xhigh');
});

test('clear releases the pinned lead model for the next prompt',async ($,on) => {
  const f=fixture(on,{},{modelOverride:'auto'});await start($);
  await prompt($,'Implement pagination');
  await $.command.run({command:'lab-model',args:'opus'});
  await $.session.end({reason:'clear'});
  await prompt($,'New unrelated task');await step($);
  expect(f.models).toEqual([OPUS]);
});

test('clear keeps a financial task financial and sends the financial policy again',async ($,on) => {
  fixture(on);await start($);
  await prompt($,'Review my IBKR covered calls');
  await $.session.end({reason:'clear'});
  const next=await prompt($,'Read context.md and continue');
  expect(next.context.join('\n').includes('SCOPED FINANCIAL POLICY')).toBe(true);
});

test('a passing check run resets the failure count',async ($,on) => {
  const f=fixture(on);await start($);await prompt($,'Implement a bounded fix');
  const verify=async passed => {
    f.files.set('/lab/run/verified-checks.json',JSON.stringify({passed,revision:0,taskSerial:0,workspaceFingerprint:'source-a'}));
    return JSON.parse((await $.tool.call({tool:'mcp__harness-lab__verify'})).result);
  };
  await verify(false);await verify(true);
  expect((await verify(false)).next).toBe(undefined);
  expect((await verify(false)).next.includes('harness-lab:reasoner')).toBe(true);
});

test('an old run with an escalated Opus route re-routes to Sonnet on its next prompt',async ($,on) => {
  const f=fixture(on,{route:{model:OPUS,effort:'xhigh',reason:'uncertain scope; conservative route',financial:false}});await start($);
  await prompt($,'continue the task');await step($);
  expect(f.models).toEqual([SONNET]);
});

test('workers keep the model and effort their spawn resolved',async ($,on) => {
  const f=fixture(on);await start($);await prompt($,'Implement pagination');
  const worker=await $.agent.spawn({prompt:'Implement one scoped change',subagentType:'harness-lab:implementer'});
  await $.agent.spawn({prompt:'Find the call sites',subagentType:'Explore'});
  await $.agent.spawn({prompt:'Review the change',subagentType:'harness-lab:reviewer'});
  expect(f.spawnModels).toEqual([SONNET,SONNET,OPUS]);
  await step($,worker.agentId,0,'claude-haiku-5-5');
  expect(f.models).toEqual(['claude-haiku-5-5']);
  expect(f.efforts).toEqual([undefined]);
  expect(JSON.parse(f.files.get('/lab/run/metrics.json')).agents[worker.agentId].model).toBe(SONNET);
});

test('status shows the Opus share of served calls and soft-budget warnings',async ($,on) => {
  expect(usageSummary({[OPUS]:{requests:1},[SONNET]:{requests:3}}).opusShare).toBe(25);
  expect(budgetWarnings({workers:5,reviews:3,models:{}}).length).toBe(2);
  expect(budgetWarnings({workers:1,models:{[SONNET]:{requests:1,cache_creation_input_tokens:2500000}}})[0].includes('stop and ask')).toBe(true);
  expect(budgetWarnings({workers:1,models:{[SONNET]:{requests:1,cache_read_input_tokens:50000000}}}).length).toBe(0);
  const f=fixture(on,{models:{[SONNET]:{requests:3,cache_creation_input_tokens:2500000,cache_read_input_tokens:9000000},[OPUS]:{requests:1}}});await start($);
  const status=JSON.parse((await $.command.run({command:'lab-status',args:''})).text).status;
  expect(status.includes('Opus 25% of 4 calls')).toBe(true);
  expect(status.includes('(+9.0M cache reads)')).toBe(true);
  expect(status.includes('OVER SOFT BUDGET')).toBe(true);
  const answer=await prompt($,'Keep going');
  expect(answer.context.join('\n').includes('SOFT BUDGET EXCEEDED')).toBe(true);
  const after=await prompt($,'Yes, continue');
  expect(after.context.join('\n').includes('SOFT BUDGET EXCEEDED')).toBe(false);
});

test('mcporter cannot reach a protected server or print its config',async ($,on) => {
  configure({mcporterBlock:['guarded-server']});
  expect(mcporterDenial('mcporter call guarded-server.read_note path=x')).toBeTruthy();
  expect(mcporterDenial('npx mcporter call --server guarded_server --tool write_note')).toBeTruthy();
  expect(mcporterDenial('mcporter config list')).toBeTruthy();
  expect(mcporterDenial('mcporter --log-level debug config get chrome-devtools')).toBeTruthy();
  expect(mcporterDenial('mcporter --config ./x.json call chrome-devtools.list_pages')).toBe(null);
  expect(mcporterDenial('mcporter call chrome-devtools.list_network_requests --output json | jq length')).toBe(null);
  const f=fixture(on,{},{mcporterBlock:['guarded-server']});await start($);
  const denied=await $.tool.call({tool:'Bash',command:'cd /tmp && mcporter call guarded-server.write_note path=a'});
  expect(denied.deny.includes('protected')).toBe(true);
  const monitored=await $.tool.call({tool:'Monitor',command:'mcporter call guarded-server.search_notes query=x'});
  expect(monitored.deny.includes('protected')).toBe(true);
  const allowed=await $.tool.call({tool:'Bash',command:'mcporter call chrome-devtools.list_pages'});
  expect(allowed.deny).toBe(undefined);
  expect(f.calls).toEqual(['Bash']);
});

test('worker starts and review remain available beyond obsolete stored budgets',async ($,on) => {
  const f=fixture(on,{workers:10000});await start($);
  const launches=await Promise.all(Array.from({length:10},() => $.agent.spawn({prompt:'Implement one scoped change',subagentType:'harness-lab:implementer'})));
  expect(launches.filter(x => !x.deny).length).toBe(10);
  const review=await $.agent.spawn({prompt:'Independently inspect the completed change',subagentType:'harness-lab:reviewer'});
  expect(review.model).toBe('claude-opus-5-5');
  const extra=await $.agent.spawn({prompt:'Implement another change',subagentType:'harness-lab:implementer'});
  expect(Boolean(extra.deny)).toBe(false);
  expect(f.spawns).toBe(12);
});

test('worker requests continue beyond the old worker turn budget',async ($,on) => {
  const f=fixture(on);await start($);
  const worker=await $.agent.spawn({prompt:'Implement the specified fix',subagentType:'harness-lab:implementer'});
  for(let i=0;i<18;i++) await step($,worker.agentId,i);
  const next=await step($,worker.agentId,18);
  expect(next.answer).toBe('checked');
  expect(f.models.length).toBe(19);
});

test('lead and combined requests continue beyond old caps without resetting counters',async ($,on) => {
  const f=fixture(on,{steps:120000,mainSteps:40000});await start($);
  const next=await step($);
  expect(next.answer).toBe('checked');
  expect(f.models.length).toBe(1);
  const state=JSON.parse(f.files.get('/lab/run/metrics.json'));
  expect(state.steps).toBe(120001);
  expect(state.mainSteps).toBe(40001);
});

test('a normal permission denial passes through unchanged',async ($,on) => {
  fixture(on);on('tool.check',() => ({decision:'deny',reason:'existing permission guard'}));await start($);
  // tool.call itself has a stub; tool.check tests that no lab approval hook exists.
  const denied=await $.tool.check({tool:'Bash',input:{command:'echo test'}});
  expect(denied.decision).toBe('deny');
});

test('completion rejects missing checks, failed tests, or stale source fingerprints',async () => {
  const state={checkpoint:true,codeEdited:true,revision:2,taskSerial:0,workspaceFingerprint:'now',review:{approved:true,revision:2,workspaceFingerprint:'now'}};
  const evidence={passed:true,revision:2,taskSerial:0,workspaceFingerprint:'now'};
  expect(evidenceComplete(state,evidence)).toBe(true);
  expect(evidenceComplete(state,{...evidence,passed:false})).toBe(false);
  expect(evidenceComplete(state,{...evidence,workspaceFingerprint:'old'})).toBe(false);
  expect(evidenceComplete(state,{...evidence,revision:1})).toBe(false);
  expect(evidenceComplete({...state,review:null},evidence)).toBe(false);
  expect(evidenceComplete({...state,unresolved:['Unimplemented requirement']},evidence)).toBe(false);
});

test('a source change made outside Write/Edit is detected at the completion gate',async ($,on) => {
  const f=fixture(on,{checkpoint:true});await start($);f.hash='changed-through-shell';
  const stop=await $.classic.Stop({session_id:'session',transcript_path:'/transcript',cwd:'/project',hook_event_name:'Stop',stop_hook_active:false,last_assistant_message:'Done'});
  expect(stop.block.includes('acceptance checks')).toBe(true);
  const state=JSON.parse(f.files.get('/lab/run/metrics.json'));
  expect(state.codeEdited).toBe(true);
  expect(state.workspaceFingerprint).toBe('changed-through-shell');
});

test('a chat-only turn finishes without the checkpoint reminder; tool use or broker work still gets it',async ($,on) => {
  const stopEvent={session_id:'s',transcript_path:'/t',cwd:'/project',hook_event_name:'Stop',stop_hook_active:false,last_assistant_message:'OK'};
  let f=fixture(on);await start($);await prompt($,'Reply with exactly: OK');
  expect((await $.classic.Stop(stopEvent)).block).toBe(undefined);
  await $.tool.call({tool:'Bash',command:'ls'});
  expect((await $.classic.Stop(stopEvent)).block.includes('checkpoint')).toBe(true);
});

test('broker questions keep the checkpoint reminder even without tools',async ($,on) => {
  fixture(on);await start($);await prompt($,'Should I roll the short call on my account?');
  const stop=await $.classic.Stop({session_id:'s',transcript_path:'/t',cwd:'/project',hook_event_name:'Stop',stop_hook_active:false,last_assistant_message:'Hold'});
  expect(stop.block.includes('harness-lab:reviewer')).toBe(true);
});

test('API credential patterns are removed from compact handoffs',async () => {
  const token='sk-ant-'+'x'.repeat(30);
  expect(redact('temporary token '+token)).toBe('temporary token [REDACTED]');
});

test('checkpoint writes a compact contract and the verify tool reaches normal Bash handling',async ($,on) => {
  const f=fixture(on);await start($);
  await $.tool.call({tool:'mcp__harness-lab__checkpoint',context:'src/totals.py',plan:'Preserve signed amounts',implementation:'One-line fix',unresolved:[],criteria:['refund reduces total'],checks:[{argv:['python3','-m','unittest','-q']}]});
  expect(JSON.parse(f.files.get('/lab/run/acceptance.json')).checks[0].argv).toEqual(['python3','-m','unittest','-q']);
  await $.tool.call({tool:'mcp__harness-lab__verify'});
  expect(f.calls.includes('Bash')).toBe(true);
});

test('actual reviewer completion and current checker evidence allow a verified finish',async ($,on) => {
  const f=fixture(on,{checkpoint:true,codeEdited:true});await start($);
  f.files.set('/lab/run/verified-checks.json',JSON.stringify({passed:true,revision:0,taskSerial:0,workspaceFingerprint:'source-a'}));
  const reviewer=await $.agent.spawn({prompt:'Review final code and checker evidence',subagentType:'harness-lab:reviewer'});
  await $.turn.complete({turnId:'review',agentId:reviewer.agentId,answer:'{"approved":true,"findings":[]}',durationMs:10,isAborted:false,reason:'answer'});
  const stop=await $.classic.Stop({session_id:'s',transcript_path:'/t',cwd:'/project',hook_event_name:'Stop',stop_hook_active:false,last_assistant_message:'Finished'});
  expect(stop.block).toBe(undefined);
  expect(JSON.parse(f.files.get('/lab/run/metrics.json')).evidenceComplete).toBe(true);
});

test('a task reset archives metrics and refuses old verification evidence',async ($,on) => {
  const f=fixture(on,{checkpoint:true,codeEdited:true});await start($);
  const answer=await $.command.run({command:'lab-new',args:''});
  expect(answer.text.includes('New task handoff')).toBe(true);
  expect(f.files.has('/lab/run/archive-0.json')).toBe(true);
  expect(JSON.parse(f.files.get('/lab/run/metrics.json')).taskSerial).toBe(1);
  expect(JSON.parse(f.files.get('/lab/run/metrics.json')).runtimeReady).toBe(true);
});

test('two real checker failures keep the lead model and return one reasoner hint',async ($,on) => {
  const f=fixture(on);await start($);await prompt($,'Implement a bounded fix');
  f.files.set('/lab/run/verified-checks.json',JSON.stringify({passed:false,revision:0,taskSerial:0,workspaceFingerprint:'source-a'}));
  const first=JSON.parse((await $.tool.call({tool:'mcp__harness-lab__verify'})).result);
  const second=JSON.parse((await $.tool.call({tool:'mcp__harness-lab__verify'})).result);
  const third=JSON.parse((await $.tool.call({tool:'mcp__harness-lab__verify'})).result);
  expect(first.next).toBe(undefined);
  expect(second.next.includes('harness-lab:reasoner')).toBe(true);
  expect(third.next).toBe(undefined);
  await step($);
  expect(f.models[0]).toBe(SONNET);
});

test('a rejected review does not switch the lead; the next prompt carries the reasoner hint',async ($,on) => {
  const f=fixture(on,{checkpoint:true,codeEdited:true});await start($);await prompt($,'Implement a bounded fix');
  const reviewer=await $.agent.spawn({prompt:'Review final code',subagentType:'harness-lab:reviewer'});
  expect(reviewer.model).toBe(OPUS);
  await $.turn.complete({turnId:'review',agentId:reviewer.agentId,answer:'{"approved":false,"findings":["missing test"]}',durationMs:10,isAborted:false,reason:'answer'});
  const next=await prompt($,'fix it');await step($);
  expect(f.models).toEqual([SONNET]);
  expect(next.context.join('\n').includes('did not approve')).toBe(true);
  expect(JSON.parse(f.files.get('/lab/run/metrics.json')).route.model).toBe(SONNET);
});

test('recorded request usage uses the served model and counts all cache categories',async ($,on) => {
  const f=fixture(on);await start($);await prompt($,'Implement pagination');await step($);
  const metrics=JSON.parse(f.files.get('/lab/run/metrics.json'));
  expect(metrics.models['claude-sonnet-5-5'].requests).toBe(1);
  expect(metrics.models['claude-sonnet-5-5'].cache_read_input_tokens).toBe(100);
  expect(metrics.planStart[0].percentUsed).toBe(60);
});

test('lab controls refuse persisted changes to the ordinary model setting',async ($,on) => {
  fixture(on);
  const answer=await $.config.set({key:'model',value:'claude-opus-5-5'});
  expect(answer.deny.includes('saved Claude settings unchanged')).toBe(true);
});

test('damaged lab state refuses a model request rather than bypassing routing',async ($,on) => {
  const f=fixture(on);f.files.set('/lab/run/metrics.json','invalid JSON');
  const result=await step($);
  expect(result.answer.includes('no model request sent')).toBe(true);
  expect(f.models.length).toBe(0);
});

test('large stdout keeps its head and tail, preserves stderr, and saves a local copy',async ($,on) => {
  const f=fixture(on);f.stdout='HEAD\n'+'a'.repeat(24000)+'\nTAIL';f.stderr='Important error';await start($);
  const answer=await $.tool.call({tool:'Bash',command:'echo fixture',tool_use_id:'output-test'});
  expect(answer.result.stdout.startsWith('HEAD')).toBe(true);
  expect(answer.result.stdout.endsWith('TAIL')).toBe(true);
  expect(answer.result.stdout.length<10000).toBe(true);
  expect(answer.result.stderr).toBe('Important error');
  expect(f.files.get('/lab/run/tool-output-output-test.log')).toBe(f.stdout);
});

test('home sessions browse without a scope and prevent unscoped editing or verification',async ($,on) => {
  const f=fixture(on,{scopeRequired:true,verificationProject:null,workspaceFingerprint:null},{homeWorkspace:true,project:'/home',verificationProject:null});await start($);
  const browse=await $.tool.call({tool:'Bash',command:'ls /home'});
  expect(browse.deny).toBe(undefined);
  const edit=await $.tool.call({tool:'Write',file_path:'/home/repo/code.py',content:'print(1)'});
  expect(edit.deny.includes('work folder')).toBe(true);
  const verify=await $.tool.call({tool:'mcp__harness-lab__verify'});
  expect(verify.result.includes('Select the specific code folder')).toBe(true);
  expect(f.calls.length).toBe(1);
  const worker=await $.agent.spawn({prompt:'Review code',subagentType:'harness-lab:reviewer'});
  expect(worker.deny.includes('Select the code folder')).toBe(true);
});

test('a home project selection invalidates old evidence and scopes subsequent code edits',async ($,on) => {
  const f=fixture(on,{scopeRequired:true,verificationProject:null,workspaceFingerprint:null,checkpoint:true,review:{approved:true}},{homeWorkspace:true,project:'/home',verificationProject:null});await start($);
  const selected=await $.tool.call({tool:'mcp__harness-lab__select_project',path:'/home/repo'});
  expect(selected.result.includes('Code verification folder: /home/repo')).toBe(true);
  const state=JSON.parse(f.files.get('/lab/run/metrics.json'));
  expect(state.scopeRequired).toBe(false);
  expect(state.workspaceFingerprint).toBe('source-a');
  expect(state.review).toBe(null);
  expect(state.checkpoint).toBe(false);
  expect(JSON.parse(f.files.get('/lab/run/runtime.json')).project).toBe('/home');
  const edit=await $.tool.call({tool:'Write',file_path:'/home/repo/code.py',content:'print(1)'});
  expect(edit.deny).toBe(undefined);
  const outside=await $.tool.call({tool:'Write',file_path:'/home/another/code.py',content:'print(2)'});
  expect(outside.deny.includes('work folder')).toBe(true);
});

test('unscoped home completion cannot count code edits as verified',async () => {
  const state={checkpoint:true,codeEdited:true,scopeRequired:true,revision:0,workspaceFingerprint:null,review:{approved:true,revision:0,workspaceFingerprint:null}};
  expect(evidenceComplete(state,{passed:true,revision:0,taskSerial:0,workspaceFingerprint:null})).toBe(false);
});

test('quota fallback recognizes shared windows and excludes family limits or expired bars',async () => {
  expect(exhaustedWindows([{kind:'seven_day',percentUsed:100}]).length).toBe(1);
  expect(exhaustedWindows([{kind:'seven_day_opus',percentUsed:100}]).length).toBe(0);
  expect(exhaustedWindows([{kind:'five_hour',percentUsed:99}]).length).toBe(0);
  expect(exhaustedWindows([{kind:'seven_day',percentUsed:100,resetsAt:'2000-01-01T00:00:00Z'}]).length).toBe(0);
});

test('fallback control is ready only after a main error at a shared quota and idle workers',async ($,on) => {
  const f=fixture(on,{}, {}, {CLAUDE_LAB_AUTH_SOURCE:'primary',CLAUDE_LAB_AUTH_FALLBACK:'1',CLAUDE_LAB_AUTH_GENERATION:'generation'});
  await start($);f.windows=[{kind:'seven_day',percentUsed:100}];
  await $.session.measure({context:{tokens:0,window:1000000,percent:0},rateLimits:f.windows,changed:['rateLimits']});
  expect(JSON.parse(f.files.get('/lab/run/auth-control.json')).phase).toBe('idle');
  f.liveAgents=[{id:'busy',status:'running'}];
  await $.turn.complete({turnId:'main',answer:'',durationMs:1,isAborted:false,reason:'error'});
  expect(JSON.parse(f.files.get('/lab/run/auth-control.json')).phase).toBe('pending');
  f.liveAgents=[];
  await $.session.measure({context:{tokens:0,window:1000000,percent:0},rateLimits:f.windows,changed:['rateLimits']});
  expect(JSON.parse(f.files.get('/lab/run/auth-control.json')).phase).toBe('ready');
  expect(JSON.parse(f.files.get('/lab/run/auth-control.json')).source).toBe('primary');
});

test('backup idle state supports returning between turns while workers prevent a switch',async ($,on) => {
  const f=fixture(on,{}, {}, {CLAUDE_LAB_AUTH_SOURCE:'token',CLAUDE_LAB_AUTH_FALLBACK:'1',CLAUDE_LAB_AUTH_GENERATION:'generation'});
  await start($);
  await $.turn.complete({turnId:'main',answer:'done',durationMs:1,isAborted:false,reason:'answer'});
  let control=JSON.parse(f.files.get('/lab/run/auth-control.json'));
  expect(control.phase).toBe('idle');expect(control.source).toBe('token');
  f.liveAgents=[{id:'busy',status:'idle'}];
  await $.session.measure({context:{tokens:0,window:1000000,percent:0},rateLimits:[],changed:['rateLimits']});
  control=JSON.parse(f.files.get('/lab/run/auth-control.json'));
  expect(control.phase).toBe('pending');expect(control.workersIdle).toBe(false);
  f.liveAgents=[];await $.turn.start({turnId:'next'});
  expect(JSON.parse(f.files.get('/lab/run/auth-control.json')).leadIdle).toBe(false);
});

test('worker completion retains main quota evidence and clear invalidates the previous boundary',async ($,on) => {
  const f=fixture(on,{}, {}, {CLAUDE_LAB_AUTH_SOURCE:'primary',CLAUDE_LAB_AUTH_FALLBACK:'1',CLAUDE_LAB_AUTH_GENERATION:'generation'});
  await start($);f.windows=[{kind:'seven_day',percentUsed:100}];f.liveAgents=[{id:'worker',status:'running'}];
  await $.turn.complete({turnId:'main',answer:'',durationMs:1,isAborted:false,reason:'error'});
  await $.turn.start({turnId:'child',agentId:'worker'});f.liveAgents=[];
  await $.turn.complete({turnId:'child',agentId:'worker',answer:'done',durationMs:1,isAborted:false,reason:'answer'});
  expect(JSON.parse(f.files.get('/lab/run/auth-control.json')).phase).toBe('ready');
  await $.session.end({reason:'clear'});
  const control=JSON.parse(f.files.get('/lab/run/auth-control.json'));
  expect(control.phase).toBe('pending');expect(control.hasMainTurn).toBe(false);
});
