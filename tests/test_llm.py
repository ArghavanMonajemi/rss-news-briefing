import json
from types import SimpleNamespace

import pytest

from rss_news_briefing import cache, llm
from rss_news_briefing.models import Briefing, BriefingFormatError


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


# --- summarize_articles -------------------------------------------------

XML = "<articles>one</articles>"


@pytest.fixture
def fake_api(monkeypatch, make_usage, make_briefing_dict):
    """Replace the OpenAI client and the API-key lookup. Records every call.

    `outputs` is the list of answers the fake gives, one per call. When it runs
    out, the last answer is repeated. The default is one valid briefing.
    """
    state = SimpleNamespace(
        calls=[],
        outputs=[json.dumps(make_briefing_dict())],
        usage=make_usage(),
    )

    class FakeOpenAI:
        def __init__(self, api_key=None, **kwargs):
            self.api_key = api_key
            self.responses = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            state.calls.append(kwargs)
            index = min(len(state.calls), len(state.outputs)) - 1
            return SimpleNamespace(output_text=state.outputs[index], usage=state.usage)

    monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm, "config", lambda key, **kwargs: "test-key")
    return state


def test_first_call_returns_a_validated_briefing_and_the_usage(fake_api):
    briefing, usages = llm.summarize_articles(XML)

    assert isinstance(briefing, Briefing)
    assert briefing.overview == "Overview of the day."
    assert usages == [fake_api.usage]
    assert len(fake_api.calls) == 1


def test_api_is_called_with_the_model_instructions_and_articles(fake_api):
    llm.summarize_articles(XML)

    call = fake_api.calls[0]
    assert call["model"] == llm.MODEL
    assert call["instructions"] == llm.INSTRUCTIONS
    assert call["input"] == XML


def test_the_instructions_ask_for_json_and_exact_urls():
    assert "JSON" in llm.INSTRUCTIONS
    assert "<link>" in llm.INSTRUCTIONS


def test_a_valid_briefing_is_saved_to_the_cache_as_json(fake_api):
    briefing, _ = llm.summarize_articles(XML)

    path = cache.briefing_cache_path(XML, llm.MODEL, llm.INSTRUCTIONS)
    saved = cache.load_cached_briefing(path)
    assert Briefing.model_validate_json(saved) == briefing


def test_same_input_a_second_time_makes_no_api_call(fake_api):
    first, _ = llm.summarize_articles(XML)

    second, usages = llm.summarize_articles(XML)

    assert second == first
    assert usages == []  # nothing was billed
    assert len(fake_api.calls) == 1


def test_different_input_makes_a_new_api_call(fake_api):
    llm.summarize_articles("<articles>one</articles>")
    llm.summarize_articles("<articles>two</articles>")

    assert len(fake_api.calls) == 2


def test_cached_briefing_needs_neither_api_key_nor_client(fake_api, monkeypatch):
    llm.summarize_articles(XML)

    def forbidden(*args, **kwargs):
        raise AssertionError("must not be called on a cache hit")

    monkeypatch.setattr(llm, "config", forbidden)
    monkeypatch.setattr(llm, "OpenAI", forbidden)

    briefing, usages = llm.summarize_articles(XML)

    assert briefing.overview == "Overview of the day."
    assert usages == []


def test_an_unreadable_cached_briefing_is_ignored_and_replaced(fake_api):
    path = cache.briefing_cache_path(XML, llm.MODEL, llm.INSTRUCTIONS)
    cache.save_cached_briefing(path, "A plain-text briefing from an older version.")

    briefing, usages = llm.summarize_articles(XML)

    assert briefing.overview == "Overview of the day."
    assert len(usages) == 1
    assert len(fake_api.calls) == 1
    assert Briefing.model_validate_json(cache.load_cached_briefing(path)) == briefing


# --- summarize_articles: messy answers ----------------------------------


def test_json_wrapped_in_a_code_fence_is_accepted(fake_api, make_briefing_dict):
    fake_api.outputs = ["```json\n" + json.dumps(make_briefing_dict()) + "\n```"]

    briefing, _ = llm.summarize_articles(XML)

    assert briefing.overview == "Overview of the day."
    assert len(fake_api.calls) == 1


def test_an_invalid_answer_is_retried_once_with_the_error_attached(
    fake_api, make_briefing_dict
):
    fake_api.outputs = [
        "Sorry, here is a summary in prose.",
        json.dumps(make_briefing_dict()),
    ]

    briefing, usages = llm.summarize_articles(XML)

    assert briefing.overview == "Overview of the day."
    assert len(fake_api.calls) == 2
    assert len(usages) == 2  # both calls were billed, so both are reported
    assert fake_api.calls[0]["input"] == XML
    retry_input = fake_api.calls[1]["input"]
    assert XML in retry_input  # the articles are sent again
    assert "Sorry, here is a summary in prose." in retry_input  # the rejected answer
    assert "<validation_error>" in retry_input  # and why it was rejected


def test_an_answer_that_fails_validation_is_never_cached(fake_api):
    fake_api.outputs = ["not json at all"]

    with pytest.raises(BriefingFormatError):
        llm.summarize_articles(XML)

    path = cache.briefing_cache_path(XML, llm.MODEL, llm.INSTRUCTIONS)
    assert cache.load_cached_briefing(path) is None


def test_two_invalid_answers_raise_after_the_allowed_attempts(fake_api):
    fake_api.outputs = ["not json", '{"overview": "only this"}']

    with pytest.raises(BriefingFormatError):
        llm.summarize_articles(XML)

    assert len(fake_api.calls) == 1 + llm.MAX_FORMAT_RETRIES


def test_with_no_retries_allowed_the_first_invalid_answer_raises(fake_api, monkeypatch):
    monkeypatch.setattr(llm, "MAX_FORMAT_RETRIES", 0)
    fake_api.outputs = ["not json"]

    with pytest.raises(BriefingFormatError):
        llm.summarize_articles(XML)

    assert len(fake_api.calls) == 1
