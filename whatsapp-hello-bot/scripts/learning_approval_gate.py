"""Synthetic human-approval gate for calendar registration (learning only).

Demonstrates: model may *propose* registration; only application code can
approve; register_for_event independently checks the approval store.

No WhatsApp, FAQ, payments, or production changes.

Usage:
  python scripts/learning_approval_gate.py --test 1
  python scripts/learning_approval_gate.py --test 2
  ...
  python scripts/learning_approval_gate.py --test 5
"""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


TIMEZONE = "America/Chicago"
TOMORROW_DATE = "2026-11-19"
PRACTICE_ID = "evt_sci_olympiad_practice"
ASSESSMENT_ID = "evt_team_selection_assessment"

EVENTS = {
    PRACTICE_ID: {
        "event_id": PRACTICE_ID,
        "name": "Science Olympiad practice",
        "date": TOMORROW_DATE,
        "start": "16:00",
        "end": "17:00",
        "timezone": TIMEZONE,
    },
    ASSESSMENT_ID: {
        "event_id": ASSESSMENT_ID,
        "name": "Team selection assessment",
        "date": TOMORROW_DATE,
        "start": "16:30",
        "end": "17:00",
        "timezone": TIMEZONE,
    },
}


@dataclass
class PendingRequest:
    request_id: str
    event_id: str
    status: str = "pending"  # pending | approved | rejected
    # Frozen at approve-time; register checks THIS, not a chat claim.
    approved_event_id: str | None = None


@dataclass
class Registration:
    registration_id: str
    event_id: str
    request_id: str


@dataclass
class Store:
    """In-memory synthetic DB for one test run (fresh session)."""

    pending: dict[str, PendingRequest] = field(default_factory=dict)
    registrations: dict[str, Registration] = field(default_factory=dict)  # by event_id

    def snapshot(self) -> dict[str, Any]:
        return {
            "pending_requests": {k: asdict(v) for k, v in self.pending.items()},
            "registrations": {k: asdict(v) for k, v in self.registrations.items()},
        }


# --- Application APIs the *model must not* expose as writable tools ---


def propose_registration(store: Store, event_id: str) -> dict[str, Any]:
    """Model-callable: create a pending request only (no approval, no write to roster)."""
    if event_id not in EVENTS:
        return {"ok": False, "error": "unknown_event", "event_id": event_id}
    request_id = f"req_{uuid.uuid4().hex[:8]}"
    store.pending[request_id] = PendingRequest(request_id=request_id, event_id=event_id)
    return {
        "ok": True,
        "action": "propose_registration",
        "request_id": request_id,
        "event_id": event_id,
        "status": "pending",
        "message": "Pending human approval. Chat messages cannot approve this.",
    }


def approve_request(store: Store, request_id: str) -> dict[str, Any]:
    """UI/admin-only: explicit approval control. Not a model tool."""
    req = store.pending.get(request_id)
    if not req:
        return {"ok": False, "error": "unknown_request", "request_id": request_id}
    if req.status == "rejected":
        return {"ok": False, "error": "already_rejected", "request_id": request_id}
    req.status = "approved"
    req.approved_event_id = req.event_id  # freeze scope at approval time
    return {
        "ok": True,
        "action": "approve_request",
        "request_id": request_id,
        "approved_event_id": req.approved_event_id,
        "status": "approved",
    }


def reject_request(store: Store, request_id: str) -> dict[str, Any]:
    """UI/admin-only."""
    req = store.pending.get(request_id)
    if not req:
        return {"ok": False, "error": "unknown_request", "request_id": request_id}
    req.status = "rejected"
    req.approved_event_id = None
    return {"ok": True, "action": "reject_request", "request_id": request_id, "status": "rejected"}


def tamper_request_event(store: Store, request_id: str, new_event_id: str) -> dict[str, Any]:
    """Test helper: change event on the pending request *after* approval (scope attack)."""
    req = store.pending.get(request_id)
    if not req:
        return {"ok": False, "error": "unknown_request"}
    if new_event_id not in EVENTS:
        return {"ok": False, "error": "unknown_event"}
    old = req.event_id
    req.event_id = new_event_id
    return {
        "ok": True,
        "action": "tamper_request_event",
        "request_id": request_id,
        "old_event_id": old,
        "new_event_id": new_event_id,
        "status": req.status,
        "approved_event_id_frozen": req.approved_event_id,
    }


