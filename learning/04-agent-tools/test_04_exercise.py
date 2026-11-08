from exercise_04 import parse_faq_command, route_message


def test_route_help():
    assert route_message("HELP")["action"] == "help"


def test_route_opener():
    assert route_message("hi")["action"] == "greeting"
    assert (
        route_message("Hi, I have a question about Kendall")["action"] == "greeting"
    )


def test_route_faq_admin_denied():
    assert (
        route_message("/faq Q: x A: y", sender_is_admin=False)["action"]
        == "faq_admin_denied"
    )


def test_route_faq_admin_ok():
    msg = "/faq Q: Can grandparents attend? A: Yes, sign in at gym."
    out = route_message(msg, sender_is_admin=True)
    assert out["action"] == "faq_admin"
    assert "grandparents" in out["question"].lower()
    assert "gym" in out["answer"].lower()


def test_route_normal_question():
    out = route_message("Where should I park?")
    assert out == {"action": "faq_answer", "question": "Where should I park?"}


def test_parse_faq_command():
    parsed = parse_faq_command("/faq Q: Best flower? A: tomato")
    assert parsed == ("Best flower?", "tomato")
