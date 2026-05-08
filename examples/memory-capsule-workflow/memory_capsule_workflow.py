"""
Memory Capsule Workflow — reference example for Firecrawl agent builders.

Demonstrates:
  - A task-scoped Memory Capsule as a plain Python dict
  - Tool selection (search vs scrape) driven by capsule state
  - Evidence writeback after retrieval

Memory stays external. Firecrawl is the web acquisition substrate.
See docs/memory-capsule-pattern.md for the full design rationale.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # add FIRECRAWL_API_KEY
    python memory_capsule_workflow.py
"""

import json
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from firecrawl import FirecrawlApp

load_dotenv()

# ---------------------------------------------------------------------------
# Memory Capsule helpers
# ---------------------------------------------------------------------------

def build_capsule(task_id: str, objective: str) -> dict:
    """
    Build a fresh task-scoped Memory Capsule.

    In a real system this would be compiled by the orchestration layer from a
    larger external memory store.  Here we construct a minimal example capsule
    to illustrate the shape.
    """
    return {
        "capsule_id": f"mc_{task_id}",
        "scope": {
            "agent_id": "research-bot",
            "task_id": task_id,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=2)
            ).isoformat(),
        },
        "policies": {
            "freshness_required": True,
            "source_priority": ["official product pages", "official docs"],
        },
        "working_set": {
            "objective": objective,
            "active_hypothesis": None,
        },
        "procedural_hints": [
            {
                "hint": "use map before scrape when the relevant page URL is unknown",
                "confidence": 0.85,
            },
            {
                "hint": "pricing or docs content is usually one level deep from the root",
                "confidence": 0.80,
            },
        ],
        "evidence_log": [],
    }


def get_hint(capsule: dict, keyword: str) -> str | None:
    """Return the first procedural hint containing keyword, or None."""
    for entry in capsule.get("procedural_hints", []):
        if keyword.lower() in entry["hint"].lower():
            return entry["hint"]
    return None


def has_fresh_evidence(capsule: dict, url: str) -> bool:
    """Return True if url already has a non-expired evidence entry."""
    now = datetime.now(timezone.utc)
    for entry in capsule.get("evidence_log", []):
        if entry["url"] != url:
            continue
        captured = datetime.fromisoformat(entry["captured_at"])
        ttl = entry.get("freshness_ttl_sec", 0)
        if (now - captured).total_seconds() < ttl:
            return True
    return False


def write_evidence(capsule: dict, url: str, fact: str, ttl_sec: int = 86400) -> None:
    """Append a new evidence entry to the capsule's evidence log."""
    capsule["evidence_log"].append(
        {
            "url": url,
            "fact": fact,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "freshness_ttl_sec": ttl_sec,
        }
    )


def extract_search_urls(search_result) -> list[str]:
    """Extract candidate URLs from a SearchData result."""
    urls: list[str] = []
    for item in getattr(search_result, "web", []) or []:
        url = getattr(item, "url", None)
        if url:
            urls.append(url)
    return urls


