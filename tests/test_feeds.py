import calendar
from types import SimpleNamespace

import feedparser
import pytest
from feedparser import FeedParserDict

from rss_news_briefing import cache, feeds

FEED_URL = "https://example.com/feed.xml"
LINK = "https://example.com/story-1"


# --- helpers ------------------------------------------------------------


def build_rss(entries):
    """Build a small RSS document from dicts with link/title/summary/date."""
    items = ""
    for entry in entries:
        date = f"<pubDate>{entry['date']}</pubDate>" if entry.get("date") else ""
        items += (
            f"<item><title>{entry.get('title', 'Title')}</title>"
            f"<link>{entry['link']}</link>"
            f"<description>{entry.get('summary', 'Summary')}</description>"
            f"{date}</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<title>Test Feed</title><link>https://example.com</link>"
        f"<description>desc</description>{items}</channel></rss>"
    )


@pytest.fixture
def serve_feed(monkeypatch):
    """Make feedparser.parse return a feed built from `entries`, with no network."""
    real_parse = feedparser.parse

    def _serve(entries):
        xml = build_rss(entries)
        monkeypatch.setattr(feeds.feedparser, "parse", lambda url: real_parse(xml))

    return _serve


@pytest.fixture
def parse_returns(monkeypatch):
    """Make feedparser.parse return a hand-built result (for error cases)."""

    def _set(**fields):
        result = FeedParserDict(
            {"bozo": 0, "entries": [], "feed": FeedParserDict({}), **fields}
        )
        monkeypatch.setattr(feeds.feedparser, "parse", lambda url: result)

    return _set


@pytest.fixture
def downloads(monkeypatch):
    """Fake page download and text extraction.

    `pages` maps url -> extracted text.
      - url missing from `pages`: the download fails (fetch_url returns None)
      - pages[url] = None:        the download works but extraction fails
    `fetched` records every URL that was downloaded.
    """
    env = SimpleNamespace(pages={}, fetched=[])

    def fake_fetch_url(url):
        env.fetched.append(url)
        return url if url in env.pages else None

    def fake_extract(downloaded):
        return env.pages[downloaded]

    monkeypatch.setattr(feeds, "fetch_url", fake_fetch_url)
    monkeypatch.setattr(feeds, "extract", fake_extract)
    return env


# --- fetch_articles: the happy path -------------------------------------


def test_article_fields_come_from_the_feed(serve_feed, downloads):
    serve_feed(
        [
            {
                "link": LINK,
                "title": "Big news",
                "summary": "Short",
                "date": "Mon, 26 Oct 2026 10:00:00 GMT",
            }
        ]
    )
    downloads.pages[LINK] = "Full text"

    articles, hits = feeds.fetch_articles(FEED_URL)

    assert len(articles) == 1
    article = articles[0]
    assert article["source"] == "Test Feed"
    assert article["title"] == "Big news"
    assert article["link"] == LINK
    assert article["summary"] == "Short"
    assert article["published"] == "Mon, 26 Oct 2026 10:00:00 GMT"
    assert article["text"] == "Full text"
    assert article["timestamp"] == calendar.timegm((2026, 10, 26, 10, 0, 0, 0, 0, 0))
    assert hits == 0


def test_entry_without_a_date_gets_timestamp_zero(serve_feed, downloads):
    serve_feed([{"link": LINK}])
    downloads.pages[LINK] = "Full text"

    articles, _ = feeds.fetch_articles(FEED_URL)

    assert articles[0]["timestamp"] == 0
    assert articles[0]["published"] == ""


# --- fetch_articles: caching and fallback -------------------------------


def test_successful_extraction_is_saved_to_the_cache(serve_feed, downloads):
    serve_feed([{"link": LINK}])
    downloads.pages[LINK] = "Full text"

    feeds.fetch_articles(FEED_URL)

    assert cache.load_cached_text(LINK) == "Full text"


def test_second_run_uses_the_cache_and_does_not_download(serve_feed, downloads):
    serve_feed([{"link": LINK}])
    downloads.pages[LINK] = "Full text"
    feeds.fetch_articles(FEED_URL)

    articles, hits = feeds.fetch_articles(FEED_URL)

    assert hits == 1
    assert articles[0]["text"] == "Full text"
    assert downloads.fetched == [LINK]  # only the first run downloaded


