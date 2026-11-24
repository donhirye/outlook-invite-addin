import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

from app.config import FAQ_NOT_FOUND_MESSAGE, PARENT_FALLBACK_MESSAGE
from app import faq_service


def test_empty_question_returns_not_found(monkeypatch):
    monkeypatch.setattr(faq_service, "OPENAI_API_KEY", "test-key")
    assert faq_service.answer_faq_question("   ") == FAQ_NOT_FOUND_MESSAGE


def test_missing_api_key_returns_parent_fallback(monkeypatch):
    monkeypatch.setattr(faq_service, "OPENAI_API_KEY", "")
    answer = faq_service.answer_faq_question("Where should I park?")
    assert answer == PARENT_FALLBACK_MESSAGE


def test_answer_faq_question_uses_openai_response(monkeypatch, tmp_path):
    faq_file = tmp_path / "faq.txt"
    faq_file.write_text("Parking:\nParents should park in Lot C.\n", encoding="utf-8")

    class FakeResponse:
        output_text = (
            '{"answer":"Parents should park in Lot C.","confidence":0.91}'
        )

    class FakeResponses:
        def create(self, **kwargs):
            assert kwargs["model"] == "gpt-5.6-luna"
            assert kwargs.get("temperature", 0) == 0
            assert kwargs.get("reasoning") == {"effort": "minimal"}
            assert "TODAY'S DATE" in kwargs["instructions"]
            assert "TODAY'S DATE (America/Chicago): 2026-11-12" in kwargs["input"]
            assert "Lot C" in kwargs["input"]
            assert "Where should I park?" in kwargs["input"]
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key: str):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setattr(faq_service, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(faq_service, "OPENAI_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(
        faq_service,
        "load_faq_text",
        lambda faq_path=None: faq_file.read_text(encoding="utf-8").strip(),
    )
    monkeypatch.setattr(
        faq_service,
        "retrieve_chunks",
        lambda question, faq_text=None, faq_path=None: [
            "Parking:\nParents should park in Lot C."
        ],
    )
    monkeypatch.setattr(faq_service, "OpenAI", FakeClient)
    monkeypatch.setattr(faq_service, "score_faq_records", lambda question: (None, 0.2))
    monkeypatch.setattr(
        faq_service, "score_faq_qa", lambda question, faq_text: (None, 0.2)
    )
    monkeypatch.setattr(
        faq_service,
        "chicago_today",
        lambda: __import__("datetime").date(2026, 11, 12),
    )

    detailed = faq_service.answer_faq_detailed("Where should I park?")
    assert detailed.answer == "Parents should park in Lot C."
    assert detailed.confidence == 0.91
    assert detailed.match_score == 0.2
    assert detailed.llm_invocations == 1
    assert faq_service.answer_faq_question("Where should I park?") == (
        "Parents should park in Lot C."
    )


def test_direct_qa_match_returns_tomato():
    faq = (
        "SCIENCE OLYMPIAD — SAMPLE FAQ\n\n"
        "Parking:\nParents should park in Lot C.\n\n"
        "Q: Best flower in world\n"
        "A: tomato\n"
    )
    assert (
        faq_service.match_faq_qa("what is the best flower in the world", faq)
        == "tomato"
    )


def test_direct_qa_short_circuits_answer(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("OpenAI should not be called for direct Q/A matches")

    monkeypatch.setattr(faq_service, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(faq_service, "OpenAI", boom)
    monkeypatch.setattr(
        faq_service,
        "score_faq_records",
        lambda question: (
            {
                "faq_id": "T1",
                "question": "Best flower in world",
                "answer": "tomato",
                "source": "Test",
                "source_url": "",
            },
            0.99,
        ),
    )

    answer = faq_service.answer_faq_question("What is the best flower in the world?")
    assert answer == "tomato"


def test_needs_direct_qa_reshape_multi_date_dump():
    question = "When is 6th grade orchestra concert?"
    answer = (
        "The 6th grade band and orchestra concert is scheduled for Wednesday, "
        "December 2, 2026, at 7:00 PM. The first-semester holiday concert is "
        "scheduled for Tuesday, December 8, 2026; the evening BCO Honors Holiday "
        "Concert is at 7:00 PM."
    )
    assert faq_service.needs_direct_qa_reshape(question, answer) is True


def test_needs_direct_qa_reshape_skips_single_topic():
    question = "how do I order PE shirts?"
    answer = (
        "Beginning with the 2026-2027 school year, PE shirts are ordered from "
        "Boomer Tees and picked up directly from Boomer Tees."
    )
    assert faq_service.needs_direct_qa_reshape(question, answer) is False


def test_merge_timing_evidence_prefers_dated_over_undated_status(
    monkeypatch, tmp_path
):
    from app.faq_records import clear_faq_records_cache, upsert_record

    monkeypatch.setattr("app.faq_records.FAQ_RECORDS_FILE", tmp_path / "faq_records.json")
    monkeypatch.setattr("app.faq_records.FAQ_GCS_BUCKET", "")
    clear_faq_records_cache()
    upsert_record(
        {
            "faq_id": "REF-STATUS",
            "category": "Reflections art program",
            "question": "What is the current status of Crone's Reflections Art Program?",
            "answer": (
                "The screening process for entries in Crone's Reflections Art "
                "Program is underway. Results are awaited."
            ),
            "source": "Crone PTSA Newsletter - 2026-10-14",
            "status": "Active",
        }
    )
    upsert_record(
        {
            "faq_id": "REF-DEADLINE",
            "category": "Reflections submission",
            "question": "When and where must Reflections artwork be submitted?",
            "answer": (
                "Reflections artwork must be submitted to the Crone main office "
                "by Friday, October 9, 2026."
            ),
            "source": "Crone PTSA Newsletter - 2026-09-16",
            "event_date": "2026-10-09",
            "status": "Active",
        }
    )
    upsert_record(
        {
            "faq_id": "REF-ADVANCE",
            "category": "Reflections",
            "question": "What happened to the Crone entries in the Reflections program?",
            "answer": (
                "Entries from Crone were selected to advance to the district "
                "level of the Reflections program."
            ),
            "source": "Crone PTSA Newsletter - 2026-10-28",
            "published_date": "2026-10-28",
            "status": "Active",
        }
    )
    stale = (
        "Q: What is the current status of Crone's Reflections Art Program?\n"
        "A: The screening process is underway. Results are awaited."
    )
    chunks, best = faq_service.merge_timing_evidence_chunks(
        "is the reflections competition over?",
        [stale],
    )
    assert best is not None
    assert best.get("faq_id") == "REF-DEADLINE"
    assert "October 9, 2026" in chunks[0]
    assert any("advance to the district" in c for c in chunks)
    assert faq_service._chunk_looks_undated_status(stale)
    assert all(not faq_service._chunk_looks_undated_status(c) for c in chunks)


def test_timing_ask_seeds_dated_evidence_into_llm(monkeypatch, tmp_path):
    from app.faq_records import clear_faq_records_cache, upsert_record

    monkeypatch.setattr("app.faq_records.FAQ_RECORDS_FILE", tmp_path / "faq_records.json")
    monkeypatch.setattr("app.faq_records.FAQ_GCS_BUCKET", "")
    clear_faq_records_cache()
    upsert_record(
        {
            "faq_id": "REF-STATUS",
            "category": "Reflections",
            "question": "What is the current status of Crone's Reflections Art Program?",
            "answer": (
                "The screening process for entries is underway. "
                "The newsletter says results are awaited."
            ),
            "source": "Crone PTSA – Frequently Asked Questions",
            "status": "Active",
        }
    )
    upsert_record(
        {
            "faq_id": "REF-DEADLINE",
            "category": "Reflections",
            "question": "When and where must Reflections artwork be submitted?",
            "answer": (
                "Reflections artwork must be submitted by Friday, October 9, 2026."
            ),
            "source": "Crone PTSA Newsletter - 2026-09-16",
            "event_date": "2026-10-09",
            "status": "Active",
        }
    )

    class FakeResponse:
        output_text = (
            '{"answer":"Yes — Reflections submissions were due October 9, 2026, '
            'so that phase is over.","confidence":0.92}'
        )
        usage = type("U", (), {"input_tokens": 80, "output_tokens": 30})()

    seen: dict = {}

    class FakeResponses:
        def create(self, **kwargs):
            seen["input"] = kwargs["input"]
            seen["instructions"] = kwargs["instructions"]
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key: str):
            self.responses = FakeResponses()

    monkeypatch.setattr(faq_service, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(faq_service, "OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(faq_service, "OpenAI", FakeClient)
    monkeypatch.setattr(faq_service, "load_faq_text", lambda faq_path=None: "faq")
    monkeypatch.setattr(
        faq_service,
        "retrieve_chunks",
        lambda question, faq_text=None, faq_path=None: [
            "Q: What is the current status of Crone's Reflections Art Program?\n"
            "A: The screening process is underway. Results are awaited."
        ],
    )
    monkeypatch.setattr(
        faq_service,
        "chicago_today",
        lambda: __import__("datetime").date(2026, 11, 24),
    )

    detailed = faq_service.answer_faq_detailed(
        "is the reflections competition over?"
    )
    assert "October 9, 2026" in seen["input"]
    assert "Prefer FAQ excerpts with concrete dates" in seen["instructions"]
    assert "briefly cite the key phase dates" in seen["instructions"]
    # Undated status blurb must not lead the excerpts when dated evidence exists.
    first_excerpt = seen["input"].split("FAQ EXCERPTS:\n", 1)[1].split("\n\n---\n\n")[0]
    assert "October 9, 2026" in first_excerpt
    assert "underway" not in first_excerpt.lower()
    assert "over" in detailed.answer.lower()
    assert detailed.faq_id == "REF-DEADLINE"
    assert detailed.source_name == "Crone PTSA Newsletter - 2026-09-16"


def test_direct_qa_reshape_runs_when_gated(monkeypatch):
    multi = (
        "The 6th grade band and orchestra concert is scheduled for Wednesday, "
        "December 2, 2026, at 7:00 PM. The first-semester holiday concert is "
        "scheduled for Tuesday, December 8, 2026."
    )

    class FakeResponse:
        output_text = (
            "The 6th grade band and orchestra concert is scheduled for "
            "Wednesday, December 2, 2026, at 7:00 PM."
        )
        usage = type("U", (), {"input_tokens": 40, "output_tokens": 20})()

    class FakeResponses:
        def create(self, **kwargs):
            assert "trim a matched FAQ answer" in kwargs["instructions"]
            assert "December 8" in kwargs["input"]
            assert "6th grade orchestra" in kwargs["input"].lower()
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key: str):
            self.responses = FakeResponses()

    monkeypatch.setattr(faq_service, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(faq_service, "OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(faq_service, "OpenAI", FakeClient)
    monkeypatch.setattr(faq_service, "load_faq_text", lambda faq_path=None: "x")
    monkeypatch.setattr(
        faq_service,
        "score_faq_records",
        lambda question: (
            {
                "faq_id": "MUSIC-1",
                "question": "What upcoming Crone music events are scheduled?",
                "answer": multi,
                "source": "Crone's Weekly Newsletter - 2026-11-13",
                "source_url": "",
            },
            0.9,
        ),
    )

    detailed = faq_service.answer_faq_detailed(
        "When is 6th grade orchestra concert?"
    )
    assert detailed.retrieval_mode == "direct_qa_reshaped"
    assert detailed.llm_invocations == 1
    assert "December 2, 2026" in detailed.answer
    assert "December 8" not in detailed.answer
    assert detailed.faq_id == "MUSIC-1"


def test_llm_answer_strips_invented_source_and_uses_file_source(monkeypatch):
    faq = (
        "Q: When is the Springfield trip?\n"
        "A: May 29–30, 2027.\n"
        "(Source: Crone PTSA Newsletter – Nov 2026; "
        "URL: https://example.com/newsletter)\n"
    )

    class FakeResponse:
        output_text = (
            '{"answer":"The trip is May 29–30, 2027.\\n\\n'
            'Source: Crone PTSA FAQ","confidence":0.9}'
        )

    class FakeResponses:
        def create(self, **kwargs):
            assert 'Do NOT add a "Source:" line' in kwargs["instructions"]
            assert "TODAY'S DATE (America/Chicago): 2026-11-12" in kwargs["input"]
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key: str):
            self.responses = FakeResponses()

    monkeypatch.setattr(faq_service, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(faq_service, "OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(faq_service, "load_faq_text", lambda faq_path=None: faq)
    monkeypatch.setattr(
        faq_service,
        "retrieve_chunks",
        lambda question, faq_text=None, faq_path=None: [faq],
    )
    monkeypatch.setattr(faq_service, "OpenAI", FakeClient)
    monkeypatch.setattr(faq_service, "score_faq_records", lambda question: (None, 0.2))
    monkeypatch.setattr(faq_service, "_best_faq_record", lambda question: (None, 0.2))
    monkeypatch.setattr(
        faq_service,
        "chicago_today",
        lambda: __import__("datetime").date(2026, 11, 12),
    )

    detailed = faq_service.answer_faq_detailed("When is the Springfield trip?")
    assert "Crone PTSA FAQ" not in detailed.answer
    assert detailed.answer == "The trip is May 29–30, 2027."
    assert detailed.source_name == "Crone PTSA Newsletter – Nov 2026"
    assert detailed.source_url == "https://example.com/newsletter"


def test_resolve_source_prefers_excerpt():
    faq = (
        "Q: A?\nA: 1\n(Source: Whole File Source)\n\n"
        "Q: B?\nA: 2\n(Source: Excerpt Source; URL: https://ex.ample/b)\n"
    )
    name, url = faq_service.resolve_source(faq, excerpts="(Source: Excerpt Source; URL: https://ex.ample/b)")
    assert name == "Excerpt Source"
    assert url == "https://ex.ample/b"
