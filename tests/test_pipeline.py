from datetime import UTC
from types import SimpleNamespace

import pytest

from rss_news_briefing import llm, pipeline
from rss_news_briefing.pipeline import NoArticlesError, generate_briefing


def briefing_citing(make_briefing, *urls):
    bullets = [{"text": f"Bullet {i}.", "sources": [url]} for i, url in enumerate(urls)]
    return make_briefing(themes=[{"title": "Theme", "bullets": bullets}])


@pytest.fixture
def env(monkeypatch, make_briefing):
    """Fake the two slow/expensive steps: fetching feeds and calling the LLM.

    Fill `env.results` with {feed_name: (articles, hits)} or {feed_name: Exception}.
    Set `env.briefing` and `env.usages` to what summarize_articles should return.
    `env.xml_seen` records every input sent to the summarizer.
    """
    state = SimpleNamespace(
        results={},
        briefing=make_briefing(),
        usages=[],
        xml_seen=[],
    )

    def fake_fetch_articles(feed):
        result = state.results[feed]
        if isinstance(result, Exception):
            raise result
        return result

    def fake_summarize_articles(xml):
        state.xml_seen.append(xml)
        return state.briefing, state.usages

    monkeypatch.setattr(pipeline, "FEEDS", ["feed-a", "feed-b"])
    monkeypatch.setattr(pipeline, "fetch_articles", fake_fetch_articles)
    monkeypatch.setattr(pipeline, "summarize_articles", fake_summarize_articles)
    return state


# --- failures -----------------------------------------------------------


def test_all_feeds_empty_raises_no_articles_error(env):
    env.results = {"feed-a": ([], 0), "feed-b": ([], 0)}

    with pytest.raises(NoArticlesError):
        generate_briefing()

    assert env.xml_seen == []  # no money spent on an empty request


def test_all_feeds_failing_raises_no_articles_error(env):
    env.results = {"feed-a": RuntimeError("boom"), "feed-b": RuntimeError("boom")}

    with pytest.raises(NoArticlesError):
        generate_briefing()


def test_one_failing_feed_does_not_stop_the_others(env, make_article):
    env.results = {
        "feed-a": RuntimeError("boom"),
        "feed-b": ([make_article(link="https://example.com/b")], 0),
    }

    result = generate_briefing()

    assert result.article_count == 1


# --- combining articles -------------------------------------------------


def test_cache_hits_and_misses_are_added_up_across_feeds(env, make_article):
    env.results = {
        "feed-a": ([make_article(link=f"https://a.com/{i}") for i in range(3)], 2),
        "feed-b": ([make_article(link=f"https://b.com/{i}") for i in range(2)], 0),
    }

    result = generate_briefing()

    assert result.cache_hits == 2
    assert result.cache_misses == 3


def test_an_empty_feed_does_not_count_towards_cache_stats(env, make_article):
    env.results = {
        "feed-a": ([], 0),
        "feed-b": ([make_article(link="https://b.com/1")], 1),
    }

    result = generate_briefing()

    assert (result.cache_hits, result.cache_misses) == (1, 0)


def test_duplicate_links_across_feeds_are_counted_once(env, make_article):
    shared = "https://example.com/shared"
    env.results = {
        "feed-a": (
            [make_article(link=shared), make_article(link="https://a.com/1")],
            0,
        ),
        "feed-b": ([make_article(link=shared)], 0),
    }

    result = generate_briefing()

    assert result.article_count == 2


def test_summarizer_receives_the_newest_article_first(env, make_article):
    env.results = {
        "feed-a": (
            [make_article(link="https://a.com/old", title="Oldest", timestamp=1)],
            0,
        ),
        "feed-b": (
            [make_article(link="https://b.com/new", title="Newest", timestamp=9)],
            0,
        ),
    }

    generate_briefing()

    xml = env.xml_seen[0]
    assert xml.index("Newest") < xml.index("Oldest")


def test_feed_names_are_unique_and_sorted(env, make_article):
    env.results = {
        "feed-a": (
            [
                make_article(link="https://a.com/1", source="Zed News"),
                make_article(link="https://a.com/2", source="Zed News"),
            ],
            0,
        ),
        "feed-b": ([make_article(link="https://b.com/1", source="Alpha Daily")], 0),
    }

    result = generate_briefing()

    assert result.sources == ["Alpha Daily", "Zed News"]


# --- the result ---------------------------------------------------------


def one_article_env(env, make_article):
    env.results = {
        "feed-a": ([make_article(link="https://a.com/1")], 0),
        "feed-b": ([], 0),
    }


def test_the_briefing_is_passed_through(env, make_article, make_briefing):
    one_article_env(env, make_article)
    env.briefing = make_briefing(overview="Today in the news...")

    assert generate_briefing().briefing.overview == "Today in the news..."


def test_usage_is_none_when_nothing_was_billed(env, make_article):
    one_article_env(env, make_article)
    env.usages = []  # the briefing came from the cache

    assert generate_briefing().usage is None


def test_usage_is_converted_with_the_estimated_cost(env, make_article, make_usage):
    one_article_env(env, make_article)
    raw_usage = make_usage(input_tokens=2000, cached_tokens=500, output_tokens=300)
    env.usages = [raw_usage]

    usage = generate_briefing().usage

    assert usage.input_tokens == 2000
    assert usage.cached_tokens == 500
    assert usage.output_tokens == 300
    assert usage.cost == pytest.approx(llm.calculate_cost(raw_usage))


def test_usage_adds_up_when_the_briefing_needed_a_retry(env, make_article, make_usage):
    one_article_env(env, make_article)
    first = make_usage(1000, 0, 100)
    retry = make_usage(1200, 0, 150)
    env.usages = [first, retry]

    usage = generate_briefing().usage

    assert usage.input_tokens == 2200
    assert usage.output_tokens == 250
    assert usage.cost == pytest.approx(
        llm.calculate_cost(first) + llm.calculate_cost(retry)
    )


def test_generated_at_is_timezone_aware(env, make_article):
    one_article_env(env, make_article)

    assert generate_briefing().generated_at.tzinfo == UTC


# --- grounding ----------------------------------------------------------


def test_links_given_to_the_model_are_recorded_newest_first(env, make_article):
    env.results = {
        "feed-a": ([make_article(link="https://a.com/old", timestamp=1)], 0),
        "feed-b": ([make_article(link="https://b.com/new", timestamp=9)], 0),
    }

    result = generate_briefing()

    assert result.input_links == ["https://b.com/new", "https://a.com/old"]


def test_no_unknown_sources_when_the_briefing_cites_only_input_links(
    env, make_article, make_briefing
):
    one_article_env(env, make_article)
    env.briefing = briefing_citing(make_briefing, "https://a.com/1")

    assert generate_briefing().unknown_sources == []


def test_an_invented_link_is_reported_as_an_unknown_source(
    env, make_article, make_briefing
):
    one_article_env(env, make_article)
    env.briefing = briefing_citing(
        make_briefing, "https://a.com/1", "https://made-up.example/story"
    )

    result = generate_briefing()

    assert result.unknown_sources == ["https://made-up.example/story"]
    assert result.briefing is env.briefing  # reported, not silently edited
