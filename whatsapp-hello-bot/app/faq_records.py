"""Structured FAQ records (CSV import, durable JSON + optional GCS)."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from app.config import BASE_DIR, FAQ_GCS_BUCKET

logger = logging.getLogger(__name__)

CHICAGO = ZoneInfo("America/Chicago")
FAQ_RECORDS_FILE = BASE_DIR / "data" / "faq_records.json"
FAQ_RECORDS_GCS_OBJECT = "faq_records.json"
FAQ_IMPORT_SEED = BASE_DIR / "data" / "imports" / "Crone_Combined_FAQs_Admin_Import.csv"
_lock = Lock()
_cache: dict[str, Any] | None = None


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def chicago_today() -> date:
    return datetime.now(CHICAGO).date()


def _empty() -> dict[str, Any]:
    return {"records": {}, "updated_at": None, "conflicts": []}


def _load_raw() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    data = _empty()
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(FAQ_RECORDS_GCS_OBJECT)
            if blob.exists():
                loaded = json.loads(blob.download_as_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("records"), dict):
                    data = {**_empty(), **loaded}
                    _cache = data
                    return data
        except Exception:
            logger.exception("Failed reading FAQ records from GCS")
    if FAQ_RECORDS_FILE.exists():
        try:
            loaded = json.loads(FAQ_RECORDS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("records"), dict):
                data = {**_empty(), **loaded}
        except Exception:
            logger.exception("Failed reading %s", FAQ_RECORDS_FILE)
    _cache = data
    return data


def _save(data: dict[str, Any]) -> None:
    global _cache
    data["updated_at"] = datetime.now(CHICAGO).isoformat()
    FAQ_RECORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    FAQ_RECORDS_FILE.write_text(text, encoding="utf-8")
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(FAQ_RECORDS_GCS_OBJECT)
            blob.upload_from_string(text, content_type="application/json")
        except Exception:
            logger.exception("Failed writing FAQ records to GCS")
    _cache = data
    try:
        from app.faq_store import clear_faq_cache, set_faq_text

        clear_faq_cache()
        set_faq_text(records_to_faq_text(list_records(include_inactive=False)))
    except Exception:
        logger.exception("Failed syncing legacy FAQ text after records save")


def clear_faq_records_cache() -> None:
    global _cache
    _cache = None


def normalize_record(row: dict[str, Any]) -> dict[str, Any] | None:
    faq_id = str(row.get("FAQ_ID") or row.get("faq_id") or "").strip()
    question = str(row.get("Question") or row.get("question") or "").strip()
    answer = str(row.get("Answer") or row.get("answer") or "").strip()
    if not faq_id or not question or not answer:
        return None
    return {
        "faq_id": faq_id,
        "category": str(row.get("Category") or row.get("category") or "").strip(),
        "question": question,
        "answer": answer,
        "source": str(row.get("Source") or row.get("source") or "").strip(),
        "source_url": str(row.get("Source_URL") or row.get("source_url") or "").strip(),
        "published_date": str(
            row.get("Published_Date") or row.get("published_date") or ""
        ).strip(),
        "event_date": str(row.get("Event_Date") or row.get("event_date") or "").strip(),
        "status": str(row.get("Status") or row.get("status") or "Active").strip()
        or "Active",
    }


def parse_faq_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, Any]] = []
    for row in reader:
        rec = normalize_record(row or {})
        if rec:
            out.append(rec)
    return out


def import_faq_csv_text(text: str) -> dict[str, Any]:
    rows = parse_faq_csv(text)
    with _lock:
        data = _load_raw()
        records = dict(data.get("records") or {})
        for rec in rows:
            records[rec["faq_id"]] = rec
        data["records"] = records
        data["conflicts"] = detect_conflicts(list(records.values()))
        _save(data)
    return {
        "imported": len(rows),
        "total": len(list_records(include_inactive=True)),
        "conflicts": data.get("conflicts") or [],
    }


def import_faq_csv_file(path: Path | None = None) -> dict[str, Any]:
    path = path or FAQ_IMPORT_SEED
    return import_faq_csv_text(path.read_text(encoding="utf-8-sig"))


def ensure_faq_records_seeded() -> dict[str, Any]:
    data = _load_raw()
    if data.get("records"):
        return {"seeded": False, "total": len(data["records"])}
    if FAQ_IMPORT_SEED.exists():
        result = import_faq_csv_file(FAQ_IMPORT_SEED)
        return {"seeded": True, **result}
    return {"seeded": False, "total": 0}


def list_records(*, include_inactive: bool = True) -> list[dict[str, Any]]:
    ensure_faq_records_seeded()
    records = list((_load_raw().get("records") or {}).values())
    if not include_inactive:
        records = [r for r in records if str(r.get("status", "")).lower() == "active"]
    records.sort(key=lambda r: (r.get("category") or "", r.get("faq_id") or ""))
    return records


def get_record(faq_id: str) -> dict[str, Any] | None:
    ensure_faq_records_seeded()
    return (_load_raw().get("records") or {}).get(faq_id)


def upsert_record(record: dict[str, Any]) -> dict[str, Any]:
    rec = normalize_record(record)
    if not rec:
        raise ValueError("FAQ record requires FAQ_ID, Question, and Answer")
    with _lock:
        data = _load_raw()
        records = dict(data.get("records") or {})
        records[rec["faq_id"]] = rec
        data["records"] = records
        data["conflicts"] = detect_conflicts(list(records.values()))
        _save(data)
    return rec


def records_to_faq_text(records: list[dict[str, Any]]) -> str:
    lines = [
        "Crone Middle School PTSA — Parent FAQ",
        "Authoritative FAQ records imported for the WhatsApp bot.",
        "",
    ]
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_cat.setdefault(rec.get("category") or "General", []).append(rec)
    for cat in sorted(by_cat):
        lines.append(f"## {cat}")
        lines.append("")
        for rec in by_cat[cat]:
            lines.append(f"Q: {rec['question']}")
            lines.append(f"A: {rec['answer']}")
            meta = []
            if rec.get("source"):
                meta.append(f"Source: {rec['source']}")
            if rec.get("source_url"):
                meta.append(f"URL: {rec['source_url']}")
            if rec.get("event_date"):
                meta.append(f"Event_Date: {rec['event_date']}")
            if meta:
                lines.append("(" + "; ".join(meta) + ")")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _parse_event_date(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def detect_conflicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag near-duplicate questions with differing answers for admin review."""
    conflicts: list[dict[str, Any]] = []
    active = [r for r in records if str(r.get("status", "")).lower() == "active"]
    for i, a in enumerate(active):
        qa = re.sub(r"[^a-z0-9\s]+", " ", (a.get("question") or "").lower())
        ta = {t for t in qa.split() if len(t) > 2}
        if not ta:
            continue
        for b in active[i + 1 :]:
            qb = re.sub(r"[^a-z0-9\s]+", " ", (b.get("question") or "").lower())
            tb = {t for t in qb.split() if len(t) > 2}
            if not tb:
                continue
            overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
            if overlap >= 0.7 and (a.get("answer") or "").strip() != (
                b.get("answer") or ""
            ).strip():
                conflicts.append(
                    {
                        "faq_ids": [a["faq_id"], b["faq_id"]],
                        "overlap": round(overlap, 3),
                        "questions": [a["question"], b["question"]],
                    }
                )
    return conflicts


def get_conflicts() -> list[dict[str, Any]]:
    ensure_faq_records_seeded()
    return list((_load_raw().get("conflicts") or []))
