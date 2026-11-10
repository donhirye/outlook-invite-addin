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
            assert "ONLY the FAQ excerpts" in kwargs["instructions"]
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