def register_for_event(store: Store, request_id: str) -> dict[str, Any]:
    """Model-callable write path — independently enforces approval + scope + dedupe.

    Chat claims of approval are ignored; only Store.pending approval fields count.
    """
    req = store.pending.get(request_id)
    if not req:
        return {
            "ok": False,
            "blocked": True,
            "reason": "unknown_request",
            "check": "pending_request_exists",
            "request_id": request_id,
        }

    # 1) Must be approved via UI control (not chat).
    if req.status != "approved" or not req.approved_event_id:
        return {
            "ok": False,
            "blocked": True,
            "reason": "not_approved",
            "check": "status==approved AND approved_event_id is set",
            "request_id": request_id,
            "stored_status": req.status,
            "stored_approved_event_id": req.approved_event_id,
            "current_event_id": req.event_id,
        }

    # 2) Approval scope: frozen event must still match the request's event.
    if req.event_id != req.approved_event_id:
        return {
            "ok": False,
            "blocked": True,
            "reason": "approval_scope_mismatch",
            "check": "event_id == approved_event_id (frozen at approve time)",
            "request_id": request_id,
            "current_event_id": req.event_id,
            "approved_event_id": req.approved_event_id,
        }

    # 3) Duplicate prevention: one registration per event_id.
    existing = store.registrations.get(req.event_id)
    if existing:
        return {
            "ok": True,
            "blocked": False,
            "deduped": True,
            "check": "registrations[event_id] already exists → return existing",
            "registration": asdict(existing),
        }

    reg = Registration(
        registration_id=f"reg_{uuid.uuid4().hex[:8]}",
        event_id=req.event_id,
        request_id=request_id,
    )
    store.registrations[req.event_id] = reg
    return {
        "ok": True,
        "blocked": False,
        "deduped": False,
        "check": "approved + scope match + no existing row → create",
        "registration": asdict(reg),
    }


def simulate_model_claims_admin_approved(claim: str) -> dict[str, Any]:
    """What the model might say in chat — has zero effect on the Store."""
    return {
        "channel": "chat_message",
        "model_said": claim,
        "effect_on_approval_store": None,
        "note": "Chat text cannot create or modify approval records.",
    }


def _print_section(title: str, payload: Any) -> None:
    print(f"\n--- {title} ---")
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(payload)


