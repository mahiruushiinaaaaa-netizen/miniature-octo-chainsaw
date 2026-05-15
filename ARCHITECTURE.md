]# Mini AI v39 — Architecture & Improvement Diagram

## Current Flow (What Happens Now)

```
USER INPUT
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  CommandRouter (commands.py)                                  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 1. Intent Classification (CONVO/QUERY/TASK/EXPLORE/COMPLEX)│
│  │ 2. Model Routing (fast model vs primary)                 │ │
│  │ 3. Direct shortcuts (cd, play, search)                   │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent Loop (agent.py) — Max N steps                         │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                │
│  │ Prompt   │──▶│ Generate │──▶│ Parse    │                 │
│  │ Assembly │   │ (LLM)   │   │ Action   │                 │
│  └──────────┘   └──────────┘   └──────────┘                │
│       │              │               │                       │
│       │         ~3-30 sec           │                       │
│       │         (BOTTLENECK)         ▼                       │
│       │                        ┌──────────┐                 │
│       │                        │ Execute  │                 │
│       │                        │ Tool     │                 │
│       │                        └────┬─────┘                 │
│       │                             │                       │
│       ◀─────── observation ─────────┘                       │
│                                                              │
│  Loop until: answer tool | max steps | error                 │
└──────────────────────────────────────────────────────────────┘
```

## Bottlenecks Identified

```
┌────────────────────────────────────────────────────────────────┐
│ SPEED BOTTLENECKS (where time is wasted)                        │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 1. GENERATION TIME: 3-30s per step (CPU inference)              │
│    └─ Can't reduce model speed, but CAN reduce steps needed    │
│                                                                 │
│ 2. WASTED STEPS: Model often does 3-5 steps for 1-step tasks   │
│    └─ Reads file → thinks → reads again → finally acts         │
│    └─ FIX: Better one-shot examples + task-specific prompts    │
│                                                                 │
│ 3. TOOL SELECTION CONFUSION: Model picks wrong tool, retries   │
│    └─ 104 tools in grammar but model only sees 8 via router    │
│    └─ FIX: Intent-aware tool hints in the prompt               │
│                                                                 │
│ 4. EMPTY RESPONSES: Grammar mismatch → empty → retry           │
│    └─ Already fixed with retry cascade + grammar disable       │
│                                                                 │
│ 5. CONTEXT OVERFLOW: Observations fill context → truncation    │
│    └─ Already fixed with ObservationCompressor                 │
│                                                                 │
│ 6. UNNECESSARY AGENT CALLS: Simple tasks go through full loop  │
│    └─ "what time is it" → 3s generation for datetime_util      │
│    └─ FIX: Expand direct-action fast paths                     │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

## Proposed Improvements (Speed-Preserving)

```
┌────────────────────────────────────────────────────────────────────┐
│                    IMPROVED ARCHITECTURE                             │
└────────────────────────────────────────────────────────────────────┘

USER INPUT
    │
    ▼
╔══════════════════════════════════════════════════════════════════════╗
║  LAYER 0: INSTANT DISPATCH (< 50ms, no LLM needed)                  ║
║                                                                      ║
║  ┌─────────────────────────────────────────────────────────────┐    ║
║  │ Pattern Matcher (regex + keyword)                            │    ║
║  │                                                              │    ║
║  │ "what time is it"     → datetime_util("now")     INSTANT    │    ║
║  │ "convert 5km to mi"   → convert("length","5","km","mi")     │    ║
║  │ "ping google.com"     → net_op("ping","google.com")         │    ║
║  │ "git status"          → git_op("status")                    │    ║
║  │ "hash this text"      → crypto_op("hash","this text")       │    ║
║  │ "count files in ."    → file_op_ext("disk_usage",".")       │    ║
║  │ "npm install express" → package_op("npm","install","express")│    ║
║  │ "docker ps"           → docker_op("ps")                     │    ║
║  │ "run pytest"          → test_op("run")                      │    ║
║  │ "project health"      → project_health(".")                 │    ║
║  │                                                              │    ║
║  │ Coverage: ~40% of user requests → 0 LLM calls needed        │    ║
║  └─────────────────────────────────────────────────────────────┘    ║
║         │ (not matched)                                              ║
╚═════════╪════════════════════════════════════════════════════════════╝
          ▼
