import os

os.environ.setdefault("ADMIN_PASSWORD", "changeme")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
os.environ["FAQ_GCS_BUCKET"] = ""

from app.config import STUDENT_PRIVACY_MESSAGE
from app.privacy_filter import looks_like_student_pii_request, privacy_reply_if_needed


def test_blocks_student_id_lookup():
    assert looks_like_student_pii_request("What is the student ID for Jordan Lee?")
    assert privacy_reply_if_needed("look up student id for my child") == (
        STUDENT_PRIVACY_MESSAGE
    )


def test_blocks_student_phone_and_email():
    assert looks_like_student_pii_request("What is the student phone number?")
    assert looks_like_student_pii_request("Can you give me a student's email address?")
    assert looks_like_student_pii_request("student named Avery phone number")


def test_allows_general_student_id_cost_faq():
    # Process/cost FAQs must not trip the privacy gate.
    assert not looks_like_student_pii_request(
        "How much does a replacement student ID cost?"
    )
    assert privacy_reply_if_needed("Can my child buy lunch without a student ID?") is None


def test_allows_normal_parent_questions():
    assert not looks_like_student_pii_request("When is winter break?")
    assert not looks_like_student_pii_request("Where is Lost & Found?")
