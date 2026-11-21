"""Reconcile candidate newsletter FAQ CSVs into a canonical combined_FAQ."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from newsletter_archive.config import NEWSLETTER_LOCAL_ROOT, ensure_local_dirs
from newsletter_archive.faq_extract import FAQ_COLUMNS
from newsletter_archive.reconciler_prompt import (
    RECONCILER_SYSTEM_PROMPT,
    build_reconcile_user_prompt,
)
from newsletter_archive.text_clean import clean_faq_text

logger = logging.getLogger(__name__)

COMBINED_FAQ_CSV = "combined_FAQ.csv"
COMBINED_FAQ_REPORT = "combined_FAQ_Reconciliation.md"

VALID_CLASSIFICATIONS = {"New", "Duplicate", "Update", "Conflict", "Review"}


@dataclass
class Decision:
    candidate_faq_id: str
    candidate_question: str
    classification: str
    matching_faq_id: str
    note: str
    provenance_source: str = ""
    updated_record: dict[str, str] | None = None


@dataclass
class BatchResult:
    label: str
    decisions: list[Decision] = field(default_factory=list)
    privacy_flags: list[dict[str, str]] = field(default_factory=list)
    change_log: dict[str, list[str]] = field(default_factory=dict)


def combined_faq_paths(root: Path | None = None) -> tuple[Path, Path]:
    base = root or NEWSLETTER_LOCAL_ROOT
    ensure_local_dirs()
    return base / COMBINED_FAQ_CSV, base / COMBINED_FAQ_REPORT


def empty_canonical() -> list[dict[str, str]]:
    return []


def read_faq_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    cleaned: list[dict[str, str]] = []
    for row in rows:
        cleaned.append(
            {
                "FAQ_ID": (row.get("FAQ_ID") or "").strip(),
                "Category": clean_faq_text(row.get("Category") or ""),
                "Question": clean_faq_text(row.get("Question") or ""),
                "Answer": clean_faq_text(row.get("Answer") or ""),
                "Source": clean_faq_text(row.get("Source") or ""),
                "Source_URL": (row.get("Source_URL") or "").strip(),
                "Published_Date": (row.get("Published_Date") or "").strip(),
                "Event_Date": (row.get("Event_Date") or "").strip(),
                "Status": (row.get("Status") or "Active").strip() or "Active",
            }
        )
    return [r for r in cleaned if r["FAQ_ID"] and r["Question"] and r["Answer"]]


def write_faq_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    """Write CSV; if the target is locked (Excel), write a sibling *_new.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    targets = [path]
    if path.suffix.lower() == ".csv":
        targets.append(path.with_name(f"{path.stem}_new{path.suffix}"))
    last_err: Exception | None = None
    for target in targets:
        try:
            with target.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FAQ_COLUMNS, lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({c: row.get(c, "") for c in FAQ_COLUMNS})
            if target != path:
                logger.warning(
                    "Could not write %s (file locked?); wrote %s instead",
                    path.name,
                    target.name,
                )
            return target
        except PermissionError as exc:
            last_err = exc
            continue
    raise PermissionError(str(last_err or f"Could not write {path}"))


def _row_from_updated(raw: dict, *, fallback_id: str) -> dict[str, str]:
    status = clean_faq_text(raw.get("status") or raw.get("Status") or "Active") or "Active"
    if status not in {"Active", "Needs_Review"}:
        status = "Needs_Review"
    return {
        "FAQ_ID": (raw.get("faq_id") or raw.get("FAQ_ID") or fallback_id).strip(),
        "Category": clean_faq_text(raw.get("category") or raw.get("Category") or "General")
        or "General",
        "Question": clean_faq_text(raw.get("question") or raw.get("Question") or ""),
        "Answer": clean_faq_text(raw.get("answer") or raw.get("Answer") or ""),
        "Source": clean_faq_text(raw.get("source") or raw.get("Source") or ""),
        "Source_URL": (raw.get("source_url") or raw.get("Source_URL") or "").strip(),
        "Published_Date": (
            raw.get("published_date") or raw.get("Published_Date") or ""
        ).strip(),
        "Event_Date": (raw.get("event_date") or raw.get("Event_Date") or "").strip(),
        "Status": status,
    }


