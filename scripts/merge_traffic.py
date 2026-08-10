#!/usr/bin/env python3
"""Merge GitHub Traffic API snapshots into docs/metrics/traffic.json.

The Traffic API only retains ~14 days. Run weekly (or more often) and upsert
by date so overlapping windows do not duplicate rows.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "Memuro-Town/MADO-queue")
TOKEN = os.environ["GITHUB_TOKEN"]
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "metrics" / "traffic.json"
API = f"https://api.github.com/repos/{REPO}/traffic"


def fetch(kind: str) -> dict:
    req = urllib.request.Request(
        f"{API}/{kind}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "mado-queue-traffic-snapshot",
        },
    )
    with urllib.request.urlopen(req) as res:
        return json.load(res)


def day_key(ts: str) -> str:
    return ts[:10]


def upsert(bucket: dict[str, dict], rows: list[dict]) -> None:
    for row in rows:
        key = day_key(row["timestamp"])
        bucket[key] = {"count": row["count"], "uniques": row["uniques"]}


def main() -> None:
    existing: dict = {"repo": REPO, "clones": {}, "views": {}}
    if OUT.exists():
        existing = json.loads(OUT.read_text(encoding="utf-8"))
        existing.setdefault("clones", {})
        existing.setdefault("views", {})

    clones = fetch("clones")
    views = fetch("views")
    upsert(existing["clones"], clones.get("clones", []))
    upsert(existing["views"], views.get("views", []))

    existing["repo"] = REPO
    existing["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing["clones"] = dict(sorted(existing["clones"].items()))
    existing["views"] = dict(sorted(existing["views"].items()))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} clones={len(existing['clones'])} views={len(existing['views'])}")


if __name__ == "__main__":
    main()