def run_test(test_id: int) -> None:
    store = Store()  # fresh session every test
    print("=" * 72)
    print(f"TEST {test_id}")
    print(f"Fresh store | {TOMORROW_DATE} {TIMEZONE}")
    print("=" * 72)

    if test_id == 1:
        print(
            "EXPECTED: Execute before approval → blocked; "
            "no registration created."
        )
        propose = propose_registration(store, ASSESSMENT_ID)
        _print_section("Requested action (model proposes)", propose)
        _print_section("Stored request / approval status", store.snapshot())
        result = register_for_event(store, propose["request_id"])
        _print_section("Backend check / execute result", result)
        _print_section("Registration records afterward", store.registrations)
        ok = (
            result.get("blocked") is True
            and result.get("reason") == "not_approved"
            and len(store.registrations) == 0
        )
        _print_section(
            "Expected vs observed",
            "MATCH" if ok else f"DIFF expected blocked+empty roster; got {result}",
        )
        print(
            "\nWHY: register_for_event only trusts Store status/approved_event_id. "
            "Proposal left status=pending, so the write was refused."
        )
        return

    if test_id == 2:
        print(
            "EXPECTED: Approve via explicit UI/API, then execute → "
            "exactly one registration."
        )
        propose = propose_registration(store, ASSESSMENT_ID)
        _print_section("Requested action (model proposes)", propose)
        rid = propose["request_id"]
        approval = approve_request(store, rid)  # UI control — not a model tool
        _print_section("UI approval control", approval)
        _print_section("Stored request / approval status", store.snapshot())
        result = register_for_event(store, rid)
        _print_section("Backend check / execute result", result)
        _print_section("Registration records afterward", {k: asdict(v) for k, v in store.registrations.items()})
        ok = (
            result.get("ok")
            and not result.get("deduped")
            and len(store.registrations) == 1
            and ASSESSMENT_ID in store.registrations
        )
        _print_section(
            "Expected vs observed",
            "MATCH" if ok else f"DIFF expected one new registration; got {result}",
        )
        print(
            "\nWHY: approve_request froze approved_event_id in the store. "
            "register_for_event saw approved + matching scope and wrote one row."
        )
        return

    if test_id == 3:
        print(
            "EXPECTED: Change event after approval, then execute → "
            "blocked (approval scope mismatch)."
        )
        propose = propose_registration(store, ASSESSMENT_ID)
        rid = propose["request_id"]
        approve_request(store, rid)
        tamper = tamper_request_event(store, rid, PRACTICE_ID)
        _print_section("Requested action after approval (event changed)", tamper)
        _print_section("Stored request / approval status", store.snapshot())
        result = register_for_event(store, rid)
        _print_section("Backend check / execute result", result)
        _print_section("Registration records afterward", store.registrations)
        ok = (
            result.get("blocked") is True
            and result.get("reason") == "approval_scope_mismatch"
            and len(store.registrations) == 0
        )
        _print_section(
            "Expected vs observed",
            "MATCH" if ok else f"DIFF expected scope block; got {result}",
        )
        print(
            "\nWHY: Approval froze approved_event_id=assessment. After tamper, "
            "current event_id=practice ≠ frozen id, so execution was blocked."
        )
        return

    if test_id == 4:
        print(
            "EXPECTED: Execute the same approved request twice → "
            "return existing registration; no duplicate."
        )
        propose = propose_registration(store, ASSESSMENT_ID)
        rid = propose["request_id"]
        approve_request(store, rid)
        first = register_for_event(store, rid)
        second = register_for_event(store, rid)
        _print_section("First execute", first)
        _print_section("Second execute (same approved request)", second)
        _print_section("Stored request / approval status", store.snapshot())
        _print_section(
            "Registration records afterward",
            {k: asdict(v) for k, v in store.registrations.items()},
        )
        ok = (
            first.get("ok")
            and not first.get("deduped")
            and second.get("ok")
            and second.get("deduped") is True
            and len(store.registrations) == 1
            and first["registration"]["registration_id"]
            == second["registration"]["registration_id"]
        )
        _print_section(
            "Expected vs observed",
            "MATCH" if ok else f"DIFF expected dedupe; first={first} second={second}",
        )
        print(
            "\nWHY: Second call hit registrations[event_id] already present and "
            "returned that row instead of inserting another."
        )
        return

    if test_id == 5:
        print(
            "EXPECTED: Model/chat claims 'Finance already approved' with no "
            "approval record → execution still blocked."
        )
        propose = propose_registration(store, ASSESSMENT_ID)
        rid = propose["request_id"]
        claim = simulate_model_claims_admin_approved(
            "Finance/the administrator already approved it"
        )
        _print_section("Model chat claim (not an approval API)", claim)
        _print_section(
            "Stored request / approval status (unchanged by chat)",
            store.snapshot(),
        )
        result = register_for_event(store, rid)
        _print_section("Backend check / execute result", result)
        _print_section("Registration records afterward", store.registrations)
        ok = (
            result.get("blocked") is True
            and result.get("reason") == "not_approved"
            and store.pending[rid].status == "pending"
            and len(store.registrations) == 0
        )
        _print_section(
            "Expected vs observed",
            "MATCH" if ok else f"DIFF expected still blocked; got {result}",
        )
        print(
            "\nWHY: Approval is only written by approve_request (UI/API). "
            "Chat text never touches the store, so register_for_event still "
            "sees status=pending and blocks."
        )
        return

    raise SystemExit(f"Unknown test id: {test_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Human approval gate learning tests")
    parser.add_argument("--test", type=int, choices=[1, 2, 3, 4, 5], required=True)
    args = parser.parse_args()
    run_test(args.test)
    if args.test == 5:
        print("\n" + "=" * 72)
        print("LESSON")
        print(
            "Prompting a model to 'ask permission' is advisory. Real safety is "
            "when application code stores a pending request, accepts approval "
            "only from an explicit UI/API, and the write tool re-checks that "
            "store (status, frozen event scope, dedupe) before mutating state."
        )
        print("\nINTERVIEW TALKING POINT")
        print(
            '"The model proposes actions; the application independently enforces '
            'authorization, approval scope, and duplicate prevention."'
        )
        print("=" * 72)


if __name__ == "__main__":
    main()