def apply_decisions(
    canonical: list[dict[str, str]],
    candidates: list[dict[str, str]],
    decisions: list[Decision],
) -> list[dict[str, str]]:
    """Return new canonical list. Never deletes.

    Duplicate: leave existing row unchanged.
    Conflict: keep existing FAQ_ID, replace content with the latest candidate,
    force Status=Needs_Review (conflict remains flagged in the report).
    """
    by_id = {r["FAQ_ID"]: dict(r) for r in canonical}
    order = [r["FAQ_ID"] for r in canonical]
    candidate_by_id = {c["FAQ_ID"]: c for c in candidates}

    for dec in decisions:
        cls = dec.classification
        if cls == "Duplicate":
            continue

        if cls in {"Update", "Conflict"}:
            match_id = (dec.matching_faq_id or "").strip()
            if not match_id or match_id not in by_id:
                logger.warning(
                    "%s without valid matching_faq_id for %s; skip apply",
                    cls,
                    dec.candidate_faq_id,
                )
                continue
            raw = dec.updated_record
            if not raw:
                # Conflict/Update must still prefer latest candidate when model omitted body.
                cand = candidate_by_id.get(dec.candidate_faq_id)
                if not cand:
                    logger.warning(
                        "%s missing updated_record and candidate for %s",
                        cls,
                        dec.candidate_faq_id,
                    )
                    continue
                raw = cand
            old = by_id[match_id]
            updated = _row_from_updated(raw, fallback_id=match_id)
            updated["FAQ_ID"] = match_id  # hard rule: preserve existing ID
            if cls == "Conflict":
                updated["Status"] = "Needs_Review"
                # Prefer candidate published date when present (latest issue).
                if not updated["Published_Date"]:
                    updated["Published_Date"] = (
                        candidate_by_id.get(dec.candidate_faq_id, {}).get("Published_Date")
                        or old.get("Published_Date", "")
                    )
                # Enrich note is in the report; ensure answer came from latest.
                if not updated["Answer"]:
                    updated["Answer"] = old.get("Answer", "")
            else:
                if not updated["Published_Date"]:
                    updated["Published_Date"] = old.get("Published_Date", "")
            by_id[match_id] = updated
            continue

        if cls in {"New", "Review"}:
            if not dec.updated_record and cls == "Review":
                # Review-only flag, no add
                continue
            src = dec.updated_record or candidate_by_id.get(dec.candidate_faq_id) or {}
            if isinstance(src, dict) and "FAQ_ID" in src and "faq_id" not in src:
                # already canonical-shaped candidate
                new_row = {
                    "FAQ_ID": src["FAQ_ID"],
                    "Category": clean_faq_text(src.get("Category") or "General") or "General",
                    "Question": clean_faq_text(src.get("Question") or ""),
                    "Answer": clean_faq_text(src.get("Answer") or ""),
                    "Source": clean_faq_text(src.get("Source") or ""),
                    "Source_URL": (src.get("Source_URL") or "").strip(),
                    "Published_Date": (src.get("Published_Date") or "").strip(),
                    "Event_Date": (src.get("Event_Date") or "").strip(),
                    "Status": "Needs_Review"
                    if cls == "Review"
                    else ((src.get("Status") or "Active").strip() or "Active"),
                }
            else:
                new_row = _row_from_updated(
                    src if isinstance(src, dict) else {},
                    fallback_id=dec.candidate_faq_id,
                )
                if cls == "Review":
                    new_row["Status"] = "Needs_Review"

            if not new_row["Question"] or not new_row["Answer"]:
                continue
            faq_id = new_row["FAQ_ID"] or dec.candidate_faq_id
            if faq_id in by_id:
                # collision: suffix -R{n}
                n = 2
                while f"{faq_id}-R{n}" in by_id:
                    n += 1
                faq_id = f"{faq_id}-R{n}"
                new_row["FAQ_ID"] = faq_id
            by_id[faq_id] = new_row
            order.append(faq_id)

    return [by_id[i] for i in order if i in by_id]


