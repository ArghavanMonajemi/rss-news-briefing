import pytest
from rss_news_briefing.prompt import build_articles_xml


def test_empty_list_gives_a_valid_wrapper():
    assert build_articles_xml([]) == "<articles>\n</articles>"


@pytest.mark.parametrize(
    "raw, escaped",
    [
        ("Tom & Jerry", "Tom &amp; Jerry"),
        ("<script>", "&lt;script&gt;"),
        ("a > b", "a &gt; b"),
    ],
)
def test_special_characters_are_escaped_in_every_text_field(make_article, raw, escaped):
    article = make_article(title=raw, summary=raw, text=raw, source=raw)

    xml = build_articles_xml([article])

    assert raw not in xml
    # title, summary, text and source
    assert xml.count(escaped) == 4


def test_text_is_truncated_to_max_chars(make_article):
    article = make_article(text="x" * 100)

    xml = build_articles_xml([article], max_chars=10)

    assert "<text>" + "x" * 10 + "</text>" in xml


def test_text_is_truncated_before_escaping(make_article):
    # If escaping happened first, the cut could split an entity like "&amp;".
    article = make_article(text="&" * 5)

    xml = build_articles_xml([article], max_chars=2)

    assert "<text>&amp;&amp;</text>" in xml


def test_ids_are_sequential_from_zero(make_article):
    articles = [make_article(link=f"https://example.com/{i}") for i in range(3)]

    xml = build_articles_xml(articles)

    assert all(f"<id>{i}</id>" in xml for i in range(3))
    assert "<id>3</id>" not in xml


def test_every_article_field_is_present(make_article):
    article = make_article(
        title="Big news",
        link="https://example.com/big",
        source="Example Feed",
        published="Mon, 26 Oct 2026 10:00:00 GMT",
        summary="Short summary",
        text="Long text",
    )

    xml = build_articles_xml([article])

    assert "<title>Big news</title>" in xml
    assert "<link>https://example.com/big</link>" in xml
    assert "<source>Example Feed</source>" in xml
    assert "<published>Mon, 26 Oct 2026 10:00:00 GMT</published>" in xml
    assert "<summary>Short summary</summary>" in xml
    assert "<text>Long text</text>" in xml
