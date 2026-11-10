"""School calendar durable store + CSV import."""

from __future__ import annotations

import csv
import hashlib
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
CALENDAR_FILE = BASE_DIR / "data" / "school_calendar.json"
CALENDAR_GCS_OBJECT = "school_calendar.json"
CALENDAR_IMPORT_SEED = (
    BASE_DIR / "data" / "imports" / "school_district_204_2026_2027_calendar.csv"
)
DEFAULT_SOURCE_NAME = "School District 204 2026–2027 Calendar"
DEFAULT_SOURCE_URL = (
    "https://resources.finalsite.net/images/v1785767151/ipsdorg/"
    "kdopbpymlg03ffqsaxpf/SchoolCalendar2026-2027FINAL.pdf"
)
_lock = Lock()
_cache: dict[str, Any] | None = None


def _gcs_enabled() -> bool:
    return bool(FAQ_GCS_BUCKET)


def _empty() -> dict[str, Any]:
    return {
        "calendar_name": DEFAULT_SOURCE_NAME,
        "source_name": DEFAULT_SOURCE_NAME,
        "source_url": DEFAULT_SOURCE_URL,
        "school_year": "2026-2027",
        "events": {},
        "updated_at": None,
    }


def clear_calendar_cache() -> None:
    global _cache
    _cache = None


def _load_raw() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    data = _empty()
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(CALENDAR_GCS_OBJECT)
            if blob.exists():
                loaded = json.loads(blob.download_as_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = {**_empty(), **loaded}
                    if not isinstance(data.get("events"), dict):
                        data["events"] = {}
                    _cache = data
                    return data
        except Exception:
            logger.exception("Failed reading school calendar from GCS")
    if CALENDAR_FILE.exists():
        try:
            loaded = json.loads(CALENDAR_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = {**_empty(), **loaded}
                if not isinstance(data.get("events"), dict):
                    data["events"] = {}
        except Exception:
            logger.exception("Failed reading %s", CALENDAR_FILE)
    _cache = data
    return data


def _save(data: dict[str, Any]) -> None:
    global _cache
    data["updated_at"] = datetime.now(CHICAGO).isoformat()
    CALENDAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    CALENDAR_FILE.write_text(text, encoding="utf-8")
    if _gcs_enabled():
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(FAQ_GCS_BUCKET).blob(CALENDAR_GCS_OBJECT)
            blob.upload_from_string(text, content_type="application/json")
        except Exception:
            logger.exception("Failed writing school calendar to GCS")
    _cache = data


def event_id_for(start: str, end: str, name: str) -> str:
    raw = f"{start}|{end}|{name}".strip().lower()
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "event"
    return f"{slug}-{start}-{digest}"


def normalize_event(row: dict[str, Any]) -> dict[str, Any] | None:
    name = str(row.get("Event") or row.get("event_name") or row.get("name") or "").strip()
    start = str(row.get("Start Date") or row.get("start_date") or "").strip()
    end = str(row.get("End Date") or row.get("end_date") or start).strip()
    if not name or not start:
        return None
    eid = str(row.get("event_id") or "").strip() or event_id_for(start, end, name)
    return {
        "event_id": eid,
        "calendar_name": str(
            row.get("Calendar Name") or row.get("calendar_name") or DEFAULT_SOURCE_NAME
        ).strip(),
        "name": name,
        "start_date": start,
        "end_date": end,
        "event_type": str(row.get("Type") or row.get("event_type") or "").strip(),
        "student_attendance": str(
            row.get("Student Attendance") or row.get("student_attendance") or ""
        ).strip(),
        "source_name": str(
            row.get("Source Name") or row.get("source_name") or DEFAULT_SOURCE_NAME
        ).strip(),
        "source_url": str(
            row.get("Source URL") or row.get("source_url") or DEFAULT_SOURCE_URL
        ).strip(),
        "notes": str(row.get("Notes") or row.get("notes") or "").strip(),
    }


def parse_calendar_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, Any]] = []
    for row in reader:
        ev = normalize_event(row or {})
        if ev:
            out.append(ev)
    return out


def import_calendar_csv_text(text: str) -> dict[str, Any]:
    rows = parse_calendar_csv(text)
    with _lock:
        data = _load_raw()
        events = dict(data.get("events") or {})
        for ev in rows:
            events[ev["event_id"]] = ev
            if ev.get("calendar_name"):
                data["calendar_name"] = ev["calendar_name"]
            if ev.get("source_name"):
                data["source_name"] = ev["source_name"]
            if ev.get("source_url"):
                data["source_url"] = ev["source_url"]
        data["events"] = events
        _save(data)
    return {"imported": len(rows), "total": len(list_events())}


def import_calendar_csv_file(path: Path | None = None) -> dict[str, Any]:
    path = path or CALENDAR_IMPORT_SEED
    return import_calendar_csv_text(path.read_text(encoding="utf-8-sig"))


def ensure_calendar_seeded() -> dict[str, Any]:
    data = _load_raw()
    if data.get("events"):
        return {"seeded": False, "total": len(data["events"])}
    if CALENDAR_IMPORT_SEED.exists():
        result = import_calendar_csv_file(CALENDAR_IMPORT_SEED)
        return {"seeded": True, **result}
    return {"seeded": False, "total": 0}


def list_events() -> list[dict[str, Any]]:
    ensure_calendar_seeded()
    events = list((_load_raw().get("events") or {}).values())
    events.sort(key=lambda e: (e.get("start_date") or "", e.get("name") or ""))
    return events


def get_calendar_meta() -> dict[str, Any]:
    ensure_calendar_seeded()
    data = _load_raw()
    return {
        "calendar_name": data.get("calendar_name"),
        "source_name": data.get("source_name") or DEFAULT_SOURCE_NAME,
        "source_url": data.get("source_url") or DEFAULT_SOURCE_URL,
        "school_year": data.get("school_year") or "2026-2027",
        "updated_at": data.get("updated_at"),
        "event_count": len(data.get("events") or {}),
    }


def upsert_event(event: dict[str, Any]) -> dict[str, Any]:
    ev = normalize_event(event)
    if not ev:
        raise ValueError("Calendar event requires name and start date")
    with _lock:
        data = _load_raw()
        events = dict(data.get("events") or {})
        events[ev["event_id"]] = ev
        data["events"] = events
        _save(data)
    return ev


def parse_iso_date(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None
