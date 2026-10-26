// Claude Lab runs only when explicitly loaded by the separate launcher.
// It routes at task/worker boundaries, never approves permissions, and keeps
// compact task state outside the user's repositories.
// Budgets are soft: counters feed status warnings and guidance; they never stop work.
let SONNET = 'claude-sonnet-5-5';
let OPUS = 'claude-opus-5-5';
// Broker and order-execution terms only: "trading" or "portfolio" also name ordinary repositories.
// Add your own terms (broker names, strategy words) with CLAUDE_LAB_FINANCIAL_TERMS; the launcher copies them
// into the run's runtime.json as financialTerms.
const FINANCIAL = /\b(brokerage|ibkr|interactive brokers|options? strateg(?:y|ies)|covered calls?|short (?:puts?|calls?)|iron condors?|credit spreads?|(?:stock|option|limit|stop) orders?)\b/i;
let extraFinancial = null;
let blockedServers = [];
const escapeRe = (text) => String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// Called with the run's runtime.json whenever it is read: extra financial terms, MCP servers mcporter must not
// reach, and the pinned model ids.
export function configure(config = {}) {
  const terms = (config.financialTerms || []).filter(Boolean);
  extraFinancial = terms.length ? new RegExp('\\b(?:' + terms.map(escapeRe).join('|') + ')\\b', 'i') : null;
  blockedServers = (config.mcporterBlock || []).filter(Boolean).map(String);
  SONNET = config.sonnetModel || 'claude-sonnet-5-5';
  OPUS = config.opusModel || 'claude-opus-5-5';
}
const isFinancial = (text) => FINANCIAL.test(text) || Boolean(extraFinancial && extraFinancial.test(text));
const HARD = /\b(architect(?:ure|ural)?|cross[- ]file|security|vulnerabilit\w*|cryptograph\w*|proof|prove|theorem|mathematical|race condition|deadlock|root cause|ambiguous|hard debugging|independent review|critical review)\b/i;
const OPUS_ROLE = /^(?:harness-lab:(?:reviewer|reasoner)|staff-reviewer)$/;
const REVIEW_ROLE = /^(?:harness-lab:reviewer|staff-reviewer)$/;
const SOFT_BUDGET = {workers:4, reviews:2, tokens:2e6};
const TOKEN_KEYS = ['input_tokens','output_tokens','cache_creation_input_tokens'];
const EFFORTS = ['low','medium','high','xhigh','max'];

export function redact(text) {
  return String(text).replace(/AIza[\w-]{25,}|sk-(?:ant|proj)-[\w-]{15,}|Bearer\s+[\w.-]{20,}/gi, '[REDACTED]');
}

// Routes the lead on the user's own words. Sonnet is the default; hard questions get a
// reasoner hint instead of a model switch, and financial work adds a mandatory Opus review.
export function route(text, override = 'auto', financialTask = false) {
  const financial = financialTask || isFinancial(text);
  const hard = HARD.test(text);
  if (override === 'opus') return {model: OPUS, effort: 'xhigh', reason: 'user override', financial, hard};
  if (financial) return {model: SONNET, effort: 'high', reason: 'financial task; Opus review required', financial, hard};
  const reason = override === 'sonnet' ? 'user override' : hard ? 'hard question; spawn harness-lab:reasoner for it' : 'default route';
  return {model: SONNET, effort: 'medium', reason, financial, hard};
}

// The router picks every worker's model (agent files carry no model line): Opus only for
// review and hard reasoning, Sonnet for the rest; an explicit Haiku or Sonnet request is kept.
export function spawnModel(type = '', requested = '') {
  if (OPUS_ROLE.test(type)) return OPUS;
  if (/haiku|sonnet/i.test(requested)) return requested;
  return SONNET;
}

export function usageSummary(models = {}) {
  let calls = 0, opus = 0, tokens = 0, cacheReads = 0;
  for (const [model, bucket] of Object.entries(models)) {
    calls += bucket.requests || 0;
    if (/opus/i.test(model)) opus += bucket.requests || 0;
    for (const key of TOKEN_KEYS) tokens += bucket[key] || 0;
    cacheReads += bucket.cache_read_input_tokens || 0;
  }
  // Cache reads are cheap and grow with every call, so the budget counts new tokens only.
  return {calls, opusShare: calls ? Math.round(100 * opus / calls) : 0, tokens, cacheReads};
}