def select_map_target(map_result, objective: str) -> str | None:
    """Choose the best mapped URL for the objective keywords."""
    keywords = objective.lower().split()
    for link in getattr(map_result, "links", []) or []:
        link_url = getattr(link, "url", None)
        if link_url and any(keyword in link_url.lower() for keyword in keywords):
            return link_url
    return None


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def run_workflow(objective: str, target_domain: str) -> dict:
    """
    Execute a memory-aware Firecrawl workflow.

    Decision logic:
      1. If the capsule already has a fresh evidence entry for the target URL,
         skip re-scraping (continuity reuse).
      2. If no known URL exists for the objective, use `search` to discover it.
      3. If the site structure hint is active, use `map` to locate the right
         page before scraping.
      4. Scrape the resolved URL and write evidence back.

    Returns the updated capsule so the caller can persist it.
    """
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        raise EnvironmentError("FIRECRAWL_API_KEY is not set in the environment.")

    fc = FirecrawlApp(api_key=api_key)

    task_id = f"{target_domain.replace('.', '_')}_research"
    capsule = build_capsule(task_id, objective)

    print(f"\n[capsule] task_id      : {capsule['scope']['task_id']}")
    print(f"[capsule] objective    : {capsule['working_set']['objective']}")
    print(f"[capsule] expires_at   : {capsule['scope']['expires_at']}\n")

    # ------------------------------------------------------------------
    # Step 1 — check for reusable evidence
    # ------------------------------------------------------------------
    root_url = f"https://{target_domain}"
    if has_fresh_evidence(capsule, root_url):
        print(f"[step 1] fresh evidence found for {root_url} — skipping re-scrape")
        return capsule

    # ------------------------------------------------------------------
    # Step 2 — discover relevant URL via search
    # ------------------------------------------------------------------
    print(f"[step 2] no cached evidence — running search for: {objective}")
    search_query = f"site:{target_domain} {objective}"
    search_result = fc.search(search_query, limit=5)
    discovered_urls = extract_search_urls(search_result)

    if not discovered_urls:
        print("[step 2] search returned no results — falling back to root URL")
        discovered_urls = [root_url]

    print(f"[step 2] discovered {len(discovered_urls)} candidate URL(s)")

    # ------------------------------------------------------------------
    # Step 3 — optionally use map hint to refine the target
    # ------------------------------------------------------------------
    map_hint = get_hint(capsule, "map")
    target_url = discovered_urls[0]

    if map_hint and len(discovered_urls) == 1 and discovered_urls[0] == root_url:
        print(f"[step 3] map hint active: '{map_hint}'")
        print(f"[step 3] running map on {root_url} to find relevant page")
        # Pass correlationId so the response can be matched back to this capsule.
        # Firecrawl echoes it unchanged — it is not stored or interpreted server-side.
        map_result = fc.map(root_url, limit=20, params={"correlationId": capsule["capsule_id"]})
        mapped_url = select_map_target(map_result, objective)
        if mapped_url:
            target_url = mapped_url
            print(f"[step 3] map matched: {target_url}")
    else:
        print(f"[step 3] using search result directly: {target_url}")

    # ------------------------------------------------------------------
    # Step 4 — scrape the resolved URL
    # ------------------------------------------------------------------
    print(f"[step 4] scraping: {target_url}")
    # correlationId lets the caller verify this response belongs to the current capsule
    # even when multiple concurrent scrapes are in flight.
    scrape_result = fc.scrape(
        target_url,
        formats=["markdown"],
        params={"correlationId": capsule["capsule_id"]},
    )

    # Confirm the echo — Firecrawl returns correlationId unchanged in the response.
    echoed_id = (scrape_result or {}).get("correlationId") if isinstance(scrape_result, dict) else None
    if echoed_id:
        print(f"[step 4] correlationId echoed: {echoed_id}")

    content_preview = ""
    if scrape_result and getattr(scrape_result, "markdown", None):
        content_preview = scrape_result.markdown[:300].replace("\n", " ")

    # ------------------------------------------------------------------
    # Step 5 — write evidence back
    # ------------------------------------------------------------------
    fact = (
        f"content retrieved — preview: {content_preview!r}"
        if content_preview
        else "page reached but no markdown content returned"
    )
    write_evidence(capsule, target_url, fact, ttl_sec=3600)

    print(f"[step 5] evidence written for {target_url}")
    print(f"[step 5] fact: {fact[:120]}...")

    return capsule


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Example task: find pricing information on firecrawl.dev
    OBJECTIVE = "pricing plans"
    TARGET_DOMAIN = "firecrawl.dev"

    updated_capsule = run_workflow(
        objective=OBJECTIVE,
        target_domain=TARGET_DOMAIN,
    )

    print("\n--- updated capsule evidence_log ---")
    print(json.dumps(updated_capsule["evidence_log"], indent=2))
    print("\nWorkflow complete. Persist updated_capsule to your external memory store.")
