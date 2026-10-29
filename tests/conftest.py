from types import SimpleNamespace

import pytest

from rss_news_briefing import cache
from rss_news_briefing.models import Briefing


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Send every cache read/write to a throwaway folder.

    `cache.py` does `from .config import ARTICLES_DIR`, so the name lives in
    the cache module's namespace. That is where it has to be patched.
    """
    monkeypatch.setattr(cache, "ARTICLES_DIR", tmp_path / "articles")
    monkeypatch.setattr(cache, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(cache, "SUMMARIES_DIR", tmp_path / "summaries")
    monkeypatch.setattr(cache, "CACHE_TTL_HOURS", 24)


@pytest.fixture
def make_article():
    """Build an article dict, overriding any field you care about."""

    def _make(**overrides):
        article = {
            "source": "Test Feed",
            "title": "A title",
            "link": "https://example.com/a",
            "published": "Mon, 26 Oct 2026 10:00:00 GMT",
            "summary": "A summary",
            "text": "Full article text",
            "timestamp": 1000,
        }
        article.update(overrides)
        return article

    return _make


@pytest.fixture
def make_usage():
    """Build an object shaped like the OpenAI `response.usage`."""

    def _make(input_tokens=1000, cached_tokens=0, output_tokens=100):
        return SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
        )

    return _make


@pytest.fixture
def make_briefing_dict():
    """A valid briefing as a plain dict (what the model's JSON decodes to).

    The default bullet cites https://example.com/a, which is also the default
    link of `make_article`.
    """

    def _make(**overrides):
        data = {
            "overview": "Overview of the day.",
            "themes": [
                {
                    "title": "Theme",
                    "bullets": [
                        {
                            "text": "A bullet.",
                            "sources": ["https://example.com/a"],
                        }
                    ],
                }
            ],
            "worth_watching": "Watch this.",
        }
        data.update(overrides)
        return data

    return _make


@pytest.fixture
def make_briefing(make_briefing_dict):
    """A validated Briefing object. Override any top-level field."""

    def _make(**overrides):
        return Briefing.model_validate(make_briefing_dict(**overrides))

    return _make