def _parse_decisions(data: dict, candidates: list[dict[str, str]]) -> BatchResult:
    raw_list = data.get("decisions") or []
    decisions: list[Decision] = []
    if not isinstance(raw_list, list):
        raw_list = []

    seen_candidates: set[str] = set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        cid = (raw.get("candidate_faq_id") or "").strip()
        cls = (raw.get("classification") or "Review").strip()
        if cls not in VALID_CLASSIFICATIONS:
            cls = "Review"
        updated = raw.get("updated_record")
        if updated is not None and not isinstance(updated, dict):
            updated = None
        decisions.append(
            Decision(
                candidate_faq_id=cid,
                candidate_question=clean_faq_text(
                    raw.get("candidate_question") or ""
                ),
                classification=cls,
                matching_faq_id=(raw.get("matching_faq_id") or "").strip(),
                note=clean_faq_text(raw.get("note") or ""),
                provenance_source=clean_faq_text(raw.get("provenance_source") or ""),
                updated_record=updated,
            )
        )
        seen_candidates.add(cid)

    # Ensure every candidate got a decision
    for cand in candidates:
        if cand["FAQ_ID"] not in seen_candidates:
            decisions.append(
                Decision(
                    candidate_faq_id=cand["FAQ_ID"],
                    candidate_question=cand["Question"],
                    classification="Review",
                    matching_faq_id="",
                    note="Model omitted this candidate; flagged for human review.",
                    provenance_source=cand.get("Source") or "",
                    updated_record=None,
                )
            )

    privacy = data.get("existing_privacy_flags") or []
    flags: list[dict[str, str]] = []
    if isinstance(privacy, list):
        for item in privacy:
            if isinstance(item, dict):
                flags.append(
                    {
                        "faq_id": str(item.get("faq_id") or "").strip(),
                        "note": clean_faq_text(item.get("note") or ""),
                    }
                )
    change_log: dict[str, list[str]] = {}
    raw_log = data.get("change_log") or {}
    if isinstance(raw_log, dict):
        for key in ("new", "updated", "duplicates", "conflicts", "review_items"):
            val = raw_log.get(key) or []
            if isinstance(val, list):
                change_log[key] = [str(x).strip() for x in val if str(x).strip()]
    return BatchResult(
        label="",
        decisions=decisions,
        privacy_flags=flags,
        change_log=change_log,
    )


def reconcile_batch_llm(
    canonical: list[dict[str, str]],
    candidates: list[dict[str, str]],
    *,
    candidate_label: str,
    prior_notes: str = "",
    model: str | None = None,
) -> BatchResult:
    from openai import OpenAI

    from app.config import OPENAI_API_KEY, OPENAI_MODEL

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for FAQ reconciliation.")

    use_model = (model or OPENAI_MODEL or "gpt-4o-mini").strip()
    user = build_reconcile_user_prompt(
        canonical_rows=canonical,
        candidate_rows=candidates,
        candidate_label=candidate_label,
        prior_notes=prior_notes,
    )
    client = OpenAI(api_key=OPENAI_API_KEY)
    # Some models (e.g. gpt-5.6-luna) reject temperature=0; omit by default.
    kwargs = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": RECONCILER_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    resp = client.chat.completions.create(**kwargs)

    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Reconciler returned non-JSON: {raw[:400]}") from exc

    batch = _parse_decisions(data, candidates)
    batch.label = candidate_label
    usage = getattr(resp, "usage", None)
    if usage:
        logger.info(
            "Reconcile %s prompt=%s completion=%s decisions=%s",
            candidate_label,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            len(batch.decisions),
        )
    return batch


