"""Run answering-engine evaluations without sending WhatsApp messages.

Usage:
  python -m evals.run --engine engine1_legacy
  python -m evals.run --engine engine2_hybrid
  python -m evals.run --engine all
  python -m evals.run --engine engine1_legacy --live-model   # optional, cost-capped
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure package imports work when run as module from whatsapp-hello-bot/
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
os.environ.setdefault("FAQ_GCS_BUCKET", "")
os.environ.setdefault("GUIDED_ENABLED", "true")
os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "eval-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "eval-token")

from app.engine_config import set_selected_engine_id
from app.engines.base import ENGINE_1, ENGINE_2
from app.engines.pipeline import process_message
from app.guided_state import clear_session, set_session
from evals.build_cases import CASES_PATH, main as build_cases

REPORTS = Path(__file__).resolve().parent / "reports"
LIVE_COST_CAP_USD = 0.50


def _load_cases() -> dict[str, Any]:
    if not CASES_PATH.exists():
        build_cases()
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _setup_prior(phone: str, prior: dict[str, Any] | None) -> None:
    clear_session(phone)
    if not prior:
        return
    topic = prior.get("guided_topic")
    step = prior.get("step")
    if topic and step:
        set_session(
            phone,
            {
                "topic_id": topic,
                "step_id": step,
                "human_recommended": False,
                "updated_at": time.time(),
            },
        )


def _score_case(case: dict[str, Any], result, *, engine_id: str) -> dict[str, Any]:
    messages = "\n".join(result.messages or [])
    failures: list[str] = []
    expected_route = case.get("expected_route")
    if expected_route and result.route != expected_route:
        # Engine2 may use guided_continue for correction starts after jump.
        if not (
            engine_id == ENGINE_2
            and expected_route == "guided_start"
            and result.route in {"guided_start", "guided_continue"}
        ):
            failures.append(f"route expected={expected_route} got={result.route}")

    expected_flow = case.get("expected_flow")
    if expected_flow and result.flow_id and result.flow_id != expected_flow:
        failures.append(f"flow expected={expected_flow} got={result.flow_id}")

    for fact in case.get("required_answer_facts") or []:
        if fact.lower() not in messages.lower():
            failures.append(f"missing fact: {fact}")

    for bad in case.get("forbidden_claims") or []:
        if bad.lower() in messages.lower():
            failures.append(f"forbidden claim present: {bad}")

    if case.get("demo_marker_required") and "[DEMO ANSWER]" not in messages:
        failures.append("missing [DEMO ANSWER] marker")

    extracted_exp = case.get("expected_extracted") or {}
    if extracted_exp and engine_id == ENGINE_2:
        for key, val in extracted_exp.items():
            if (result.extracted or {}).get(key) != val:
                # Soft fail for extraction on engine2 only
                failures.append(f"extracted.{key} expected={val} got={(result.extracted or {}).get(key)}")

    preferred = case.get("engine2_preferred_transition")
    if preferred and engine_id == ENGINE_2 and result.state_transition != preferred:
        failures.append(
            f"transition expected={preferred} got={result.state_transition}"
        )

    return {
        "id": case.get("id"),
        "category": case.get("category"),
        "passed": not failures,
        "failures": failures,
        "route": result.route,
        "flow_id": result.flow_id,
        "engine_id": result.engine_id,
        "latency_ms": None,
    }


def run_engine(engine_id: str, cases: list[dict], *, live_model: bool) -> dict[str, Any]:
    if not live_model:
        # Keep deterministic offline runs free of accidental live spend unless opted in.
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY_EVAL", "") or ""
    set_selected_engine_id(engine_id if engine_id in {ENGINE_1, ENGINE_2} else ENGINE_1)

    results = []
    passed = 0
    latencies = []
    for idx, case in enumerate(cases):
        phone = f"1555{idx:07d}"
        _setup_prior(phone, case.get("prior_context"))
        started = time.perf_counter()
        result = process_message(
            phone=phone,
            text=case.get("input") or "",
            message_id=f"eval-{engine_id}-{case.get('id')}",
            message_type="text",
        )
        latency = (time.perf_counter() - started) * 1000
        scored = _score_case(case, result, engine_id=engine_id)
        scored["latency_ms"] = round(latency, 1)
        latencies.append(latency)
        if scored["passed"]:
            passed += 1
        results.append(scored)
        clear_session(phone)

    failed = len(cases) - passed
    by_cat: dict[str, dict[str, int]] = {}
    for row in results:
        cat = row.get("category") or "unknown"
        bucket = by_cat.setdefault(cat, {"passed": 0, "failed": 0})
        if row["passed"]:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1

    return {
        "engine_id": engine_id,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(cases), 3) if cases else 0.0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "by_category": by_cat,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="all")
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--rebuild-cases", action="store_true")
    args = parser.parse_args()

    if args.rebuild_cases or not CASES_PATH.exists():
        build_cases()
    dataset = _load_cases()
    cases = dataset["cases"]

    engines = []
    if args.engine == "all":
        engines = [ENGINE_1, ENGINE_2]
    else:
        engines = [args.engine]

    mode = "live_model" if args.live_model else "deterministic_mocked_safe"
    label = (
        "LIVE MODEL EVALUATION — not mocked"
        if args.live_model
        else "Deterministic / offline-safe evaluation (LLM optional empty)"
    )

    REPORTS.mkdir(parents=True, exist_ok=True)
    engine_rows = []
    for eid in engines:
        print(f"Running {eid} on {len(cases)} cases ({mode})...")
        row = run_engine(eid, cases, live_model=args.live_model)
        engine_rows.append(row)
        out = REPORTS / f"{eid}_{dataset['dataset_version']}_{mode}.json"
        out.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        print(
            f"  pass_rate={row['pass_rate']} passed={row['passed']} failed={row['failed']} "
            f"avg_latency_ms={row['avg_latency_ms']}"
        )

    summary = {
        "dataset_version": dataset["dataset_version"],
        "case_count": len(cases),
        "mode": mode,
        "label": label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_cost_cap_usd": LIVE_COST_CAP_USD if args.live_model else None,
        "engines": [
            {
                "engine_id": r["engine_id"],
                "passed": r["passed"],
                "failed": r["failed"],
                "pass_rate": r["pass_rate"],
                "avg_latency_ms": r["avg_latency_ms"],
                "by_category": r["by_category"],
            }
            for r in engine_rows
        ],
        "empty": False,
    }
    (REPORTS / "latest_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    hist = REPORTS / "history"
    hist.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (hist / f"summary_{stamp}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {REPORTS / 'latest_summary.json'}")


if __name__ == "__main__":
    main()