export function budgetWarnings(state) {
  const usage = usageSummary(state.models);
  const warnings = [];
  if (state.workers > SOFT_BUDGET.workers) warnings.push(`${state.workers} workers (guide: ${SOFT_BUDGET.workers})`);
  if ((state.reviews || 0) > SOFT_BUDGET.reviews) warnings.push(`${state.reviews} reviews (guide: one review plus one re-review)`);
  if (usage.tokens > SOFT_BUDGET.tokens) warnings.push(`${(usage.tokens / 1e6).toFixed(1)}M new tokens (guide: 2M); stop and ask the user`);
  return warnings;
}

export function evidenceComplete(state, checks) {
  if (!state.checkpoint || state.unresolved?.length) return false;
  if (state.route?.financial && !state.review?.approved) return false;
  if (!state.codeEdited) return true;
  if (state.scopeRequired) return false;
  return Boolean(checks?.passed && checks.revision === state.revision &&
    checks.taskSerial === (state.taskSerial || 0) && state.review?.approved &&
    state.review.revision === state.revision && checks.workspaceFingerprint === state.workspaceFingerprint &&
    state.review.workspaceFingerprint === state.workspaceFingerprint);
}

export function exhaustedWindows(windows, now = Date.now()) {
  return (windows || []).filter(w => ['five_hour','seven_day'].includes(w.kind) &&
    Number.isFinite(w.percentUsed) && w.percentUsed >= 100 &&
    (!w.resetsAt || (Number.isFinite(Date.parse(w.resetsAt)) && Date.parse(w.resetsAt) > now)))
    .map(w => ({kind:w.kind,percentUsed:w.percentUsed,...(w.resetsAt ? {resetsAt:w.resetsAt} : {})}));
}

function shellQuote(text) { return "'" + String(text).replaceAll("'", "'\\''") + "'"; }
// Defense in depth behind the settings deny rules: mcporter must not reach a server you protect
// (it would bypass that server's per-tool hooks) or print its config (which can hold secrets).
export function mcporterDenial(command) {
  if (!/mcporter/i.test(command)) return null;
  for (const name of blockedServers) {
    if (new RegExp(escapeRe(name).replaceAll('-', '[-_]'), 'i').test(command))
      return `mcporter must not call the protected MCP server "${name}"; it would bypass that server's guards. Use its native mcp__ tools.`;
  }
  if (/\bmcporter(?:\s+--?[\w-]+(?:[ =][^\s-]\S*)?)*\s+config\b/i.test(command)) return 'mcporter config output can contain credentials; ask the user to run config commands themselves.';
  return null;
}
// Keeps a raised session effort (/effort) and raises a lower one to what the route needs.
function atLeast(current, wanted) { return EFFORTS.indexOf(current) >= EFFORTS.indexOf(wanted) ? current : wanted; }

