from exercise_03 import (
    answer_from_faq,
    chunk_faq_text,
    load_faq,
    match_faq_qa,
    parse_faq_qa_pairs,
    retrieve_chunks,
)


def test_parse_pairs():
    pairs = parse_faq_qa_pairs(load_faq())
    assert any("park" in q.lower() for q, _ in pairs)
    assert any("grandparents" in q.lower() for q, _ in pairs)


def test_match_parking():
    ans = match_faq_qa("Where should I park?", load_faq())
    assert ans is not None
    assert "Lot C" in ans


def test_chunk_and_retrieve():
    chunks = chunk_faq_text(load_faq())
    assert len(chunks) >= 2
    top = retrieve_chunks("parking lot", chunks, top_k=1)
    assert top
    assert "Lot C" in top[0] or "park" in top[0].lower()


def test_answer_from_faq():
    ans = answer_from_faq("Can grandparents attend?")
    assert "sign in" in ans.lower() or "gym" in ans.lower()
