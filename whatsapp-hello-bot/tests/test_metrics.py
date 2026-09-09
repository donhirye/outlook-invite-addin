from app.metrics import get_metrics, record_question


def test_record_question_counts_and_unique_users(tmp_path):
    metrics_file = tmp_path / "usage_metrics.json"

    first = record_question("15551110001", e2e_ms=120.4, path=metrics_file)
    assert first["questions_asked"] == 1
    assert first["unique_users"] == 1
    assert first["last_e2e_ms"] == 120.4

    second = record_question("15551110001", e2e_ms=90.0, path=metrics_file)
    assert second["questions_asked"] == 2
    assert second["unique_users"] == 1

    third = record_question("15551110002", e2e_ms=80.0, path=metrics_file)
    assert third["questions_asked"] == 3
    assert third["unique_users"] == 2

    snapshot = get_metrics(path=metrics_file)
    assert snapshot == {
        "questions_asked": 3,
        "unique_users": 2,
        "last_e2e_ms": 80.0,
        "last_faq_total_ms": None,
    }
