"""HTML → text must keep actionable hrefs attached to anchor text."""

from __future__ import annotations

from newsletter_archive.faq_llm import newsletter_plain_text
from newsletter_archive.html_text import html_to_text_preserve_links, link_markdown
from newsletter_archive.sections import html_to_sections


def test_link_markdown_basic():
    assert (
        link_markdown("order here", "https://out.smore.com/render/x")
        == "[order here](https://out.smore.com/render/x)"
    )


def test_html_to_text_preserve_links_inlines_href():
    html = (
        '<p><a href="https://out.smore.com/render/8035u/CQrKdW?__$u__">'
        "Check out today's student announcements to hear about a few of our clubs "
        "that are taking off soon</a>. The clubs features in this episode are "
        "Teachers of Tomorrow, Computer Science, Robotics, Chess, and ASL club.</p>"
    )
    text = html_to_text_preserve_links(html)
    assert "https://out.smore.com/render/8035u/CQrKdW?__$u__" in text
    assert "Teachers of Tomorrow" in text
    assert "[Check out today's student announcements" in text
    # URL must sit with the announcements sentence, not only as a bare orphan.
    assert "](https://out.smore.com/render/8035u/CQrKdW?__$u__)" in text


def test_newsletter_plain_text_uses_link_preserving_serializer():
    html = (
        '<html><body><p>Order at <a href="https://example.com/shop">Boomer Tees</a>.'
        "</p></body></html>"
    )
    text = newsletter_plain_text(html)
    assert "[Boomer Tees](https://example.com/shop)" in text


def test_html_to_sections_keeps_href_on_same_line_as_clubs():
    html = (
        "<html><body>"
        "<p>"
        '<a href="https://out.smore.com/render/8035u/CQrKdW?__$u__">'
        "Check out today's student announcements to hear about a few of our clubs "
        "that are taking off soon</a>. The clubs features in this episode are "
        "Teachers of Tomorrow, Computer Science, Robotics, Chess, and ASL club."
        "</p>"
        "</body></html>"
    )
    sections = html_to_sections(html)
    body = "\n".join(line for sec in sections for line in sec.body_lines)
    assert "Teachers of Tomorrow" in body
    assert "https://out.smore.com/render/8035u/CQrKdW?__$u__" in body
    # Prefer a single line that has both the URL and a club name (not detached).
    assert any(
        "CQrKdW" in line and "Teachers of Tomorrow" in line
        for sec in sections
        for line in sec.body_lines
    )
