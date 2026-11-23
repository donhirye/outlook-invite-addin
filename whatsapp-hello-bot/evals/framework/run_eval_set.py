"""Run evals/eval_set.md prompts through strategies A/C/E/Ep → multi-sheet workbook.

Usage (from whatsapp-hello-bot/):
  python -m evals.framework.run_eval_set
  python -m evals.framework.run_eval_set --out evals/reports/eval_set_strategies.xlsx
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import traceback
from datetime import date
from pathlib import Path

# Ensure repo app imports work when run as a module.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-eval-framework-32chars")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ.setdefault("FAQ_GCS_BUCKET", "")
os.environ.setdefault("EVAL_FRAMEWORK_ENABLED", "true")

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

EVAL_SET = ROOT / "evals" / "eval_set.md"
IMPORT_DIR = ROOT / "data" / "imports"
# Eval "today" before Jan 2027 PTSA meeting (EV-007).
EVAL_TODAY = date(2026, 11, 22)
STRATEGIES = ("A", "C", "E", "Ep")


def parse_eval_set(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    cases: list[dict] = []
    blocks = re.split(r"\n(?=## EV-\d+)", text)
    for block in blocks:
        m = re.match(r"## (EV-\d+)\s*[—\-]\s*(.+)", block.strip())
        if not m:
            continue
        case_id, title = m.group(1), m.group(2).strip()
        prompt_m = re.search(
            r"### Prompt\n(.+?)(?=\n### |\n---|\Z)", block, re.S
        )
        prompt = (prompt_m.group(1).strip() if prompt_m else "").strip()
        # Skip meta cases with no concrete parent utterance
        if not prompt or prompt.lower().startswith("any faq"):
            cases.append(
                {
                    "id": case_id,
                    "title": title,
                    "prompt": "",
                    "skip_reason": "no concrete prompt (meta / deferred)",
                    "expected_facts": _facts(block),
                }
            )
            continue
        cases.append(
            {
                "id": case_id,
                "title": title,
                "prompt": prompt,
                "skip_reason": "",
                "expected_facts": _facts(block),
            }
        )
    return cases


def _facts(block: str) -> str:
    m = re.search(
        r"### Expected (?:answer facts|behavior)\n(.+?)(?=\n### |\n---|\Z)",
        block,
        re.S,
    )
    if not m:
        return ""
    lines = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("- "):
            lines.append(line[2:].strip("` "))
        elif line and not line.startswith("(") and not line.startswith("Must "):
            if line[0].isdigit() and ". " in line[:4]:
                lines.append(line.split(". ", 1)[-1])
    return " | ".join(lines[:12])


def _setup_data() -> None:
    from app import calendar_store
    from app.faq_records import clear_faq_records_cache, ensure_faq_records_seeded

    calendar_store.clear_calendar_cache()
    # Prefer durable local calendar if present; else import CSVs into temp file.
    cal_path = ROOT / "data" / "calendar.json"
    if not cal_path.exists() or cal_path.stat().st_size < 50:
        # import into default calendar file location used by app
        calendar_store.CALENDAR_FILE = cal_path
        calendar_store.FAQ_GCS_BUCKET = ""
        for name in (
            "school_district_204_2026_2027_calendar.csv",
            "crone_2026_2027_calendar.csv",
        ):
            p = IMPORT_DIR / name
            if p.exists():
                calendar_store.import_calendar_csv_text(
                    p.read_text(encoding="utf-8-sig")
                )
    clear_faq_records_cache()
    ensure_faq_records_seeded()

    # Freeze "today" for overview + calendar next-event logic
    import app.calendar_service as cal_svc
    import app.faq_records as faq_rec
    import app.overview_service as overview

    cal_svc.chicago_today = lambda: EVAL_TODAY  # type: ignore
    faq_rec.chicago_today = lambda: EVAL_TODAY  # type: ignore
    overview.chicago_today = lambda: EVAL_TODAY  # type: ignore
    # Match staging model for bake-offs (local .env may differ).
    import app.config as config
    import app.faq_service as faq_svc

    config.OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
    faq_svc.OPENAI_MODEL = config.OPENAI_MODEL
    overview.OPENAI_MODEL = config.OPENAI_MODEL


def run_one(prompt: str, strategy: str):
    from app.engines.base import ConversationContext
    from app.engines.engine1_legacy import LegacyEngine
    import app.config as config

    config.EVAL_FRAMEWORK_ENABLED = True
    config.ANSWER_STRATEGY = strategy

    engine = LegacyEngine()
    ctx = ConversationContext(
        phone_hash="eval",
        phone="15550990000",
        message_id=f"eval-{strategy}",
        text=prompt,
        extras={"answer_strategy": strategy},
    )
    result = engine.answer(ctx)
    answer = "\n\n".join(result.messages or [])
    return {
        "route": result.route,
        "retrieval_mode": result.retrieval_mode,
        "answer_strategy": result.answer_strategy,
        "answer": answer,
        "source_name": result.source_name or "",
        "faq_id": result.faq_id or "",
        "llm_invocations": (result.model_usage.invocations if result.model_usage else 0),
        "error": result.error or "",
    }


def write_workbook(cases: list[dict], results: dict[str, list[dict]], out: Path) -> None:
    wb = Workbook()
    # Summary tab
    summary = wb.active
    summary.title = "Summary"
    headers = [
        "id",
        "title",
        "prompt",
        "expected_facts",
        "skip_reason",
    ]
    for s in STRATEGIES:
        headers.extend([f"{s}_route", f"{s}_answer"])
    summary.append(headers)
    for i, case in enumerate(cases):
        row = [
            case["id"],
            case["title"],
            case["prompt"],
            case.get("expected_facts", ""),
            case.get("skip_reason", ""),
        ]
        for s in STRATEGIES:
            r = results[s][i]
            row.append(r.get("route", ""))
            row.append(r.get("answer", ""))
        summary.append(row)
    summary.freeze_panes = "A2"
    for col in summary.columns:
        summary.column_dimensions[col[0].column_letter].width = min(48, 18)

    wrap = Alignment(wrap_text=True, vertical="top")
    bold = Font(bold=True)

    for s in STRATEGIES:
        ws = wb.create_sheet(title=f"Strategy_{s}")
        ws.append(
            [
                "id",
                "title",
                "prompt",
                "expected_facts",
                "route",
                "retrieval_mode",
                "answer_strategy",
                "llm_invocations",
                "faq_id",
                "source_name",
                "answer",
                "error",
                "skip_reason",
            ]
        )
        for cell in ws[1]:
            cell.font = bold
        for i, case in enumerate(cases):
            r = results[s][i]
            ws.append(
                [
                    case["id"],
                    case["title"],
                    case["prompt"],
                    case.get("expected_facts", ""),
                    r.get("route", ""),
                    r.get("retrieval_mode", ""),
                    r.get("answer_strategy", ""),
                    r.get("llm_invocations", 0),
                    r.get("faq_id", ""),
                    r.get("source_name", ""),
                    r.get("answer", ""),
                    r.get("error", ""),
                    case.get("skip_reason", ""),
                ]
            )
        ws.freeze_panes = "A2"
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = wrap
        ws.column_dimensions["C"].width = 40
        ws.column_dimensions["D"].width = 40
        ws.column_dimensions["K"].width = 80

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "evals" / "reports" / "eval_set_strategies.xlsx",
    )
    parser.add_argument(
        "--strategies",
        default="A,C,E,Ep",
        help="Comma-separated strategy ids",
    )
    args = parser.parse_args()
    global STRATEGIES
    STRATEGIES = tuple(s.strip() for s in args.strategies.split(",") if s.strip())

    cases = parse_eval_set(EVAL_SET)
    print(f"Parsed {len(cases)} cases from {EVAL_SET}")
    print(f"EVAL_TODAY={EVAL_TODAY.isoformat()} strategies={STRATEGIES}")
    _setup_data()

    results: dict[str, list[dict]] = {s: [] for s in STRATEGIES}
    for s in STRATEGIES:
        print(f"\n=== Strategy {s} ===")
        for case in cases:
            if case.get("skip_reason") or not case.get("prompt"):
                results[s].append(
                    {
                        "route": "skipped",
                        "answer": "",
                        "skip": case.get("skip_reason"),
                        "retrieval_mode": "",
                        "answer_strategy": s,
                        "llm_invocations": 0,
                        "faq_id": "",
                        "source_name": "",
                        "error": "",
                    }
                )
                print(f"  {case['id']}: skipped")
                continue
            try:
                out = run_one(case["prompt"], s)
                results[s].append(out)
                preview = (out["answer"] or "").replace("\n", " ")[:100]
                print(f"  {case['id']}: {out['route']} | {preview}")
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                results[s].append(
                    {
                        "route": "error",
                        "answer": "",
                        "error": err,
                        "retrieval_mode": "",
                        "answer_strategy": s,
                        "llm_invocations": 0,
                        "faq_id": "",
                        "source_name": "",
                    }
                )
                print(f"  {case['id']}: ERROR {err}")
                traceback.print_exc()

    write_workbook(cases, results, args.out)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
