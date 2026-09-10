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
        output_text = "Parents should park in Lot C."

    class FakeResponses:
        def create(self, **kwargs):
            assert kwargs["model"] == "gpt-5.6-luna"
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

    answer = faq_service.answer_faq_question("Where should I park?")
    assert answer == "Parents should park in Lot C."
