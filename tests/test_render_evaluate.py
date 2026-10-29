from datetime import UTC, datetime

from rss_news_briefing import evaluate
from rss_news_briefing.pipeline import BriefingResult, NoArticlesError
from rss_news_briefing.render import render_text

# --- render_text --------------------------------------------------------


def test_rendered_text_contains_every_part_of_the_briefing(make_briefing):
    briefing = make_briefing(
        overview="A busy day.",
        themes=[
            {
                "title": "Tech",
                "bullets": [
                    {
                        "text": "A chip launched.",
                        "sources": ["https://example.com/a", "https://example.com/b"],
                    }
                ],
            }
        ],
        worth_watching="The vote on Friday.",
    )

    text = render_text(briefing)

    assert "A busy day." in text
    assert "Tech" in text
    assert "- A chip launched." in text
    assert "https://example.com/a, https://example.com/b" in text
    assert "Worth watching: The vote on Friday." in text


def test_rendered_themes_keep_their_order(make_briefing):
    bullet = [{"text": "x", "sources": ["https://example.com/a"]}]
    briefing = make_briefing(
        themes=[
            {"title": "First theme", "bullets": bullet},
            {"title": "Second theme", "bullets": bullet},
        ]
    )

    text = render_text(briefing)

    assert text.index("First theme") < text.index("Second theme")


# --- the evaluate script ------------------------------------------------


def make_result(briefing, input_links):
    return BriefingResult(
        briefing=briefing,
        article_count=len(input_links),
        sources=["Test Feed"],
        usage=None,
        cache_hits=0,
        cache_misses=0,
        generated_at=datetime(2026, 10, 28, tzinfo=UTC),
        input_links=input_links,
    )


def test_exit_code_0_when_every_cited_link_was_in_the_input(
    monkeypatch, capsys, make_briefing
):
    result = make_result(make_briefing(), ["https://example.com/a"])
    monkeypatch.setattr(evaluate, "generate_briefing", lambda: result)

    code = evaluate.main()

    assert code == 0
    assert "PASS" in capsys.readouterr().out


def test_exit_code_1_and_the_link_is_printed_when_a_link_was_invented(
    monkeypatch, capsys, make_briefing
):
    result = make_result(make_briefing(), ["https://example.com/other"])
    monkeypatch.setattr(evaluate, "generate_briefing", lambda: result)

    code = evaluate.main()

    output = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in output
    assert "https://example.com/a" in output  # the default bullet's source


def test_exit_code_2_when_there_were_no_articles(monkeypatch, capsys):
    def no_articles():
        raise NoArticlesError("No articles found in any feed.")

    monkeypatch.setattr(evaluate, "generate_briefing", no_articles)

    code = evaluate.main()

    assert code == 2
    assert "No articles" in capsys.readouterr().out
