import re
import threading
import time
from types import SimpleNamespace

import pytest
from openai import OpenAIError

from rss_news_briefing import cache, llm, pipeline
from rss_news_briefing.llm import MapResult
from rss_news_briefing.pipeline import generate_briefing
from rss_news_briefing.prompt import build_map_input, build_summaries_xml


def make_articles(make_article, n):
    """n articles titled "Article 0", "Article 1", ... with matching links."""
    return [
        make_article(
            title=f"Article {i}",
            link=f"https://example.com/{i}",
            summary=f"feed summary {i}",
        )
        for i in range(n)
    ]


# --- prompt builders ----------------------------------------------------


def test_map_input_truncates_and_escapes_the_text(make_article):
    article = make_article(title="Tom & Jerry", text="<b>" + "x" * 100)

    xml = build_map_input(article, max_chars=10)

    assert "<title>Tom &amp; Jerry</title>" in xml
    # 10 characters kept: "<b>" plus 7 x's, escaped afterwards
    assert "<text>&lt;b&gt;" + "x" * 7 + "</text>" in xml


def test_map_input_leaves_the_link_out(make_article):
    xml = build_map_input(make_article(link="https://example.com/secret-link"), 100)

    assert "secret-link" not in xml


def test_summaries_xml_has_the_summary_and_link_but_not_the_full_text(make_article):
    articles = [
        make_article(
            link=f"https://example.com/{i}", text="FULL TEXT", summary=f"short {i}"
        )
        for i in range(2)
    ]

    xml = build_summaries_xml(articles)

    assert "<summary>short 0</summary>" in xml
    assert "<link>https://example.com/1</link>" in xml
    assert "<id>0</id>" in xml and "<id>1</id>" in xml
    assert "FULL TEXT" not in xml


def test_summaries_xml_escapes_the_summary(make_article):
    xml = build_summaries_xml([make_article(summary="profit & loss <up>")])

    assert "<summary>profit &amp; loss &lt;up&gt;</summary>" in xml


# --- summary cache ------------------------------------------------------


def test_summary_save_then_load_uses_its_own_folder():
    path = cache.summary_cache_path("<article/>", "m1", "do it")

    assert cache.load_cached_summary(path) is None

    cache.save_cached_summary(path, "short summary")

    assert cache.load_cached_summary(path) == "short summary"
    assert path.parent == cache.SUMMARIES_DIR
    assert cache.SUMMARIES_DIR != cache.OUTPUT_DIR


@pytest.mark.parametrize(
    "changed",
    [
        {"article_xml": "<article>different</article>"},
        {"model": "m2"},
        {"instructions": "do it differently"},
    ],
)
def test_summary_path_changes_when_any_input_changes(changed):
    base = {"article_xml": "<article/>", "model": "m1", "instructions": "do it"}

    original = cache.summary_cache_path(**base)
    modified = cache.summary_cache_path(**{**base, **changed})

    assert original != modified


# --- the map step -------------------------------------------------------


@pytest.fixture
def fake_api(monkeypatch, make_usage):
    """Fake OpenAI client for the per-article calls.

    The fake answers "summary of <title>". Knobs for tests:
      fail_when:  raise OpenAIError for the article with exactly this title
      blank_when: return empty output for the article with exactly this title
      delay_for:  function(title) -> seconds to sleep before answering
    It also records every call and the most calls ever running at once.
    """
    state = SimpleNamespace(
        calls=[],
        fail_when=None,
        blank_when=None,
        delay_for=None,
        active=0,
        max_active=0,
        lock=threading.Lock(),
    )

    def create(**kwargs):
        title = re.search(r"<title>(.*?)</title>", kwargs["input"]).group(1)
        with state.lock:
            state.calls.append(kwargs)
            state.active += 1
            state.max_active = max(state.max_active, state.active)
        try:
            if state.delay_for is not None:
                time.sleep(state.delay_for(title))
            if state.fail_when == title:
                raise OpenAIError("boom")
            output = "" if state.blank_when == title else f"summary of {title}"
            return SimpleNamespace(output_text=output, usage=make_usage(100, 0, 20))
        finally:
            with state.lock:
                state.active -= 1

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = SimpleNamespace(create=create)

    monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm, "config", lambda key, **kwargs: "test-key")
    return state


def test_each_article_gets_its_own_call_and_keeps_its_place(fake_api, make_article):
    results = llm.summarize_each(make_articles(make_article, 3))

    assert len(fake_api.calls) == 3
    assert [r.summary for r in results] == [f"summary of Article {i}" for i in range(3)]
    assert all(r.usage is not None for r in results)
    assert not any(r.from_cache or r.failed for r in results)


