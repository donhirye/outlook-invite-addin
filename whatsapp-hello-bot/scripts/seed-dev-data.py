"""Seed data/dev from shared data/ with light student-PII sanitization.

Preserves staff/teacher emails and school contacts. Replaces known student
athlete name mentions in FAQ answers with a generic phrase.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHARED = ROOT / "data"
DEV = ROOT / "data" / "dev"

# Curated student-identifying strings observed in the FAQ corpus (not staff).
_STUDENT_NAME_PATTERNS = (
    (re.compile(r"\bEthan McMurtry\b", re.I), "a Crone player"),
)


def _sanitize_text(text: str) -> str:
    out = text
    for pat, repl in _STUDENT_NAME_PATTERNS:
        out = pat.sub(repl, out)
    out = re.sub(r"(?<=[.!?]\s)a Crone player", "A Crone player", out)
    out = re.sub(r"(?m)^A: a Crone player", "A: A Crone player", out)
    return out


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in {".txt", ".json", ".jsonl"}:
        raw = src.read_text(encoding="utf-8")
        dest.write_text(_sanitize_text(raw), encoding="utf-8")
    else:
        shutil.copy2(src, dest)


def main() -> None:
    DEV.mkdir(parents=True, exist_ok=True)
    for name in ("science_olympiad_faq.txt", "faq_records.json", "greeting.json"):
        src = SHARED / name
        if src.exists():
            _copy_file(src, DEV / name)
    guided_src = SHARED / "guided"
    guided_dst = DEV / "guided"
    if guided_src.exists():
        if guided_dst.exists():
            shutil.rmtree(guided_dst)
        shutil.copytree(guided_src, guided_dst)
    cal = SHARED / "school_calendar.json"
    if cal.exists():
        _copy_file(cal, DEV / "school_calendar.json")
    for pattern in ("*.index.json", "answer_traces.jsonl", "analytics_events.jsonl"):
        for stale in DEV.glob(pattern):
            stale.unlink(missing_ok=True)
    print(f"Seeded {DEV}")
    if (DEV / "faq_records.json").exists():
        data = json.loads((DEV / "faq_records.json").read_text(encoding="utf-8"))
        n = len(data.get("records") or {})
        print(f"FAQ records: {n}")


if __name__ == "__main__":
    main()