def test_failed_download_falls_back_to_the_summary_and_is_not_cached(
    serve_feed, downloads
):
    serve_feed([{"link": LINK, "summary": "Feed summary"}])
    # LINK is not in downloads.pages, so fetch_url returns None

    articles, hits = feeds.fetch_articles(FEED_URL)

    assert articles[0]["text"] == "Feed summary"
    assert hits == 0
    assert cache.load_cached_text(LINK) is None


def test_failed_extraction_falls_back_to_the_summary_and_is_not_cached(
    serve_feed, downloads
):
    serve_feed([{"link": LINK, "summary": "Feed summary"}])
    downloads.pages[LINK] = None  # downloaded fine, extraction found nothing

    articles, _ = feeds.fetch_articles(FEED_URL)

    assert articles[0]["text"] == "Feed summary"
    assert cache.load_cached_text(LINK) is None


# --- fetch_articles: limits ---------------------------------------------


def test_only_max_per_feed_entries_are_processed(serve_feed, downloads, monkeypatch):
    monkeypatch.setattr(feeds, "MAX_PER_FEED", 2)
    links = [f"https://example.com/story-{i}" for i in range(5)]
    serve_feed([{"link": link} for link in links])
    downloads.pages.update({link: "text" for link in links})

    articles, _ = feeds.fetch_articles(FEED_URL)

    assert [a["link"] for a in articles] == links[:2]
    assert downloads.fetched == links[:2]  # the rest were never downloaded


def test_no_limit_processes_every_entry(serve_feed, downloads, monkeypatch):
    monkeypatch.setattr(feeds, "MAX_PER_FEED", None)
    links = [f"https://example.com/story-{i}" for i in range(5)]
    serve_feed([{"link": link} for link in links])
    downloads.pages.update({link: "text" for link in links})

    articles, _ = feeds.fetch_articles(FEED_URL)

    assert len(articles) == 5


# --- fetch_articles: broken feeds ---------------------------------------


@pytest.mark.parametrize("status", [404, 500])
def test_http_error_status_returns_nothing(parse_returns, status):
    parse_returns(status=status)

    assert feeds.fetch_articles(FEED_URL) == ([], 0)


def test_unreadable_feed_with_no_entries_returns_nothing(parse_returns):
    parse_returns(bozo=1, bozo_exception=Exception("not well-formed"))

    assert feeds.fetch_articles(FEED_URL) == ([], 0)


def test_bozo_feed_that_still_has_entries_is_used(parse_returns, downloads):
    entry = FeedParserDict({"link": LINK, "title": "Still here"})
    parse_returns(bozo=1, bozo_exception=Exception("minor problem"), entries=[entry])
    downloads.pages[LINK] = "Full text"

    articles, _ = feeds.fetch_articles(FEED_URL)

    assert [a["title"] for a in articles] == ["Still here"]


# --- deduplicate_articles -----------------------------------------------


def test_duplicate_links_are_removed_and_the_first_copy_is_kept(make_article):
    articles = [
        make_article(link="https://example.com/a", title="first"),
        make_article(link="https://example.com/b", title="other"),
        make_article(link="https://example.com/a", title="second"),
    ]

    result = feeds.deduplicate_articles(articles)

    assert [a["title"] for a in result] == ["first", "other"]


def test_deduplicating_an_empty_list_gives_an_empty_list():
    assert feeds.deduplicate_articles([]) == []


# --- sort_articles ------------------------------------------------------


def test_newest_articles_come_first(make_article):
    articles = [
        make_article(title="old", timestamp=100),
        make_article(title="new", timestamp=300),
        make_article(title="middle", timestamp=200),
    ]

    result = feeds.sort_articles(articles)

    assert [a["title"] for a in result] == ["new", "middle", "old"]


def test_articles_without_a_date_sort_last(make_article):
    articles = [
        make_article(title="undated", timestamp=0),
        make_article(title="dated", timestamp=100),
    ]

    result = feeds.sort_articles(articles)

    assert [a["title"] for a in result] == ["dated", "undated"]


def test_sort_articles_returns_a_list():
    # Guards the old bug where list.sort() made the function return None.
    assert feeds.sort_articles([]) == []
