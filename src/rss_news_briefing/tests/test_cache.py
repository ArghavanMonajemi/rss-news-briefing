import os
import time

import pytest
from rss_news_briefing import cache

URL = "https://example.com/article"


def age_file(path, hours):
    """Make a file look like it was last modified `hours` ago."""
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


# --- article text cache -------------------------------------------------


def test_save_then_load_returns_the_text():
    cache.save_cached_article_text(URL, "hello")

    assert cache.load_cached_text(URL) == "hello"


def test_missing_entry_is_a_miss():
    assert cache.load_cached_text(URL) is None


@pytest.mark.parametrize("contents", ["{not json", "", "{}", '{"other": 1}'])
def test_unreadable_or_incomplete_file_is_a_miss(contents):
    cache.save_cached_article_text(URL, "hello")
    cache.cache_article_path(URL).write_text(contents, encoding="utf-8")

    assert cache.load_cached_text(URL) is None


def test_entry_older_than_the_ttl_is_a_miss():
    cache.save_cached_article_text(URL, "hello")
    age_file(cache.cache_article_path(URL), hours=25)

    assert cache.load_cached_text(URL) is None


def test_entry_inside_the_ttl_is_a_hit():
    cache.save_cached_article_text(URL, "hello")
    age_file(cache.cache_article_path(URL), hours=23)

    assert cache.load_cached_text(URL) == "hello"


def test_no_ttl_means_entries_never_expire(monkeypatch):
    monkeypatch.setattr(cache, "CACHE_TTL_HOURS", None)
    cache.save_cached_article_text(URL, "hello")
    age_file(cache.cache_article_path(URL), hours=24 * 365)

    assert cache.load_cached_text(URL) == "hello"


def test_different_urls_do_not_share_an_entry():
    cache.save_cached_article_text("https://example.com/a", "text a")

    assert cache.load_cached_text("https://example.com/b") is None


def test_url_to_filename_is_stable_and_unique():
    name = cache.url_to_filename("https://example.com/a")

    assert name == cache.url_to_filename("https://example.com/a")
    assert name != cache.url_to_filename("https://example.com/b")
    assert len(name) == 64
    assert all(c in "0123456789abcdef" for c in name)


def test_cache_files_go_to_the_isolated_folder():
    # Guards the conftest fixture: tests must never touch the real .cache/.
    cache.save_cached_article_text(URL, "hello")

    assert cache.cache_article_path(URL).parent == cache.ARTICLES_DIR
    assert cache.cache_article_path(URL).exists()


# --- briefing cache -----------------------------------------------------


def test_briefing_save_then_load_roundtrip():
    path = cache.briefing_cache_path(
        articles_xml="<articles/>", model="m1", instructions="do it"
    )

    assert cache.load_cached_briefing(path) is None

    cache.save_cached_briefing(path, "the briefing")

    assert cache.load_cached_briefing(path) == "the briefing"
    assert path.parent == cache.OUTPUT_DIR


def test_same_inputs_give_the_same_briefing_path():
    kwargs = {"articles_xml": "<articles/>", "model": "m1", "instructions": "do it"}

    assert cache.briefing_cache_path(**kwargs) == cache.briefing_cache_path(**kwargs)


@pytest.mark.parametrize(
    "changed",
    [
        {"articles_xml": "<articles>different</articles>"},
        {"model": "m2"},
        {"instructions": "do it differently"},
    ],
)
def test_briefing_path_changes_when_any_input_changes(changed):
    base = {"articles_xml": "<articles/>", "model": "m1", "instructions": "do it"}

    original = cache.briefing_cache_path(**base)
    modified = cache.briefing_cache_path(**{**base, **changed})

    assert original != modified


def test_briefing_key_does_not_confuse_where_one_field_ends():
    # "ab" + "c" and "a" + "bc" contain the same characters in the same order.
    first = cache.briefing_cache_path(articles_xml="x", model="ab", instructions="c")
    second = cache.briefing_cache_path(articles_xml="x", model="a", instructions="bc")

    assert first != second
