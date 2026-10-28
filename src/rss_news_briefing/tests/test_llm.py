from types import SimpleNamespace

import pytest
from rss_news_briefing import cache, llm


@pytest.fixture
def prices(monkeypatch):
    """Pin the prices so these tests don't break when you update the real ones."""
    monkeypatch.setattr(llm, "INPUT_PRICE", 0.10)
    monkeypatch.setattr(llm, "CACHED_INPUT_PRICE", 0.01)
    monkeypatch.setattr(llm, "OUTPUT_PRICE", 0.50)


# --- cost ---------------------------------------------------------------


@pytest.mark.usefixtures("prices")
@pytest.mark.parametrize(
    "input_tokens, cached_tokens, output_tokens, expected",
    [
        (1_000_000, 0, 0, 0.10),  # input only
        (0, 0, 1_000_000, 0.50),  # output only
        (1_000_000, 400_000, 100_000, 0.114),  # 0.06 + 0.004 + 0.05
        (1_000_000, 1_000_000, 0, 0.01),  # all cached: billed once, at the cached rate
        (0, 0, 0, 0.0),
    ],
)
def test_calculate_cost(
    make_usage, input_tokens, cached_tokens, output_tokens, expected
):
    usage = make_usage(input_tokens, cached_tokens, output_tokens)

    assert llm.calculate_cost(usage) == pytest.approx(expected)


# --- summarize ----------------------------------------------------------


@pytest.fixture
def fake_api(monkeypatch, make_usage):
    """Replace the OpenAI client and the API-key lookup. Records every call."""
    calls = []
    usage = make_usage()

    class FakeOpenAI:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.responses = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text="fresh briefing", usage=usage)

    monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm, "config", lambda key, **kwargs: "test-key")
    return SimpleNamespace(calls=calls, usage=usage)


def test_first_call_hits_the_api_and_returns_text_and_usage(fake_api):
    text, usage = llm.summarize_articles("<articles>one</articles>")

    assert text == "fresh briefing"
    assert usage is fake_api.usage
    assert len(fake_api.calls) == 1


def test_api_is_called_with_the_model_instructions_and_articles(fake_api):
    llm.summarize_articles("<articles>one</articles>")

    call = fake_api.calls[0]
    assert call["model"] == llm.MODEL
    assert call["instructions"] == llm.INSTRUCTIONS
    assert call["input"] == "<articles>one</articles>"


def test_fresh_briefing_is_saved_to_the_cache(fake_api):
    xml = "<articles>one</articles>"

    llm.summarize_articles(xml)

    path = cache.briefing_cache_path(xml, llm.MODEL, llm.INSTRUCTIONS)
    assert cache.load_cached_briefing(path) == "fresh briefing"


def test_same_input_a_second_time_makes_no_api_call(fake_api):
    xml = "<articles>one</articles>"
    llm.summarize_articles(xml)

    text, usage = llm.summarize_articles(xml)

    assert text == "fresh briefing"
    assert usage is None  # nothing was billed
    assert len(fake_api.calls) == 1


def test_different_input_makes_a_new_api_call(fake_api):
    llm.summarize_articles("<articles>one</articles>")
    llm.summarize_articles("<articles>two</articles>")

    assert len(fake_api.calls) == 2


def test_cached_briefing_needs_neither_api_key_nor_client(monkeypatch):
    xml = "<articles>cached</articles>"
    path = cache.briefing_cache_path(xml, llm.MODEL, llm.INSTRUCTIONS)
    cache.save_cached_briefing(path, "saved briefing")

    def forbidden(*args, **kwargs):
        raise AssertionError("must not be called on a cache hit")

    monkeypatch.setattr(llm, "config", forbidden)
    monkeypatch.setattr(llm, "OpenAI", forbidden)

    assert llm.summarize_articles(xml) == ("saved briefing", None)
