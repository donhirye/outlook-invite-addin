from app.engines.base import AnswerResult
from app.observability.tracing import derive_answer_outcome


def test_faq_not_found_is_unanswered():
    result = AnswerResult(
        messages=[
            "I couldn't find that information in the event FAQ. "
            "Please contact the PTSA Administrators."
        ],
        route="faq",
        fallback="faq_not_found",
        answer_outcome="unanswered",
    )
    assert derive_answer_outcome(result) == "unanswered"


def test_faq_hit_is_answered():
    result = AnswerResult(
        messages=["Crone has two Lost & Found locations."],
        route="faq",
        answer_outcome="answered",
    )
    assert derive_answer_outcome(result) == "answered"


def test_error_outcome():
    result = AnswerResult(
        messages=["Sorry, I'm having trouble answering right now."],
        route="error",
        error="boom",
        fallback="exception",
    )
    assert derive_answer_outcome(result) == "error"