def test_no_articles_means_no_client_and_no_api_key(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not be called")

    monkeypatch.setattr(llm, "config", forbidden)
    monkeypatch.setattr(llm, "OpenAI", forbidden)

    assert llm.summarize_each([]) == []


def test_calls_use_the_model_the_map_instructions_and_truncated_text(
    fake_api, make_article, monkeypatch
):
    monkeypatch.setattr(llm, "MAP_MAX_SUMMARY_CHARS", 5)
    article = make_article(title="Article 0", text="x" * 50)

    llm.summarize_each([article])

    call = fake_api.calls[0]
    assert call["model"] == llm.MODEL
    assert call["instructions"] == llm.MAP_INSTRUCTIONS
    assert "<text>xxxxx</text>" in call["input"]


def test_results_keep_input_order_when_calls_finish_out_of_order(
    fake_api, make_article, monkeypatch
):
    monkeypatch.setattr(llm, "MAX_WORKERS", 4)
    n = 8
    # Earlier articles sleep longer, so they finish last.
    fake_api.delay_for = lambda title: (n - int(title.split()[1])) * 0.01

    results = llm.summarize_each(make_articles(make_article, n))

    assert [r.summary for r in results] == [f"summary of Article {i}" for i in range(n)]


def test_no_more_than_max_workers_calls_run_at_once(
    fake_api, make_article, monkeypatch
):
    monkeypatch.setattr(llm, "MAX_WORKERS", 2)
    fake_api.delay_for = lambda title: 0.05

    llm.summarize_each(make_articles(make_article, 6))

    assert fake_api.max_active == 2


# --- the map step: caching ----------------------------------------------


def test_second_run_makes_no_calls_and_marks_results_cached(fake_api, make_article):
    articles = make_articles(make_article, 3)
    first = llm.summarize_each(articles)

    second = llm.summarize_each(articles)

    assert len(fake_api.calls) == 3  # all from the first run
    assert [r.summary for r in second] == [r.summary for r in first]
    assert all(r.from_cache and r.usage is None for r in second)


def test_cached_summaries_need_neither_api_key_nor_client(
    fake_api, make_article, monkeypatch
):
    articles = make_articles(make_article, 2)
    llm.summarize_each(articles)

    def forbidden(*args, **kwargs):
        raise AssertionError("must not be called on a cache hit")

    monkeypatch.setattr(llm, "config", forbidden)
    monkeypatch.setattr(llm, "OpenAI", forbidden)

    results = llm.summarize_each(articles)

    assert all(r.from_cache for r in results)


def test_only_new_articles_are_sent_on_a_later_run(fake_api, make_article):
    llm.summarize_each(make_articles(make_article, 2))
    fake_api.calls.clear()

    results = llm.summarize_each(make_articles(make_article, 3))

    assert len(fake_api.calls) == 1  # only "Article 2" is new
    assert [r.summary for r in results] == [f"summary of Article {i}" for i in range(3)]
    assert [r.from_cache for r in results] == [True, True, False]


# --- the map step: failures ---------------------------------------------


def test_failed_call_falls_back_to_the_feed_summary_and_others_succeed(
    fake_api, make_article
):
    fake_api.fail_when = "Article 1"

    results = llm.summarize_each(make_articles(make_article, 3))

    assert results[1].failed is True
    assert results[1].summary == "feed summary 1"
    assert results[1].usage is None
    assert results[0].summary == "summary of Article 0"
    assert results[2].summary == "summary of Article 2"
    assert not results[0].failed and not results[2].failed


def test_failures_are_not_cached_so_the_next_run_retries(fake_api, make_article):
    articles = make_articles(make_article, 2)
    fake_api.fail_when = "Article 1"
    llm.summarize_each(articles)

    fake_api.fail_when = None
    results = llm.summarize_each(articles)

    assert results[0].from_cache is True  # the success was cached
    assert results[1].failed is False  # the failure was retried and now works
    assert results[1].summary == "summary of Article 1"


def test_blank_output_counts_as_a_failure(fake_api, make_article):
    fake_api.blank_when = "Article 0"

    result = llm.summarize_each(make_articles(make_article, 1))[0]

    assert result.failed is True
    assert result.summary == "feed summary 0"


def test_fallback_uses_the_start_of_the_text_when_the_feed_has_no_summary(
    fake_api, make_article
):
    fake_api.fail_when = "Article 0"
    article = make_article(
        title="Article 0", link="https://example.com/0", summary="", text="y" * 1000
    )

    result = llm.summarize_each([article])[0]

    assert result.summary == "y" * llm.FALLBACK_CHARS


# --- the pipeline: choosing the mode ------------------------------------


@pytest.fixture
def env(monkeypatch):
    """Fake feeds and both LLM steps, so only the pipeline's own logic runs.

    Set `env.articles` before calling generate_briefing().
    `env.map_results` overrides what the map step returns.
    `env.reduce_usage` is the usage the final call reports.
    `env.map_inputs` / `env.xml_seen` record what each step received.
    """
    state = SimpleNamespace(
        articles=[],
        map_results=None,
        reduce_usage=None,
        map_inputs=[],
        xml_seen=[],
    )

    def fake_fetch_articles(feed):
        return state.articles, 0

    def fake_summarize_each(articles):
        state.map_inputs.append(articles)
        if state.map_results is not None:
            return state.map_results
        return [MapResult(f"short {i}", usage=None) for i in range(len(articles))]

    def fake_summarize_articles(xml):
        state.xml_seen.append(xml)
        return "the briefing", state.reduce_usage

    monkeypatch.setattr(pipeline, "FEEDS", ["feed-a"])
    monkeypatch.setattr(pipeline, "MAP_REDUCE_THRESHOLD", 3)
    monkeypatch.setattr(pipeline, "fetch_articles", fake_fetch_articles)
    monkeypatch.setattr(pipeline, "summarize_each", fake_summarize_each)
    monkeypatch.setattr(pipeline, "summarize_articles", fake_summarize_articles)
    return state


def numbered_articles(make_article, n):
    """Story 0 is the oldest and Story n-1 the newest."""
    return [
        make_article(
            title=f"Story {i}",
            link=f"https://example.com/{i}",
            text=f"FULL TEXT {i}",
            timestamp=i + 1,
        )
        for i in range(n)
    ]


def test_at_the_threshold_the_single_call_mode_is_used(env, make_article):
    env.articles = numbered_articles(make_article, 3)

    result = generate_briefing()

    assert result.mode == "single"
    assert env.map_inputs == []  # the map step never ran
    assert "FULL TEXT 0" in env.xml_seen[0]  # the final call got the full texts
    assert result.failed_summaries == 0


def test_above_the_threshold_map_reduce_is_used(env, make_article):
    env.articles = numbered_articles(make_article, 4)

    result = generate_briefing()

    assert result.mode == "map-reduce"
    assert len(env.map_inputs) == 1 and len(env.map_inputs[0]) == 4
    assert "short 0" in env.xml_seen[0]  # the final call got the short summaries
    assert "FULL TEXT" not in env.xml_seen[0]  # and not the full texts


def test_each_summary_stays_attached_to_its_own_article(env, make_article):
    env.articles = numbered_articles(make_article, 4)

    generate_briefing()

    xml = env.xml_seen[0]
    # Newest first: "Story 3" is first, so it gets the first summary, "short 0".
    assert re.search(r"<title>Story 3</title>.*?<summary>short 0</summary>", xml, re.DOTALL)
    assert re.search(r"<title>Story 0</title>.*?<summary>short 3</summary>", xml, re.DOTALL)


def test_usage_adds_up_the_map_calls_and_the_final_call(env, make_article, make_usage):
    env.articles = numbered_articles(make_article, 4)
    first = make_usage(1000, 0, 100)
    second = make_usage(2000, 500, 200)
    final = make_usage(300, 100, 50)
    env.map_results = [
        MapResult("a", first),
        MapResult("b", None, from_cache=True),
        MapResult("c", second),
        MapResult("d", None, from_cache=True),
    ]
    env.reduce_usage = final

    usage = generate_briefing().usage

    assert usage.input_tokens == 1000 + 2000 + 300
    assert usage.cached_tokens == 0 + 500 + 100
    assert usage.output_tokens == 100 + 200 + 50
    expected_cost = sum(llm.calculate_cost(u) for u in (first, second, final))
    assert usage.cost == pytest.approx(expected_cost)


def test_usage_is_none_when_nothing_was_billed(env, make_article):
    env.articles = numbered_articles(make_article, 4)  # all summaries "cached"

    assert generate_briefing().usage is None


def test_failed_summaries_are_counted(env, make_article):
    env.articles = numbered_articles(make_article, 4)
    env.map_results = [
        MapResult("a", None),
        MapResult("fallback", None, failed=True),
        MapResult("c", None),
        MapResult("fallback", None, failed=True),
    ]

    assert generate_briefing().failed_summaries == 2
