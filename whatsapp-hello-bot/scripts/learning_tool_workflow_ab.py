"""Isolated learning harness: fixed vs model-directed tools (A / B / C).

Synthetic calendar only. Does NOT touch FAQ routing, WhatsApp, or production.

  A — fixed workflow: always get_events only (no model tool choice).
  B — model-directed: both tools in API + prompt explains when to use details.
  C — model-directed: both tools in API, but prompt never names get_event_details
      or says attendance comes from it (schemas only).

Resilience scenarios (Version B + Q2, fresh session each run):
  --scenario 1  both event-detail calls succeed
  --scenario 2  assessment details timeout once, then succeed (app retries ≤1)
  --scenario 3  assessment details remain unavailable (explicit error)

Usage (from whatsapp-hello-bot/, venv active):

  python scripts/learning_tool_workflow_ab.py --version B --question 2 --scenario 1
  python scripts/learning_tool_workflow_ab.py --version B --question 2 --scenario 2
  python scripts/learning_tool_workflow_ab.py --version B --question 2 --scenario 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load .env the same way the app does (via app.config import side effects).
os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-minimum!!")

from app.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_REASONING_EFFORT  # noqa: E402

# Explicit experiment clock (not "whatever day you run this").
TIMEZONE = "America/Chicago"
TOMORROW_DATE = "2026-11-19"  # Thursday, day after the 2026-11-18 learning session
MAX_TOOL_CALLS = 6  # headroom when model re-asks after a detail error
MAX_DETAIL_RETRIES = 1  # app-enforced: at most one retry for transient detail failures

PRACTICE_ID = "evt_sci_olympiad_practice"
ASSESSMENT_ID = "evt_team_selection_assessment"

QUESTIONS = {
    1: "What events are tomorrow?",
    2: (
        "My child can attend only one activity tomorrow. "
        "Which should they attend, and why?"
    ),
}


@dataclass
class EventRecord:
    event_id: str
    name: str
    start: str
    end: str
    attendance: str | None  # "optional" | "mandatory" | None when ablated
    notes: str


def build_store(*, ablate_attendance: bool) -> dict[str, EventRecord]:
    """Fictional events for TOMORROW_DATE only."""
    sci = EventRecord(
        event_id="evt_sci_olympiad_practice",
        name="Science Olympiad practice",
        start="16:00",
        end="17:00",
        attendance=None if ablate_attendance else "optional",
        notes="Makeup available." if not ablate_attendance else "Practice session.",
    )
    team = EventRecord(
        event_id="evt_team_selection_assessment",
        name="Team selection assessment",
        start="16:30",
        end="17:00",
        attendance=None if ablate_attendance else "mandatory",
        notes="No makeup." if not ablate_attendance else "Assessment session.",
    )
    return {sci.event_id: sci, team.event_id: team}


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: Any
    attempt: int = 1
    is_retry: bool = False
    error_code: str | None = None


@dataclass
class RunResult:
    version: str
    question: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_answer: str = ""
    latency_ms: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    notes: str = ""
    scenario: int | None = None


@dataclass
class DetailFaultState:
    """Injects synthetic failures for assessment details only; practice always OK."""

    scenario: int  # 1 | 2 | 3
    assessment_attempts: int = 0

    def maybe_fault(self, event_id: str) -> dict[str, Any] | None:
        """Return an explicit error dict, or None to proceed with real details."""
        if event_id != ASSESSMENT_ID:
            return None
        self.assessment_attempts += 1
        if self.scenario == 1:
            return None
        if self.scenario == 2:
            # First look-up times out; later look-ups succeed.
            if self.assessment_attempts == 1:
                return {
                    "error": "timeout",
                    "transient": True,
                    "event_id": event_id,
                    "message": (
                        "Timed out fetching event details for "
                        f"{event_id}. Transient failure."
                    ),
                }
            return None
        if self.scenario == 3:
            return {
                "error": "unavailable",
                "transient": False,
                "event_id": event_id,
                "message": (
                    "Event details for "
                    f"{event_id} are unavailable. "
                    "No attendance rule was returned."
                ),
            }
        return None


def make_tools(
    store: dict[str, EventRecord],
    fault: DetailFaultState | None = None,
) -> dict[str, Callable[..., Any]]:
    def get_events(date: str) -> list[dict[str, str]]:
        if date != TOMORROW_DATE:
            return []
        out = []
        for ev in store.values():
            out.append(
                {
                    "event_id": ev.event_id,
                    "name": ev.name,
                    "start": ev.start,
                    "end": ev.end,
                    "timezone": TIMEZONE,
                    "date": TOMORROW_DATE,
                }
            )
        return sorted(out, key=lambda row: row["start"])

    def get_event_details(event_id: str) -> dict[str, Any]:
        if fault is not None:
            injected = fault.maybe_fault(event_id)
            if injected is not None:
                return injected
        ev = store.get(event_id)
        if not ev:
            return {
                "error": "unknown_event",
                "transient": False,
                "event_id": event_id,
                "message": f"unknown event_id: {event_id}",
            }
        payload: dict[str, Any] = {
            "event_id": ev.event_id,
            "name": ev.name,
            "date": TOMORROW_DATE,
            "start": ev.start,
            "end": ev.end,
            "timezone": TIMEZONE,
            "notes": ev.notes,
        }
        if ev.attendance is None:
            payload["attendance"] = None
            payload["attendance_note"] = (
                "Attendance requirement is not available in the data store."
            )
        else:
            payload["attendance"] = ev.attendance
        return payload

    return {"get_events": get_events, "get_event_details": get_event_details}


# Responses API tool schemas (required for gpt-5* + function tools).
TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": "get_events",
        "description": (
            f"List events for a calendar date ({TIMEZONE}). "
            "Returns only event_id, name, and times — not attendance rules."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "YYYY-MM-DD in America/Chicago",
                }
            },
            "required": ["date"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_event_details",
        "description": (
            "Get details for one event_id, including attendance "
            "(mandatory/optional) when present in the store."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
    },
]


def _error_code(result: Any) -> str | None:
    if isinstance(result, dict) and result.get("error"):
        return str(result.get("error"))
    return None


def _is_transient_detail_error(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and bool(result.get("error"))
        and bool(result.get("transient")) is True
    )


def _validate_and_run(
    name: str,
    raw_args: dict[str, Any],
    tools: dict[str, Callable[..., Any]],
) -> tuple[dict[str, Any], list[ToolCallRecord]]:
    """Validate args, execute tool, and (for details) retry once if transient.

    Returns (validated_args, attempt_records). The last record's result is what
    should be sent back to the model. Errors are explicit dicts, never empty OK.
    """
    if name not in tools:
        err = {"error": "tool_not_allowed", "transient": False, "message": f"tool not allowed: {name}"}
        return {}, [ToolCallRecord(name, dict(raw_args), err, error_code="tool_not_allowed")]
    if name == "get_events":
        date = raw_args.get("date")
        if not isinstance(date, str) or len(date) != 10:
            err = {
                "error": "invalid_args",
                "transient": False,
                "message": "get_events requires date as YYYY-MM-DD string",
            }
            return raw_args, [ToolCallRecord(name, dict(raw_args), err, error_code="invalid_args")]
        args = {"date": date}
        result = tools[name](date=date)
        return args, [ToolCallRecord(name, args, result, error_code=_error_code(result))]
    if name == "get_event_details":
        event_id = raw_args.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            err = {
                "error": "invalid_args",
                "transient": False,
                "message": "get_event_details requires non-empty event_id string",
            }
            return raw_args, [ToolCallRecord(name, dict(raw_args), err, error_code="invalid_args")]
        args = {"event_id": event_id.strip()}
        attempts: list[ToolCallRecord] = []
        result = tools[name](event_id=args["event_id"])
        attempts.append(
            ToolCallRecord(
                name,
                args,
                result,
                attempt=1,
                is_retry=False,
                error_code=_error_code(result),
            )
        )
        if _is_transient_detail_error(result) and MAX_DETAIL_RETRIES >= 1:
            result = tools[name](event_id=args["event_id"])
            attempts.append(
                ToolCallRecord(
                    name,
                    args,
                    result,
                    attempt=2,
                    is_retry=True,
                    error_code=_error_code(result),
                )
            )
        return args, attempts
    err = {"error": "unreachable", "transient": False}
    return raw_args, [ToolCallRecord(name, dict(raw_args), err, error_code="unreachable")]


def run_version_a(question: str, tools: dict[str, Callable[..., Any]]) -> RunResult:
    """Fixed workflow: always get_events(TOMORROW_DATE); never call details; no model tools."""
    started = time.perf_counter()
    args = {"date": TOMORROW_DATE}
    evidence = tools["get_events"](**args)
    latency_ms = (time.perf_counter() - started) * 1000
    lines = [
        f"Schedule for {TOMORROW_DATE} ({TIMEZONE}):",
    ]
    if not evidence:
        lines.append("No events found.")
    else:
        for row in evidence:
            lines.append(
                f"- {row['name']} ({row['start']}–{row['end']}, id={row['event_id']})"
            )
    lines.append(
        "(Fixed workflow: get_events only — attendance/details were not fetched.)"
    )
    return RunResult(
        version="A",
        question=question,
        tool_calls=[ToolCallRecord("get_events", args, evidence)],
        final_answer="\n".join(lines),
        latency_ms=round(latency_ms, 1),
        input_tokens=0,
        output_tokens=0,
        model=None,
        notes="Deterministic fixed path; no LLM.",
    )


def _system_prompt_b() -> str:
    """Prompt explicitly teaches when attendance/details tools are needed."""
    return (
        "You help a parent with a fictional school calendar.\n"
        f"Today's reference: the parent's 'tomorrow' is {TOMORROW_DATE} "
        f"in timezone {TIMEZONE}. Always use that date with get_events.\n"
        "You may only use the provided tools. The application executes them.\n"
        "get_events returns ids/names/times only. Attendance mandatory/optional "
        "is only available via get_event_details when the store provides it.\n"
        "Rules:\n"
        "1. Do not invent events, times, or attendance rules.\n"
        "2. Any recommendation (which event to attend, and why) MUST be supported "
        "by tool results you actually received.\n"
        "3. If attendance requirements are missing OR a tool returns an explicit "
        "error (timeout/unavailable), explain what is missing; do not invent the "
        "missing attendance rule; do not confidently pick an event without enough "
        "evidence. Ask a clarifying question if helpful.\n"
        "4. Keep the final answer concise for a parent."
    )


def _system_prompt_c() -> str:
    """Same date/safety rules, but never names get_event_details or attendance source.

    Both tools remain in the API `tools` list; discovery must come from schemas.
    """
    return (
        "You help a parent with a fictional school calendar.\n"
        f"Today's reference: the parent's 'tomorrow' is {TOMORROW_DATE} "
        f"in timezone {TIMEZONE}.\n"
        "You may only use the provided tools. The application executes them.\n"
        "Rules:\n"
        "1. Do not invent events, times, or policies.\n"
        "2. Only use facts returned by tools in this conversation.\n"
        "3. Keep the final answer concise for a parent."
    )


def _responses_function_calls(resp: Any) -> list[Any]:
    calls = []
    for item in getattr(resp, "output", None) or []:
        typ = getattr(item, "type", None)
        if typ == "function_call":
            calls.append(item)
    return calls


def _responses_text(resp: Any) -> str:
    text = getattr(resp, "output_text", None)
    if text:
        return str(text).strip()
    parts: list[str] = []
    for item in getattr(resp, "output", None) or []:
        if getattr(item, "type", None) == "message":
            for block in getattr(item, "content", None) or []:
                if getattr(block, "type", None) in {"output_text", "text"}:
                    parts.append(str(getattr(block, "text", "") or ""))
    return "\n".join(p for p in parts if p).strip()


def run_version_model_tools(
    question: str,
    tools: dict[str, Callable[..., Any]],
    *,
    version: str,
    instructions: str,
    notes: str,
    scenario: int | None = None,
) -> RunResult:
    """Model-directed tools via Responses API; app executes + validates; max MAX_TOOL_CALLS."""
    if not OPENAI_API_KEY:
        raise RuntimeError(f"OPENAI_API_KEY is required for Version {version}")

    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    recorded: list[ToolCallRecord] = []
    started = time.perf_counter()
    in_tok = 0
    out_tok = 0
    final = ""

    previous_response_id: str | None = None
    next_input: list[dict[str, Any]] | str = [
        {"role": "user", "content": question},
    ]

    for _ in range(MAX_TOOL_CALLS + 1):
        create_kwargs: dict[str, Any] = {
            "model": OPENAI_MODEL,
            "instructions": instructions,
            "input": next_input,
            "tools": TOOL_SCHEMAS,
        }
        if previous_response_id:
            create_kwargs["previous_response_id"] = previous_response_id
        if OPENAI_REASONING_EFFORT:
            create_kwargs["reasoning"] = {"effort": OPENAI_REASONING_EFFORT}
        try:
            resp = client.responses.create(**create_kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            if "reasoning" in msg and "reasoning" in create_kwargs:
                create_kwargs.pop("reasoning", None)
                resp = client.responses.create(**create_kwargs)
            else:
                raise

        previous_response_id = getattr(resp, "id", None) or previous_response_id
        usage = getattr(resp, "usage", None)
        if usage:
            in_tok += int(getattr(usage, "input_tokens", 0) or 0)
            out_tok += int(getattr(usage, "output_tokens", 0) or 0)

        calls = _responses_function_calls(resp)
        if not calls:
            final = _responses_text(resp)
            break

        if len(recorded) >= MAX_TOOL_CALLS:
            final = (
                "Stopped: model requested more tools after the "
                f"{MAX_TOOL_CALLS}-call limit. Partial evidence only."
            )
            break

        outputs: list[dict[str, Any]] = []
        for call in calls:
            if len(recorded) >= MAX_TOOL_CALLS:
                break
            name = getattr(call, "name", "") or ""
            call_id = getattr(call, "call_id", None) or getattr(call, "id", "")
            try:
                raw_args = json.loads(getattr(call, "arguments", None) or "{}")
            except json.JSONDecodeError:
                raw_args = {}
            if not isinstance(raw_args, dict):
                raw_args = {}
            _validated_args, attempt_records = _validate_and_run(name, raw_args, tools)
            # Count each physical attempt toward the call budget visibility.
            for rec in attempt_records:
                if len(recorded) >= MAX_TOOL_CALLS:
                    break
                recorded.append(rec)
            # Model only sees the final attempt result for this tool_call_id.
            final_result = attempt_records[-1].result if attempt_records else {
                "error": "empty_tool_result",
                "transient": False,
                "message": "No tool result produced.",
            }
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(final_result, ensure_ascii=False),
                }
            )
        next_input = outputs

        if len(recorded) >= MAX_TOOL_CALLS and not final:
            close_kwargs: dict[str, Any] = {
                "model": OPENAI_MODEL,
                "instructions": instructions,
                "previous_response_id": previous_response_id,
                "input": (
                    outputs
                    + [
                        {
                            "role": "user",
                            "content": (
                                "You have reached the tool-call limit. "
                                "Answer now using only evidence already returned. "
                                "Do not invent facts."
                            ),
                        }
                    ]
                ),
            }
            if OPENAI_REASONING_EFFORT:
                close_kwargs["reasoning"] = {"effort": OPENAI_REASONING_EFFORT}
            try:
                close = client.responses.create(**close_kwargs)
            except Exception as exc:
                if "reasoning" in str(exc).lower() and "reasoning" in close_kwargs:
                    close_kwargs.pop("reasoning", None)
                    close = client.responses.create(**close_kwargs)
                else:
                    raise
            usage = getattr(close, "usage", None)
            if usage:
                in_tok += int(getattr(usage, "input_tokens", 0) or 0)
                out_tok += int(getattr(usage, "output_tokens", 0) or 0)
            final = _responses_text(close)
            break
    else:
        final = final or "(No final answer produced.)"

    latency_ms = (time.perf_counter() - started) * 1000
    return RunResult(
        version=version,
        question=question,
        tool_calls=recorded,
        final_answer=final or "(empty model answer)",
        latency_ms=round(latency_ms, 1),
        input_tokens=in_tok,
        output_tokens=out_tok,
        model=OPENAI_MODEL,
        notes=notes,
        scenario=scenario,
    )


def run_version_b(
    question: str,
    tools: dict[str, Callable[..., Any]],
    *,
    scenario: int | None = None,
) -> RunResult:
    scenario_note = f"; scenario={scenario}" if scenario is not None else ""
    return run_version_model_tools(
        question,
        tools,
        version="B",
        instructions=_system_prompt_b(),
        notes=(
            f"Model-directed + explicit details/attendance coaching; "
            f"max_tool_calls={MAX_TOOL_CALLS}; detail_retries≤{MAX_DETAIL_RETRIES}; "
            f"reasoning_env={OPENAI_REASONING_EFFORT}{scenario_note}; fresh session"
        ),
        scenario=scenario,
    )


def run_version_c(question: str, tools: dict[str, Callable[..., Any]]) -> RunResult:
    return run_version_model_tools(
        question,
        tools,
        version="C",
        instructions=_system_prompt_c(),
        notes=(
            f"Both tools in API schemas; prompt never names get_event_details; "
            f"max_tool_calls={MAX_TOOL_CALLS}; reasoning_env={OPENAI_REASONING_EFFORT}"
        ),
    )


def print_result(result: RunResult) -> None:
    print("=" * 72)
    print(f"Version {result.version}")
    if result.scenario is not None:
        print(f"Scenario: {result.scenario}")
    print(f"Timezone / tomorrow: {TIMEZONE} / {TOMORROW_DATE}")
    print(f"Question: {result.question}")
    if result.model:
        print(f"Model: {result.model}")
    if result.notes:
        print(f"Notes: {result.notes}")
    print("-" * 72)
    print("Tool calls (includes app-side retries):")
    if not result.tool_calls:
        print("  (none)")
    retries = 0
    errors = 0
    for i, call in enumerate(result.tool_calls, 1):
        flags = []
        if call.is_retry:
            flags.append("RETRY")
            retries += 1
        if call.error_code:
            flags.append(f"ERROR={call.error_code}")
            errors += 1
        flag_s = f" [{', '.join(flags)}]" if flags else ""
        print(
            f"  {i}. {call.name}({json.dumps(call.arguments, ensure_ascii=False)}) "
            f"attempt={call.attempt}{flag_s}"
        )
        print(f"     -> {json.dumps(call.result, ensure_ascii=False)}")
    print(f"Retry count: {retries} | Error attempts: {errors}")
    print("-" * 72)
    print("Final answer:")
    print(result.final_answer)
    print("-" * 72)
    print(f"Latency: {result.latency_ms} ms")
    print(f"Tokens in/out: {result.input_tokens} / {result.output_tokens}")
    print("=" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tool workflow A/B/C learning harness")
    parser.add_argument("--version", choices=["A", "B", "C"], required=True)
    parser.add_argument("--question", type=int, choices=[1, 2], required=True)
    parser.add_argument(
        "--scenario",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="Resilience scenario for detail-tool faults (use with --version B --question 2)",
    )
    parser.add_argument(
        "--ablate-attendance",
        action="store_true",
        help="Remove mandatory/optional from get_event_details (clarification test)",
    )
    args = parser.parse_args()

    store = build_store(ablate_attendance=args.ablate_attendance)
    fault = DetailFaultState(scenario=args.scenario) if args.scenario else None
    tools = make_tools(store, fault=fault)
    question = QUESTIONS[args.question]

    print(
        f"Store mode: {'ABLATED attendance' if args.ablate_attendance else 'full attendance details'}"
    )
    if args.scenario:
        print(f"Fault scenario: {args.scenario} (practice details always available)")
    if args.version == "A":
        result = run_version_a(question, tools)
    elif args.version == "B":
        result = run_version_b(question, tools, scenario=args.scenario)
    else:
        result = run_version_c(question, tools)
    print_result(result)


if __name__ == "__main__":
    main()
