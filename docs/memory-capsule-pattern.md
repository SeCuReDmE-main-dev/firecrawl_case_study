# External Memory Capsule Pattern for Firecrawl Workflows

**Status:** Design note  
**Scope:** Agent workflow guidance — documentation only  
**Breaking changes:** None  
**New dependencies:** None  

---

## What This Document Is

This document describes a workflow pattern for agent builders who use Firecrawl as their web acquisition substrate.

It does **not** propose changes to Firecrawl's API, runtime, or internals.  
It does **not** add a built-in memory subsystem to Firecrawl.  
It does **not** change any existing endpoint contracts.

It describes how an external orchestration layer can compile a small, task-scoped context object — a *Memory Capsule* — and use it to guide Firecrawl tool calls and post-call evidence writeback.

---

## The Problem

A Firecrawl-based agent can be highly capable while still being too stateless between steps.

Agent builders often need a degree of continuity across tasks:

- which site path worked in a prior run
- which page required an extra interaction step
- which sources are trusted first for a given domain
- which extraction path failed on a similar page
- which working hypothesis is active for the current task
- which facts were already observed and when they were captured

Without a disciplined structure for carrying this forward, agents tend to:

- repeat discovery work that already succeeded
- lose successful navigation patterns between runs
- mix stale facts with fresh retrieval
- use oversized prompts as a substitute for structured memory

---

## The Core Rule

```
memory outside, hints inside
```

Memory lives in an external store controlled by the orchestration layer.  
Before each Firecrawl workflow, the orchestrator compiles a very small, task-scoped payload — the *Memory Capsule* — containing only what is relevant to the current task.  
After the workflow completes, only durable evidence and verified learnings are written back to the external store.  
Firecrawl itself never holds, interprets, or persists agent memory.

---

## What a Memory Capsule Is

A Memory Capsule is not a full memory system.

It is a small, portable, task-scoped payload compiled from a larger external memory layer.  
Its lifetime is one task execution.

**Minimal schema:**

```json
{
  "capsule_id": "mc_task_docs_pricing_001",
  "scope": {
    "agent_id": "research-bot",
    "task_id": "compare-pricing",
    "expires_at": "2026-05-08T22:00:00+00:00"
  },
  "policies": {
    "freshness_required": true,
    "source_priority": [
      "official product pages",
      "official docs"
    ]
  },
  "working_set": {
    "objective": "compare current pricing plans across vendors",
    "active_hypothesis": "pricing is on one official pricing page per vendor"
  },
  "procedural_hints": [
    {
      "hint": "use map before crawl when site structure is unknown",
      "confidence": 0.84
    },
    {
      "hint": "pricing page is usually under /pricing or /plans",
      "confidence": 0.91
    }
  ],
  "evidence_log": [
    {
      "url": "https://example.com/pricing",
      "fact": "pricing page confirmed reachable",
      "captured_at": "2026-05-08T18:00:00+00:00",
      "freshness_ttl_sec": 86400
    }
  ]
}
```

Fields are intentionally minimal. Add only what guides the next tool call or reduces redundant work.

---

## Recommended Workflow Model

```
external memory store
        |
        | compile capsule (task-scoped)
        v
  Memory Capsule
        |
        | read hints + evidence
        v
  select Firecrawl tools
        |
        +-- search      (web discovery when starting cold)
        +-- map         (site topology when structure is unknown)
        +-- scrape      (single-page acquisition)
        +-- interact    (follow-up actions when page state matters)
        +-- crawl       (async site-wide acquisition)
        |
        | evaluate results
        v
  write back evidence + learnings
        |
        v
  external memory store (updated)
```

### Tool selection heuristics

| Situation | Recommended Firecrawl tool |
|-----------|---------------------------|
| Starting cold with no known URL | `search` |
| Site structure is unknown | `map` before `crawl` or `scrape` |
| Known URL, page content needed | `scrape` |
| Page requires login, click, or form action | `interact` after `scrape` |
| Broad site coverage needed | `crawl` |