def format_report(
    batches: list[BatchResult],
    *,
    final_count: int,
) -> str:
    lines = [
        "# Combined FAQ reconciliation report",
        "",
        f"- Final canonical rows: {final_count}",
        f"- Batches applied: {len(batches)}",
        "",
    ]
    for batch in batches:
        lines.append(f"## Batch: {batch.label}")
        lines.append("")
        if batch.change_log:
            lines.append("### Change log")
            lines.append("")
            for key in ("new", "updated", "duplicates", "conflicts", "review_items"):
                items = batch.change_log.get(key) or []
                if not items:
                    continue
                lines.append(f"- **{key}**")
                for item in items:
                    lines.append(f"  - {item}")
            lines.append("")
        if not batch.decisions:
            lines.append("- (no decisions)")
            lines.append("")
            continue
        for dec in batch.decisions:
            lines.append(f"### {dec.candidate_faq_id or '(no id)'}")
            lines.append(f"- Question: {dec.candidate_question}")
            lines.append(f"- Classification: **{dec.classification}**")
            lines.append(f"- Matching existing FAQ_ID: `{dec.matching_faq_id or '(none)'}`")
            lines.append(f"- Provenance: {dec.provenance_source or '(n/a)'}")
            lines.append(f"- Note: {dec.note or '(none)'}")
            lines.append("")
        if batch.privacy_flags:
            lines.append("### Existing privacy flags")
            for flag in batch.privacy_flags:
                lines.append(f"- `{flag.get('faq_id')}`: {flag.get('note')}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def reconcile_candidates_sequential(
    candidate_csv_paths: list[Path],
    *,
    reset: bool = True,
    model: str | None = None,
    prior_notes: str = "",
    output_root: Path | None = None,
) -> tuple[Path, Path, list[dict[str, str]]]:
    """Start from empty (or existing) combined_FAQ; fold in each candidate CSV."""
    csv_path, report_path = combined_faq_paths(output_root)
    canonical = empty_canonical() if reset else read_faq_csv(csv_path)
    batches: list[BatchResult] = []
    notes = prior_notes

    for path in candidate_csv_paths:
        path = Path(path)
        candidates = read_faq_csv(path)
        if not candidates:
            logger.warning("No candidates in %s; skipping", path)
            continue
        label = path.parent.name if path.parent.name else path.stem
        logger.info(
            "Reconciling %s (%s candidates) into canonical (%s rows)",
            label,
            len(candidates),
            len(canonical),
        )
        batch = reconcile_batch_llm(
            canonical,
            candidates,
            candidate_label=label,
            prior_notes=notes,
            model=model,
        )
        canonical = apply_decisions(canonical, candidates, batch.decisions)
        batches.append(batch)
        # Checkpoint after each batch so a late write failure does not lose work.
        try:
            write_faq_csv(csv_path.with_name("combined_FAQ.partial.csv"), canonical)
        except Exception as exc:
            logger.warning("Partial checkpoint failed: %s", exc)
        # Carry forward a short running summary for next batch context
        summary_bits = [
            f"{d.candidate_faq_id}={d.classification}" for d in batch.decisions[:40]
        ]
        notes = (
            f"Prior batch {label}: {', '.join(summary_bits)}. "
            f"Canonical size now {len(canonical)}."
        )

    written = write_faq_csv(csv_path, canonical)
    try:
        report_path.write_text(
            format_report(batches, final_count=len(canonical)),
            encoding="utf-8",
            newline="\n",
        )
    except PermissionError:
        alt_report = report_path.with_name("combined_FAQ_Reconciliation_new.md")
        alt_report.write_text(
            format_report(batches, final_count=len(canonical)),
            encoding="utf-8",
            newline="\n",
        )
        report_path = alt_report
        logger.warning("Report locked; wrote %s", alt_report.name)
    # Drop partial once final write succeeded
    partial = csv_path.with_name("combined_FAQ.partial.csv")
    if partial.exists() and written.exists():
        try:
            partial.unlink()
        except OSError:
            pass
    logger.info("Wrote %s (%s rows) and %s", written, len(canonical), report_path)
    return written, report_path, canonical