let cfg, state, run, root;
let authSource, authEnabled, authGeneration;
let lock = Promise.resolve();
  async function init($) {
    if (state) return;
    run = await $.env.get('CLAUDE_LAB_RUN_DIR');
    root = await $.env.get('CLAUDE_LAB_ROOT');
    if (!run?.startsWith('/') || !root?.startsWith('/')) throw new Error('Launch with claude-lab');
    cfg = JSON.parse(await $.fs.read(run + '/runtime.json')); configure(cfg);
    state = JSON.parse(await $.fs.read(run + '/metrics.json'));
    if (!cfg.project || !state.agents) throw new Error('Invalid lab state');
    authSource = await $.env.get('CLAUDE_LAB_AUTH_SOURCE');
    authEnabled = await $.env.get('CLAUDE_LAB_AUTH_FALLBACK') === '1';
    authGeneration = await $.env.get('CLAUDE_LAB_AUTH_GENERATION');
  }
  async function change($, fn) {
    const previous = lock;
    let release;
    lock = new Promise(resolve => { release = resolve; });
    await previous;
    try {
      await init($);
      const value = await fn();
      await $.fs.write(run + '/metrics.json', JSON.stringify(state, null, 2));
      return value;
    } finally { release(); }
  }
  async function proof($) {
    try { return JSON.parse(await $.fs.read(run + '/verified-checks.json')); }
    catch { return null; }
  }
  async function recordAuthQuota($, windows) {
    await change($, () => {
      state.authSource = authSource || 'configured native login';
      state.authQuotaWindows = exhaustedWindows(windows);
    });
    if (!authEnabled || !['primary','secondary','token','token-last'].includes(authSource) || !authGeneration) return;
    const agents = await $.agent.list();
    const workersIdle = !agents.some(a => ['pending','running','waiting','idle'].includes(a.status));
    const idle = state.authLeadIdle === true && workersIdle;
    const ready = idle && state.authLastMainReason === 'error' && state.authQuotaWindows.length > 0;
    await $.fs.write(run + '/auth-control.json',JSON.stringify({schema:2,generation:authGeneration,
      source:authSource,phase:ready ? 'ready' : (idle ? 'idle' : 'pending'),
      reason:ready ? 'subscription_exhausted' : 'observation',leadIdle:state.authLeadIdle === true,
      workersIdle,hasMainTurn:state.authHasMainTurn === true,mainReason:state.authLastMainReason,turnId:state.authTurnId,
      sessionId:await $.session.id(),turnStartedAt:state.authTurnStartedAt || 0,
      windows:state.authQuotaWindows,checkedAt:Date.now()}));
  }
  async function refreshProject($) {
    const result = await $.process.run(['python3',root + '/bin/lab.py','fingerprint','--run',run],{timeoutMs:10000});
    if (result.exitCode !== 0) throw new Error('Cannot verify current source state');
    const scope = JSON.parse(result.stdout);
    const current = scope.sha256;
    await change($, () => {
      state.scopeRequired = Boolean(scope.scopeRequired);
      if (scope.project !== undefined) state.verificationProject = scope.project;
      if (state.workspaceFingerprint !== current) {
        state.workspaceFingerprint = current;
        state.revision += 1;
        state.codeEdited = true;
        state.review = null;
        state.stopNudged = false;
        state.evidenceComplete = false;
      }
    });
    return current;
  }
  function status() {
    const usage = usageSummary(state.models);
    const warnings = budgetWarnings(state);
    return `${cfg.mode} · ${state.route?.model || 'awaiting task'} · workers ${state.workers} · requests ${state.steps} · Opus ${usage.opusShare}% of ${usage.calls} calls · ${(usage.tokens / 1e6).toFixed(1)}M new tokens (+${(usage.cacheReads / 1e6).toFixed(1)}M cache reads) · revision ${state.revision}` +
      (warnings.length ? ' · OVER SOFT BUDGET: ' + warnings.join('; ') : '') +
      (cfg.homeWorkspace ? ` · code scope: ${state.verificationProject || 'choose with /lab-project'}` : '');
  }
  // One reasoner hint per task replaces the old automatic switch of the lead to Opus.
  function setHint(reason) { if (!state.reasonerHinted) state.reasonerHint = reason; }
  function takeHint() {
    const hint = state.reasonerHint;
    if (hint) { state.reasonerHint = null; state.reasonerHinted = true; }
    return hint;
  }
  function hintText(hint) {
    return `Escalation: ${hint}. Keep the lead model; spawn harness-lab:reasoner once with the failing evidence.`;
  }
  function stopped(e, reason) {
    return {turnId:e.turnId,index:e.index,answer:reason,toolUses:[],stopReason:'end_turn',usage:null};
  }

  async function runVerify($) {
    await refreshProject($);
    if (state.scopeRequired) return {result:'Select the specific code folder with /lab-project /absolute/path or the select_project tool before verification.'};
    const command = 'python3 ' + shellQuote(root + '/bin/lab.py') + ' verify --run ' + shellQuote(run);
    const checked = await $.tool.call({tool:'Bash',command,description:'Run the lab acceptance checks and record their exit codes'});
    const evidence = await proof($);
    const hint = evidence ? await change($, () => {
      state.verification = {passed:evidence.passed,revision:evidence.revision,taskSerial:evidence.taskSerial};
      state.verifyFailures = evidence.passed ? 0 : (state.verifyFailures || 0) + 1;
      if (!evidence.passed && state.verifyFailures >= 2) setHint('acceptance checks failed twice');
      return takeHint();
    }) : null;
    return {result:JSON.stringify({evidence,toolDenied:checked.deny || null,...(hint ? {next:hintText(hint)} : {})})};
  }

  async function selectProject($, path) {
    if (!path?.trim()) return {result:'Use /lab-project /absolute/path/to/project.'};
    const agents = await $.agent.list();
    if (agents.some(a => ['pending','running','waiting','idle'].includes(a.status)))
      return {result:'Finish or stop the active workers before changing the code verification folder.'};
    return change($, async () => {
      const result = await $.process.run(['python3',root + '/bin/lab.py','scope','--run',run,'--project',path.trim()],{timeoutMs:10000});
      if (result.exitCode !== 0) return {result:redact(result.stderr || 'Could not select the verification folder.')};
      const scope = JSON.parse(result.stdout);
      cfg = JSON.parse(await $.fs.read(run + '/runtime.json')); configure(cfg);
      state.workspaceFingerprint = scope.sha256;
      state.verificationProject = scope.project;
      state.scopeRequired = false;
      state.revision += 1;
      state.verification = null;
      state.review = null;
      state.checkpoint = false;
      state.stopNudged = false;
      state.evidenceComplete = false;
      await $.fs.write(run + '/acceptance.json',JSON.stringify({criteria:[],checks:[]}));
      return {result:'Code verification folder: ' + scope.project + '. Checks run there. Record a fresh checkpoint; use absolute paths or explicit cd commands for tools. Native session launch directory is retained.'};
    });
  }