These are not enforced by Firecrawl. They are orchestration-layer decisions informed by capsule hints.

---

## Evidence Writeback

After each workflow, the orchestrator should evaluate what is worth writing back.

Write back only:

- URLs that returned useful content, with a freshness TTL
- patterns that reduced tool calls (e.g. "pricing is always at /pricing")
- errors worth avoiding (e.g. "login wall at /account, skip")
- updated hypothesis if the working set changed

Do **not** write back:

- raw page content (too large, belongs in a retrieval store)
- speculative facts without grounding
- stale evidence beyond its TTL

---

## Risks

### Stale memory

Evidence accumulated across tasks may become outdated.  
Always attach `freshness_ttl_sec` to evidence entries.  
The orchestrator is responsible for expiring and refreshing stale entries.

### Memory poisoning

A bad retrieval result written back as evidence will bias future tasks.  
Guard writebacks with a verification step before persisting.  
Trust freshly scraped content over recalled capsule facts when they conflict.

### Over-personalized tool calls

A capsule that grows too large or too opinionated can narrow the agent's search space incorrectly.  
Keep capsules small. Prefer hints with explicit confidence scores. Discard low-confidence hints after a fixed number of runs.

---

## What This Pattern Is Not

- **Not a built-in agent memory in Firecrawl.** Firecrawl does not store, read, or interpret Memory Capsules.  
- **Not a general-purpose vector database.** The capsule is a compiled, task-scoped payload, not a queryable store.  
- **Not an agent framework.** This pattern is orchestration-layer guidance, not a product feature.  
- **Not a persona or identity system.** The capsule holds task-relevant hints, not agent personalities.  

---

## Phase 2 Extension: correlationId Passthrough

Phase 2 adds one small optional field — `correlationId` — to the `/v1/scrape`, `/v1/map`, and `/v1/search` request schemas.

### What it does

An orchestrator may attach a short string (max 255 characters) to a request:

```json
{
  "url": "https://example.com/pricing",
  "correlationId": "mc_task_pricing_001"
}
```

Firecrawl echoes it unchanged in the success response:

```json
{
  "success": true,
  "correlationId": "mc_task_pricing_001",
  "data": { ... }
}
```

### What it does not do

- Firecrawl does not parse, interpret, or act on `correlationId`.  
- It is not stored server-side beyond the response.  
- It is not propagated between jobs (e.g. a crawl job does not forward it to child scrapes).  
- It does not change billing, routing, or execution behavior.  

### Why it helps external orchestrators

Without `correlationId`, an orchestrator that fires multiple concurrent Firecrawl calls must match responses back to its internal task state by URL alone — which breaks when the same URL is requested in multiple tasks.

With `correlationId`, the orchestrator can tag each call with its internal task or capsule identifier. The echo in the response closes the loop without requiring the orchestrator to maintain a side-table of pending request IDs.

Example use in a Memory Capsule workflow:

```python
result = firecrawl.v1.scrape_url(
    "https://example.com/pricing",
    formats=["markdown"],
    correlationId=capsule["capsule_id"],
)
# result.correlationId == capsule["capsule_id"]
# safe to write evidence back to the correct capsule
write_evidence(capsule, result.metadata["sourceURL"], ...)
```

---

## Phase 1 Scope and Limitations

This document and the companion example under `examples/memory-capsule-workflow/` were Phase 1.

Phase 1 intentionally excluded:

- any change to Firecrawl's API endpoints or worker logic
- a built-in memory SDK or library
- replay or continuity hooks between `scrape` and `interact` sessions
- a structured memory store implementation

Phase 2 added `correlationId` passthrough only. Everything else remains out of scope.

---

## Further Reading

- [Firecrawl API documentation](https://docs.firecrawl.dev)
- [Companion example: `examples/memory-capsule-workflow/`](../examples/memory-capsule-workflow/)
- GitHub issue: [#3500 — External Memory Capsule pattern for agent workflows](https://github.com/firecrawl/firecrawl/issues/3500)