╔══════════════════════════════════════════════════════════════════════╗
║  LAYER 1: SINGLE-SHOT DISPATCH (1 LLM call, ~3-5s)                  ║
║                                                                      ║
║  ┌─────────────────────────────────────────────────────────────┐    ║
║  │ For tasks that need 1 tool call:                             │    ║
║  │                                                              │    ║
║  │ Micro-prompt (80 tokens) + GBNF grammar                     │    ║
║  │     → Model outputs: {"action":"X", "param":"Y"}            │    ║
║  │     → Execute immediately                                   │    ║
║  │     → Return result to user                                 │    ║
║  │                                                              │    ║
║  │ NO LOOP. One generation, one execution, done.                │    ║
║  │                                                              │    ║
║  │ Triggers when: intent == TASK or QUERY                       │    ║
║  │ Coverage: ~30% of requests                                   │    ║
║  └─────────────────────────────────────────────────────────────┘    ║
║         │ (needs multiple steps)                                     ║
╚═════════╪════════════════════════════════════════════════════════════╝
          ▼
╔══════════════════════════════════════════════════════════════════════╗
║  LAYER 2: MULTI-STEP AGENT (current loop, ~10-60s)                   ║
║                                                                      ║
║  ┌─────────────────────────────────────────────────────────────┐    ║
║  │ Full agent loop for complex tasks:                           │    ║
║  │                                                              │    ║
║  │ • Code generation (write multiple files)                     │    ║
║  │ • Debugging (read → analyze → fix → verify)                 │    ║
║  │ • Research (search → read → synthesize)                      │    ║
║  │ • Project setup (scaffold → install → configure)             │    ║
║  │                                                              │    ║
║  │ Improvements here:                                           │    ║
║  │ ┌─────────────────────────────────────────────────────┐     │    ║
║  │ │ A. FAST COMPLETION DETECTION                         │     │    ║
║  │ │    After run_cmd succeeds for create-project type    │     │    ║
║  │ │    commands → auto-finish (skip "done" generation)   │     │    ║
║  │ │    SAVES: 1 full generation (~5-15s)                 │     │    ║
║  │ └─────────────────────────────────────────────────────┘     │    ║
║  │ ┌─────────────────────────────────────────────────────┐     │    ║
║  │ │ B. BATCH ACTIONS                                     │     │    ║
║  │ │    Model outputs {"actions": [...]} in one shot      │     │    ║
║  │ │    Execute all in parallel                           │     │    ║
║  │ │    SAVES: N-1 generations for N independent actions  │     │    ║
║  │ └─────────────────────────────────────────────────────┘     │    ║
║  │ ┌─────────────────────────────────────────────────────┐     │    ║
║  │ │ C. STREAMING EARLY-EXIT                              │     │    ║
║  │ │    Parse JSON action from stream before generation   │     │    ║
║  │ │    completes → abort remaining tokens                │     │    ║
║  │ │    SAVES: 30-50% of generation time per step         │     │    ║
║  │ └─────────────────────────────────────────────────────┘     │    ║
║  │                                                              │    ║
║  │ Coverage: ~30% of requests (complex multi-step tasks)        │    ║
║  └─────────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════════╝
```

## Key Improvement: Expand Layer 0 (Instant Dispatch)

```
┌────────────────────────────────────────────────────────────────────┐
│ INSTANT DISPATCH PATTERNS (no LLM, < 50ms)                          │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ PATTERN                          TOOL CALL                          │
│ ─────────────────────────────────────────────────────────────────  │
│ "git {status|log|branch|...}"  → git_op(operation, args)           │
│ "docker {ps|images|stop|...}"  → docker_op(operation, target)      │
│ "npm/pip/cargo {install|...}"  → package_op(mgr, op, pkg)          │
│ "ping/dns/port {target}"       → net_op(operation, target)         │
│ "convert {N} {unit} to {unit}" → convert(cat, val, from, to)       │
│ "hash/uuid/password"           → crypto_op(operation)              │
│ "time/date/now"                → datetime_util("now")              │
│ "count/size/tree {path}"       → file_op_ext(op, path)            │
│ "test/pytest/jest"             → test_op("run")                    │
│ "lint/format {path}"           → code_analyze(op, path)           │
│ "project info/health"          → project_info/health(path)        │
│ "{N} + {N}" or math expr       → calculate(expr)                  │
│ "search {query}"               → web_search(query)                │
│ "open {url}"                   → open_browser(url)                │
│                                                                     │
│ IMPLEMENTATION: Add to _is_direct_action() + _execute_direct()     │
│ in commands.py. Pure regex matching, zero LLM overhead.            │
│                                                                     │
│ IMPACT: 40% of requests complete in <50ms instead of 3-30s        │
└────────────────────────────────────────────────────────────────────┘
```

## Speed Impact Estimate

```
┌────────────────────────────────────────────────────────────────────┐
│ BEFORE vs AFTER (average response time)                             │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ Task Type          │ Before    │ After     │ Speedup               │
│ ───────────────────┼───────────┼───────────┼─────────────────────  │
│ "git status"       │ 5-10s     │ <100ms    │ 50-100x              │
│ "convert 5km mi"   │ 5-10s     │ <50ms     │ 100-200x             │
│ "npm install X"    │ 5-10s     │ <100ms    │ 50-100x              │
│ "what time"        │ 3-5s      │ <50ms     │ 60-100x              │
│ "ping google"      │ 5-10s     │ 4-5s*     │ 1x (network bound)   │
│ "create flask app" │ 15-30s    │ 5-10s     │ 2-3x                 │
│ "fix this bug"     │ 30-60s    │ 20-40s    │ 1.5x                 │
│ "write a module"   │ 30-90s    │ 25-70s    │ 1.2-1.3x             │
│                                                                     │
│ * ping itself takes 4s, but no LLM call needed                     │
│                                                                     │
│ OVERALL: ~40% of requests go from seconds → milliseconds           │
│          ~30% save 1-2 generation cycles (5-15s each)              │
│          ~30% (complex) get modest 20-30% improvement              │
└────────────────────────────────────────────────────────────────────┘
```

## Implementation Priority

```
┌────────────────────────────────────────────────────────────────────┐
│ PRIORITY ORDER (biggest impact, least effort)                       │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ 1. ★★★ EXPAND INSTANT DISPATCH PATTERNS                            │
│    File: commands.py → _is_direct_action() + _execute_direct()     │
│    Effort: ~200 lines of regex patterns                            │
│    Impact: 40% of requests → instant                               │
│                                                                     │
│ 2. ★★★ SINGLE-SHOT MODE FOR TASK/QUERY                             │
│    File: commands.py → run_agent() early exit                      │
│    When intent is TASK and goal maps to 1 tool → skip loop         │
│    Effort: ~50 lines                                               │
│    Impact: 30% of requests → 1 LLM call instead of 2-5            │
│                                                                     │
│ 3. ★★☆ STREAMING EARLY-EXIT                                        │
│    File: agent.py + backend.py                                     │
│    Already partially implemented (StreamingActionParser)            │
│    Need: abort HTTP connection when action parsed                   │
│    Impact: 30-50% faster per generation step                       │
│                                                                     │
│ 4. ★★☆ FAST COMPLETION DETECTION                                   │
│    File: agent.py (already partially done for create-project)      │
│    Expand to: any successful run_cmd in TASK intent                │
│    Impact: saves 1 generation (5-15s) per task                     │
│                                                                     │
│ 5. ★☆☆ BATCH ACTIONS                                               │
│    Already implemented (MULTI_ACTION_GRAMMAR + MultiActionExecutor)│
│    Need: better one-shot examples showing batch format             │
│    Impact: saves N-1 generations for multi-file writes             │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

