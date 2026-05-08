# Memory Capsule Workflow

A reference example showing how an external Memory Capsule guides Firecrawl tool
selection and evidence writeback in an agent workflow.

This example is part of the Phase 1 documentation contribution described in
[`docs/memory-capsule-pattern.md`](../../docs/memory-capsule-pattern.md).

---

## What This Example Shows

- How to represent a task-scoped Memory Capsule as a plain Python object
- How an orchestrator reads capsule hints to decide which Firecrawl tool to use
- How to execute a `search → scrape` or `map → scrape` workflow based on capsule state
- How to write durable evidence back to the capsule after retrieval

This example does **not** introduce a new Firecrawl feature. It demonstrates an
orchestration pattern that works with the current Firecrawl API as-is.

---

## Prerequisites

- Python 3.9+
- A [Firecrawl API key](https://firecrawl.dev)

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill in your FIRECRAWL_API_KEY
```

---

## Usage

```bash
python memory_capsule_workflow.py
```

The script runs a research workflow for a configurable objective, using capsule
hints to choose between `search` and `scrape`, then prints the evidence that
would be written back to the external memory store.

---

## Extending This Example

- Replace the in-memory capsule dict with a persistent store (Redis, SQLite, a
  vector DB) to carry evidence across runs.
- Add TTL-based expiry to `evidence_log` entries so stale facts are not reused.
- Gate `interact` calls on a capsule hint rather than running them unconditionally.
- Integrate with an LLM to evaluate whether scraped content confirms or refutes
  the active hypothesis before writing back.

---

## Phase 1 Limitations

This example intentionally omits:

- A full memory database implementation
- A reusable SDK layer
- LLM-based hypothesis evaluation (kept out to avoid mandatory API keys)
- Integration with the Firecrawl `interact` or `crawl` endpoints (left for a
  follow-up example once the pattern is validated)
