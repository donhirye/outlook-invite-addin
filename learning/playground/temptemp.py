"""Local scratch pad (learning only).

Original file preserved as temptemp.py.original.

IMPORTANT: never print API keys. The original scratch file did
`print(os.getenv("OPENAI_API_KEY"))` — that is unsafe.
"""

from __future__ import annotations

from pathlib import Path

LEARNING_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FAQ = LEARNING_ROOT / "data" / "sample_faq.txt"


def main() -> None:
    # TODO (you): call your completed FAQ helper once exercise 03 is done.
    # Example idea:
    #   from importlib.machinery import SourceFileLoader
    #   ...
    print("Learning scratch pad")
    print("Sample FAQ exists:", SAMPLE_FAQ.exists())
    print("FAQ preview:")
    print(SAMPLE_FAQ.read_text(encoding="utf-8")[:160], "...")


if __name__ == "__main__":
    main()
