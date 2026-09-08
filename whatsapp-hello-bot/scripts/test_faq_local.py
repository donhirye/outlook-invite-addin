"""Local FAQ smoke test (no WhatsApp).

Usage (from whatsapp-hello-bot/ with venv active):

    python scripts/test_faq_local.py
    python scripts/test_faq_local.py "Where should I park?"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.faq_service import answer_faq_question


DEFAULT_QUESTIONS = [
    "Where should I park?",
    "What time does my kid need to get there?",
    "Can grandparents attend?",
    "Who won the Super Bowl?",
]


def main() -> None:
    questions = sys.argv[1:] or DEFAULT_QUESTIONS
    for question in questions:
        print(f"Question:\n{question}")
        answer = answer_faq_question(question)
        print(f"Answer:\n{answer}\n")


if __name__ == "__main__":
    main()