export function register(on) {
  on('session.start', async ($, e, next) => {
    await change($, () => {});
    for (const [name, description, argumentHint] of [
      ['lab-status','Show routes, usage counters, and task evidence',''],
      ['lab-model','Choose the lead model for the next task (add "now" to switch immediately)','auto|sonnet|opus [now]'],
      ['lab-new','Archive the current task and start a fresh handoff',''],
      ['lab-project','Choose the work folder used for code verification','/absolute/path'],
      ['lab-verify','Run recorded acceptance checks through the normal Bash tool','']
    ]) await $.command.register({name,description,argumentHint});
    await $.tool.register({name:'checkpoint',isDeferred:false,description:'Record compact task context, plan, implementation, checks and unresolved work in the lab handoff files.',
      inputSchema:{type:'object',properties:{context:{type:'string',maxLength:4000},plan:{type:'string',maxLength:4000},
        implementation:{type:'string',maxLength:4000},unresolved:{type:'array',items:{type:'string'},maxItems:12},
        criteria:{type:'array',items:{type:'string'},maxItems:12},checks:{type:'array',maxItems:6,items:{type:'object',properties:{
          argv:{type:'array',items:{type:'string'},minItems:1,maxItems:30},timeoutSeconds:{type:'integer',minimum:1,maximum:60}},required:['argv']}}},required:['context','plan','implementation','unresolved','criteria','checks']}});
    await $.tool.register({name:'verify',isDeferred:false,description:'Run the checks recorded in the task acceptance file, record actual exit codes, and return bounded evidence.',inputSchema:{type:'object',properties:{}}});
    await $.tool.register({name:'select_project',isDeferred:false,description:'Select a specific code folder for source fingerprints and acceptance checks, especially when launched from the home directory. Clears prior check and review evidence; does not move the native session.',inputSchema:{type:'object',properties:{path:{type:'string'}},required:['path']}});
    await change($, () => {state.runtimeReady = true;});
    try {
      const usage = await $.session.usage();
      await change($, () => {state.planStart ||= usage.rateLimits;state.planLatest = usage.rateLimits;state.authLeadIdle = true;state.authLastMainReason = null;state.authTurnStartedAt=0;state.authTurnId=null;state.authHasMainTurn=false;});
      await recordAuthQuota($,usage.rateLimits);
    } catch { /* Usage bars are optional; never replace missing values with zero. */ }
    $.ui.log('Claude Lab active. ' + status() + '. Ordinary Claude settings are not rewritten.');
    return next(e);
  }).catch(() => undefined);

  on('session.measure', async ($, e, next) => {
    await change($, () => {});
    await recordAuthQuota($,e.rateLimits);
    return next(e);
  }).catch(async ($, e, next) => next(e));

  on('turn.start', async ($, e, next) => {
    if (!e.agentId) await change($, () => {
      state.authLeadIdle=false;state.authLastMainReason=null;state.authTurnStartedAt=Date.now();
      state.authTurnId=e.turnId;state.authHasMainTurn=true;
    });
    try {await recordAuthQuota($,[]);} catch { /* Never stop a turn for an observer write. */ }
    return next(e);
  });

  on('session.end',async ($,e,next) => {
    try {
      await change($, () => {
        state.authLeadIdle=false;state.authHasMainTurn=false;state.authLastMainReason=null;
        // /clear drops the cached conversation, so the next prompt may pick a new lead model.
        if (e.reason === 'clear') {state.route=state.route && {...state.route,pinned:false};state.policyInjected=false;}
      });
      await recordAuthQuota($,[]);
    } catch { /* Native session transitions must not depend on observation. */ }
    return next(e);
  });

  on('prompt.submit', async ($, e, next) => {
    try {
      const chosen = await change($, async () => {
        // Route on the user's words only; project paths are not task signals.
        const previous = state.route?.pinned ? state.route : null;
        const decision = route(e.text, cfg.modelOverride, Boolean(state.route?.financial));
        // The lead model is pinned for the task: switching it mid-session rebuilds the prompt cache.
        // Effort may follow the prompt, because 5.5 models keep the cache across effort changes.
        state.route = previous && previous.model !== decision.model
          ? {...decision, model:previous.model, effort:previous.effort, pinned:true}
          : {...decision, pinned:true};
        if (!state.hasBrief) {
          await $.fs.write(run + '/brief.md', '# Task brief\n\n' + redact(e.text).slice(0,4000));
          state.hasBrief = true;
        }
        const injectPolicy = state.route.financial && (isFinancial(e.text) || !state.policyInjected);
        if (injectPolicy) state.policyInjected = true;
        const hard = decision.hard && !state.hardHinted;
        if (hard) state.hardHinted = true;
        const warnings = budgetWarnings(state);
        const budgetKey = warnings.length ? [Math.floor(usageSummary(state.models).tokens / SOFT_BUDGET.tokens), state.workers, state.reviews || 0].join('/') : null;
        const overBudget = Boolean(budgetKey) && budgetKey !== state.budgetAlerted;
        if (overBudget) state.budgetAlerted = budgetKey;
        return {...state.route, hard, injectPolicy, hint:takeHint(), overBudget};
      });
      let context = `Claude Lab: ${chosen.model}, ${chosen.effort}; ${chosen.reason}. Task artifacts: ${run}. Use compact checkpoints and evidence, not another transcript. ${status()}.`;
      context += '\nSoft budget for this task (replaces any earlier "no budget" instruction): at most 4 workers, one independent review plus at most one re-review after fixes, and stop to ask the user once the lab status shows more than 2M tokens on this task. The lead model stays fixed for the task. Multi-step data or bulk output → harness-lab:code-first-data skill; return summaries, not dumps.';
      if (chosen.overBudget) context += '\nSOFT BUDGET EXCEEDED (see status). Before more work, tell the user the usage so far and ask whether to continue; if they already said continue, carry on.';
      if (chosen.hard) context += '\nThis looks like a hard question. Keep the lead model; spawn harness-lab:reasoner once with the specific question and the evidence.';
      if (chosen.hint) context += '\n' + hintText(chosen.hint);
      if (cfg.homeWorkspace && state.scopeRequired) context += '\nHome-directory session: browse normally. Before coding, select the specific work folder with mcp__harness-lab__select_project. No entire-home source scan is performed; unscoped research completion records a checkpoint only.';
      if (chosen.financial) context += '\nFinancial or broker task: before finishing, obtain one independent harness-lab:reviewer (Opus) review of the analysis or change.';
      if (chosen.injectPolicy) context += '\nSCOPED FINANCIAL POLICY:\n' + await $.fs.read(run + '/financial-policy.md');
      $.ui.log(`Route: ${chosen.model} (${chosen.reason}).`);
      return next({...e,context:[...(e.context || []),context]});
    } catch { return {drop:'Claude Lab state could not be loaded. Run claude-lab doctor; ordinary claude remains available.'}; }
  }).catch(() => ({drop:'Lab prompt routing failed. No prompt is sent; inspect the lab runtime.'}));

  on('agent.spawn', async ($, e, next) => {
    let model, warnings;
    try {
      const denial = await change($, () => {
        if (e.parentAgentId || e.fork) return 'Lab workers cannot delegate or fork. Return your findings to the lead.';
        // A financial review may run unscoped; it reviews the analysis rather than a source tree.
        const needsScope = /implementer/i.test(e.subagentType) || (/reviewer/i.test(e.subagentType) && !state.route?.financial);
        if (state.scopeRequired && needsScope) return 'Select the code folder with the select_project tool before starting implementation or review.';
        if (!e.resume) {
          state.workers += 1;
          if (REVIEW_ROLE.test(e.subagentType)) state.reviews = (state.reviews || 0) + 1;
        }
        model = spawnModel(e.subagentType, e.model);
        warnings = budgetWarnings(state);
        return null;
      });
      if (denial) return {deny:denial};
      if (warnings.length) $.ui.log('Claude Lab soft budget: ' + warnings.join('; ') + '. Consider asking the lead to stop and check with you.');
      const reviewHash = /reviewer/i.test(e.subagentType) ? await refreshProject($) : null;
      const contract = `\nLAB CONTRACT: own only your assigned scope. Code verification folder: ${state.verificationProject || cfg.project}. Read its relevant project instructions and the task artifacts at ${run}. Read core-instructions.md before editing or committing, and financial-policy.md for financial work. Return a compact report (about 300 words): findings, file/source paths, verification evidence and unresolved issues. Multi-step data or bulk output: process it with a throwaway script and return summaries with a path to the full output, not dumps. Do not spawn workers or modify Claude configuration.`;
      const financialPolicy = isFinancial(e.prompt) || (state.route?.financial && OPUS_ROLE.test(e.subagentType)) ? '\nSCOPED FINANCIAL POLICY:\n' + await $.fs.read(run + '/financial-policy.md') : '';
      const result = await next({...e,...(cfg.homeWorkspace && state.verificationProject ? {cwd:state.verificationProject} : {}),...(model ? {model} : {}),prompt:e.prompt + contract + financialPolicy});
      if (result.agentId) await change($, () => { state.agents[result.agentId] = {...state.agents[result.agentId],role:e.subagentType,model:result.model || model || null,effort:state.agents[result.agentId]?.effort || null,steps:state.agents[result.agentId]?.steps || 0,reviewHash}; });
      return result;
    } catch { return {deny:'Lab worker routing failed. Continue in the lead or inspect the lab state; no extra worker was started by this hook.'}; }
  }).catch(() => ({deny:'Lab worker hook failed; no new worker is permitted.'}));

  // Some worker implementations start their first request before spawn returns.
  on('classic.SubagentStart', async ($, e, next) => {
    await change($, () => {
      if (e.agent_id && !state.agents[e.agent_id]) {
        state.agents[e.agent_id] = {role:e.agent_type,model:null,effort:null,steps:0};
      }
    });
    return next(e);
  });

  on('turn.step', async function* ($, e, next) {
    let decision;
    try {
      decision = await change($, () => {
        const worker = e.agentId ? (state.agents[e.agentId] ||= {model:null,effort:null,steps:0}) : null;
        state.steps += 1;
        if (worker) worker.steps += 1; else state.mainSteps += 1;
        if (worker) {
          worker.model ||= e.model;
          worker.effort ||= e.effort ?? null;
          return {worker:true};
        }
        return state.route || route('');
      });
    } catch { decision = {deny:'Lab state unavailable; no model request sent by this hook.'}; }
    if (decision.deny) {
      yield {kind:'text',index:0,text:decision.deny};
      return stopped(e,decision.deny);
    }
    // Workers keep the model and effort resolved at spawn; only the lead follows the task route.
    const request = decision.worker ? e : {...e,model:decision.model,effort:atLeast(e.effort,decision.effort)};
    const result = yield* next(request);
    if (result.usage) await change($, () => {
      const served = result.usage.model || request.model;
      const bucket = state.models[served] ||= {requests:0,input_tokens:0,output_tokens:0,cache_read_input_tokens:0,cache_creation_input_tokens:0};
      bucket.requests += 1;
      for (const key of ['input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens']) bucket[key] += result.usage[key] || 0;
    });
    return result;
  }).catch(async function* ($, e, next) {
    if (next.called) return yield* next(e);
    const reason = 'Lab routing hook failed; no model request sent.';
    yield {kind:'text',index:0,text:reason};
    return stopped(e,reason);
  });


  on('tool.call', async ($, e, next) => {
    await change($, () => { if (!e.agentId) state.mainToolCalls = (state.mainToolCalls || 0) + 1; });
    if (e.tool === 'mcp__harness-lab__checkpoint') {
      await change($, async () => {
        for (const name of ['context','plan','implementation'])
          await $.fs.write(run + '/' + name + '.md', '# ' + name + '\n\n' + redact(e[name] || '').slice(0,4000));
        await $.fs.write(run + '/acceptance.json',JSON.stringify({criteria:e.criteria,checks:e.checks},null,2));
        state.unresolved = (e.unresolved || []).map(x => redact(x).slice(0,500));
        state.checkpoint = true;
      });
      return {result:'Compact task checkpoint recorded. Acceptance checks and independent review determine verified completion.'};
    }
    if (e.tool === 'mcp__harness-lab__verify') return runVerify($);
    if (e.tool === 'mcp__harness-lab__select_project') {
      if (e.agentId) return {deny:'Only the lead can change the task verification folder.'};
      return selectProject($,e.path);
    }
    if (cfg.homeWorkspace && ['Write','Edit','MultiEdit','NotebookEdit'].includes(e.tool)) {
      const path = e.file_path || e.notebook_path || '';
      if (!path.startsWith(run + '/') && (state.scopeRequired || !path.startsWith(state.verificationProject + '/')))
        return {deny:'Select the specific work folder containing this file with the select_project tool or /lab-project before editing it. Home-directory browsing remains available.'};
    }
    if (e.agentId && (e.tool === 'Agent' || e.tool === 'Workflow')) return {deny:'Nested delegation is disabled in this lab.'};
    if (e.tool === 'Workflow') return {deny:'Use the bounded lab specialists. Open-ended workflows are disabled in this variation.'};
    if (e.tool === 'Bash' && /(?:^|[;&|\s])claude(?:-rotate)?(?:\s|$)/.test(e.command || ''))
      return {deny:'Use the lab specialists to keep model routing and context handoffs consistent.'};
    if (['Bash','Monitor'].includes(e.tool) && mcporterDenial(e.command || '')) return {deny:mcporterDenial(e.command)};
    // Pass on the original event. This never changes a permission decision.
    const result = await next(e);
    if (!result.deny && !result.isError && ['Write','Edit','MultiEdit','NotebookEdit'].includes(e.tool)) {
      const path = e.file_path || e.notebook_path || '';
      if (path && !path.startsWith(run + '/')) await change($, () => {
        state.revision += 1;
        if (/\.(?:py|[cm]?[jt]sx?|json|toml|yaml|yml|rs|go|c|cpp|h|ipynb)$/.test(path)) state.codeEdited = true;
        state.review = null;
        state.stopNudged = false;
        state.evidenceComplete = false;
      });
    }
    if (e.tool === 'Bash' && typeof result.result?.stdout === 'string' && result.result.stdout.length > 20000) {
      const id = String(e.tool_use_id || ('step-' + state.steps)).replace(/[^A-Za-z0-9_-]/g,'_');
      const path = run + '/tool-output-' + id + '.log';
      const full = redact(result.result.stdout);
      await $.fs.write(path,full);
      return {...result,result:{...result.result,stdout:full.slice(0,4000) + '\n[Output shortened; full local output: ' + path + ']\n' + full.slice(-4000)}};
    }
    return result;
  }).catch(async ($, e, next) => next.called ? next(e) : {deny:'Lab tool hook failed; this tool was not run.'});

  on('turn.complete', async ($, e, next) => {
    const reviewer = e.agentId && state?.agents[e.agentId];
    const reviewHash = reviewer && /reviewer|staff-reviewer/i.test(reviewer.role || '') ? await refreshProject($) : null;
    await change($, () => {
      const worker = e.agentId && state.agents[e.agentId];
      if (worker && /reviewer|staff-reviewer/i.test(worker.role || '')) {
        try {
          const report = JSON.parse(String(e.answer).replace(/^\s*```(?:json)?\s*/,'').replace(/\s*```\s*$/,''));
          state.review = {approved:report.approved === true && Array.isArray(report.findings) && report.findings.length === 0 && worker.reviewHash === reviewHash && !e.isAborted && e.reason === 'answer',
            findings:(report.findings || []).slice(0,12).map(x => redact(JSON.stringify(x)).slice(0,700)),revision:state.revision};
          state.review.workspaceFingerprint = reviewHash;
          if (!state.review.approved) setHint('the independent review did not approve the latest revision');
        } catch {state.review = {approved:false,findings:['Reviewer did not return the required JSON report.'],revision:state.revision};}
      }
    });
    const result = await next(e);
    if (!e.agentId) {
      await change($, () => {state.authLeadIdle=true;state.authLastMainReason=e.reason;state.authHasMainTurn=true;});
    }
    try {await recordAuthQuota($,(await $.session.usage()).rateLimits);} catch { /* Missing quota data prevents switching. */ }
    return result;
  });

  on('classic.Stop', async ($, e, next) => {
    await change($, () => {});
    if (e.agent_id || e.stop_hook_active) return next(e);
    await refreshProject($);
    const checks = await proof($);
    const complete = evidenceComplete(state,checks);
    // A pure chat turn (no tools, workers, edits or broker work) has nothing to hand off, so it
    // skips the reminder instead of paying a whole extra model turn for an empty checkpoint.
    const chatOnly = !state.mainToolCalls && !state.workers && !state.codeEdited && !state.route?.financial;
    if (!complete && !state.stopNudged && !chatOnly) {
      const hint = await change($, () => {state.stopNudged = true; return takeHint();});
      return {block:'Before finishing, record the compact checkpoint. For code edits, run meaningful acceptance checks through the lab verify tool and obtain independent reviewer approval for the latest revision. Financial tasks need one approved harness-lab:reviewer review. ' +
        (hint ? hintText(hint) + ' ' : '') + 'If blocked, record the missing evidence and clearly report incomplete work. This reminder fires once.'};
    }
    await change($, () => {state.evidenceComplete = complete;});
    try {
      const usage = await $.session.usage();
      await change($, () => {state.planLatest = usage.rateLimits;});
    } catch { /* Local model accounting remains available when plan bars fail. */ }
    $.ui.log(status() + ' · evidence ' + (complete ? (state.scopeRequired ? 'checkpoint recorded; code verification unscoped' : 'complete') : 'incomplete'));
    return next(e);
  }).catch(() => ({block:'Lab evidence could not be checked. Report incomplete verification; inspect the lab runtime before claiming completion.'}));

  on('command.run', {command:['lab-status','lab-model','lab-new','lab-verify','lab-project']}, async ($, e) => {
    await change($, () => {});
    if (e.command === 'lab-project') return {text:(await selectProject($,e.args)).result};
    if (e.command === 'lab-verify') return {text:JSON.stringify((await runVerify($)).result)};
    if (e.command === 'lab-model') {
      const [choice, when = ''] = e.args.trim().split(/\s+/);
      if (!['auto','sonnet','opus'].includes(choice) || !['','now'].includes(when)) return {text:'Use /lab-model auto, sonnet, or opus, optionally followed by "now".'};
      cfg.modelOverride = choice;
      await $.fs.write(run + '/runtime.json',JSON.stringify(cfg,null,2));
      const {pinned, switched} = await change($, () => {
        if (when === 'now' && state.route) {
          state.route = {...route('',choice,state.route.financial),pinned:true};
          return {switched:true};
        }
        return {pinned:state.route?.pinned ? state.route.model : null};
      });
      return {text:'Lab override: ' + choice + '. ' + (pinned
        ? `This task keeps ${pinned}, because switching the lead mid-session rebuilds the whole prompt cache. The override applies from the next task (/lab-new, /clear or a new session); use "/lab-model ${choice} now" to switch immediately.`
        : 'It applies from the next request' + (switched ? ' and rebuilds the prompt cache once.' : '.')) + ' Original model settings are unchanged.'};
    }
    if (e.command === 'lab-new') {
      const agents = await $.agent.list();
      if (agents.some(a => ['pending','running','waiting','idle'].includes(a.status)))
        return {text:'Finish or stop the running workers before starting a new task handoff.'};
      await change($, async () => {
        await $.fs.write(run + '/archive-' + (state.taskSerial || 0) + '.json',JSON.stringify(state,null,2));
        const serial = (state.taskSerial || 0) + 1;
        state = {schema:1,taskSerial:serial,workers:0,steps:0,mainSteps:0,agents:{},models:{},revision:0,
          codeEdited:false,verification:null,review:null,route:null,stopNudged:false,checkpoint:false,runtimeReady:true,workspaceFingerprint:state.workspaceFingerprint,
          scopeRequired:state.scopeRequired,verificationProject:state.verificationProject};
        await $.fs.write(run + '/acceptance.json',JSON.stringify({criteria:[],checks:[]}));
      });
      return {text:'New task handoff ready. Use /clear before an unrelated task, then submit its request. Previous metrics are archived; the soft budget (4 workers, one review plus one re-review, ask at 2M tokens) starts again.'};
    }
    return {text:JSON.stringify({status:status(),run,metrics:state},null,2)};
  });

  on('config.set', async () => ({deny:'This lab keeps saved Claude settings unchanged. Use /lab-model for routing, or launch a new --mode deep session. Configure ordinary Claude from its usual command.'}));
}
