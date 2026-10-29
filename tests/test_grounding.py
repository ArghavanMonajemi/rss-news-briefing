import pytest

from rss_news_briefing.grounding import (
    check_briefing,
    cited_urls,
    find_uncited_links,
    find_unknown_sources,
    format_report,
    normalize_url,
)


def citing(make_briefing, *urls):
    """A briefing with one bullet per URL (at most 4 bullets per theme)."""
    bullets = [{"text": f"Bullet {i}.", "sources": [url]} for i, url in enumerate(urls)]
    themes = [
        {"title": f"Theme {n}", "bullets": bullets[start : start + 4]}
        for n, start in enumerate(range(0, len(bullets), 4))
    ]
    return make_briefing(themes=themes)


# --- normalize_url ------------------------------------------------------


@pytest.mark.parametrize(
    "first, second",
    [
        ("https://example.com/a", "https://example.com/a/"),
        ("https://example.com/a", "HTTPS://Example.COM/a"),
        ("https://example.com/a", "https://example.com/a#section"),
        ("https://example.com/a", "  https://example.com/a  "),
        ("https://example.com/a?x=1&y=2", "https://example.com/a?x=1&amp;y=2"),
        ("https://example.com", "https://example.com/"),
    ],
)
def test_harmless_differences_are_ignored(first, second):
    assert normalize_url(first) == normalize_url(second)


@pytest.mark.parametrize(
    "first, second",
    [
        ("https://example.com/a", "https://example.com/b"),
        ("https://example.com/a", "https://example.com/A"),
        ("https://example.com/a?x=1", "https://example.com/a?x=2"),
        ("https://example.com/a", "http://example.com/a"),
        ("https://example.com/a", "https://example.org/a"),
        ("https://example.com/news/a", "https://example.com/a"),
    ],
)
def test_real_differences_are_kept(first, second):
    assert normalize_url(first) != normalize_url(second)


# --- cited_urls ---------------------------------------------------------


def test_cited_urls_are_unique_and_in_order_of_first_appearance(make_briefing):
    briefing = citing(
        make_briefing,
        "https://example.com/b",
        "https://example.com/a",
        "https://example.com/b/",  # same link, different spelling
    )

    assert cited_urls(briefing) == ["https://example.com/b", "https://example.com/a"]


def test_a_bullet_can_cite_several_sources(make_briefing):
    briefing = make_briefing(
        themes=[
            {
                "title": "Theme",
                "bullets": [
                    {
                        "text": "Two sources.",
                        "sources": ["https://example.com/a", "https://example.com/b"],
                    }
                ],
            }
        ]
    )

    assert cited_urls(briefing) == ["https://example.com/a", "https://example.com/b"]


# --- find_unknown_sources -----------------------------------------------


def test_no_unknown_sources_when_everything_cited_was_in_the_input(make_briefing):
    briefing = citing(make_briefing, "https://example.com/a", "https://example.com/b")

    unknown = find_unknown_sources(
        briefing, ["https://example.com/a", "https://example.com/b", "https://x.com"]
    )

    assert unknown == []


def test_a_url_that_was_not_in_the_input_is_reported(make_briefing):
    briefing = citing(
        make_briefing, "https://example.com/a", "https://made-up.example/z"
    )

    unknown = find_unknown_sources(briefing, ["https://example.com/a"])

    assert unknown == ["https://made-up.example/z"]


def test_a_slightly_altered_url_is_still_reported(make_briefing):
    # A model that "fixes" a link by changing its path is exactly what we want to catch.
    briefing = citing(make_briefing, "https://example.com/news/a")

    assert find_unknown_sources(briefing, ["https://example.com/a"]) == [
        "https://example.com/news/a"
    ]


def test_spelling_differences_do_not_cause_false_alarms(make_briefing):
    briefing = citing(
        make_briefing, "https://Example.com/a/", "https://example.com/b?x=1&y=2"
    )

    unknown = find_unknown_sources(
        briefing, ["https://example.com/a", "https://example.com/b?x=1&amp;y=2"]
    )

    assert unknown == []


def test_the_same_unknown_url_is_reported_once(make_briefing):
    briefing = citing(
        make_briefing, "https://made-up.example/z", "https://made-up.example/z"
    )

    assert find_unknown_sources(briefing, []) == ["https://made-up.example/z"]


# --- find_uncited_links -------------------------------------------------


def test_input_links_that_are_never_cited_are_listed(make_briefing):
    briefing = citing(make_briefing, "https://example.com/a")

    uncited = find_uncited_links(
        briefing,
        ["https://example.com/a", "https://example.com/b", "https://example.com/b/"],
    )

    assert uncited == ["https://example.com/b"]  # listed once, despite the repeat


# --- check_briefing -----------------------------------------------------


def test_report_counts_and_coverage(make_briefing):
    briefing = citing(
        make_briefing,
        "https://example.com/a",
        "https://example.com/b",
        "https://made-up.example/z",
    )
    input_links = [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
        "https://example.com/d",
        "https://example.com/d/",  # a repeat of the one above
    ]

    report = check_briefing(briefing, input_links)

    assert report.theme_count == 1
    assert report.bullet_count == 3
    assert report.input_link_count == 4  # distinct
    assert report.cited_count == 3
    assert report.unknown_sources == ["https://made-up.example/z"]
    assert report.uncited_links == ["https://example.com/c", "https://example.com/d"]
    assert report.coverage == pytest.approx(0.5)
    assert report.passed is False


def test_report_passes_when_nothing_unknown_is_cited(make_briefing):
    briefing = citing(make_briefing, "https://example.com/a")

    report = check_briefing(
        briefing, ["https://example.com/a", "https://example.com/b"]
    )

    assert report.passed is True
    assert report.coverage == pytest.approx(0.5)  # a gap in coverage is not a failure


def test_report_with_no_input_links_does_not_divide_by_zero(make_briefing):
    report = check_briefing(citing(make_briefing, "https://example.com/a"), [])

    assert report.coverage == 0.0
    assert report.unknown_sources == ["https://example.com/a"]


# --- format_report ------------------------------------------------------


def test_format_report_shows_the_verdict_and_the_unknown_links(make_briefing):
    failing = check_briefing(
        citing(make_briefing, "https://made-up.example/z"), ["https://example.com/a"]
    )
    passing = check_briefing(
        citing(make_briefing, "https://example.com/a"), ["https://example.com/a"]
    )

    failing_text = format_report(failing)
    passing_text = format_report(passing)

    assert "FAIL" in failing_text
    assert "https://made-up.example/z" in failing_text
    assert "PASS" in passing_text
    assert "Unknown links" not in passing_text