## Data Flow Diagram (Complete)

```
                         USER INPUT
                             │
                             ▼
                    ┌────────────────┐
                    │  Parse Input   │
                    │  (commands.py) │
                    └───────┬────────┘
                            │
              ┌─────────────┼─────────────────┐
              ▼             ▼                  ▼
     ┌──────────────┐ ┌──────────┐  ┌──────────────────┐
     │ Slash Command │ │ Direct   │  │ Agent-Bound      │
     │ (/cd, /git)   │ │ Shortcut │  │ (needs reasoning)│
     └──────┬───────┘ └────┬─────┘  └────────┬─────────┘
            │               │                  │
            ▼               ▼                  ▼
     ┌──────────┐   ┌────────────┐   ┌──────────────────┐
     │ Execute  │   │ Pattern    │   │ Intent Classify  │
     │ Directly │   │ Match →    │   │ (CONVO/QUERY/    │
     │          │   │ Tool Call  │   │  TASK/EXPLORE/   │
     └──────────┘   └─────┬──────┘   │  COMPLEX)        │
                           │          └────────┬─────────┘
                           ▼                   │
                    ┌────────────┐    ┌────────┴────────┐
                    │ Execute    │    │                  │
                    │ Tool       │    ▼                  ▼
                    │ (instant)  │  CONVO/QUERY      TASK/EXPLORE/COMPLEX
                    └─────┬──────┘    │                  │
                          │           ▼                  ▼
                          │    ┌────────────┐   ┌──────────────────┐
                          │    │ Fast Model │   │ Agent Loop       │
                          │    │ (1 call)   │   │ (multi-step)     │
                          │    └─────┬──────┘   └────────┬─────────┘
                          │          │                    │
                          ▼          ▼                    ▼
                    ┌─────────────────────────────────────────┐
                    │              OUTPUT TO USER              │
                    └─────────────────────────────────────────┘
```
