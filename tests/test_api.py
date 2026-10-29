import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai import OpenAIError

from rss_news_briefing import api
from rss_news_briefing.models import Briefing, BriefingFormatError
from rss_news_briefing.pipeline import BriefingResult, NoArticlesError, UsageInfo

SAMPLE_BRIEFING = Briefing.model_validate(
    {
        "overview": "Overview of the day.",
        "themes": [
            {
                "title": "Theme",
                "bullets": [
                    {"text": "A bullet.", "sources": ["https://example.com/a"]}
                ],
            }
        ],
        "worth_watching": "Watch this.",
    }
)


def make_result(usage=None, **overrides):
    return BriefingResult(
        briefing=SAMPLE_BRIEFING,
        article_count=3,
        sources=["Source A", "Source B"],
        usage=usage,
        cache_hits=1,
        cache_misses=2,
        generated_at=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
        **overrides,
    )


@pytest.fixture(autouse=True)
def reset_api_state(monkeypatch):
    """The API keeps its last result in a module variable. Start every test empty."""
    monkeypatch.setattr(api, "_latest", None)


@pytest.fixture
def client():
    # Used WITHOUT `with`, so the lifespan (and its API-key check) does not run.
    return TestClient(api.app)


@pytest.fixture
def fake_generate(monkeypatch):
    """Replace the pipeline. Set `.error` to make it raise, `.result` to change output."""
    state = SimpleNamespace(calls=0, result=make_result(), error=None)

    def fake():
        state.calls += 1
        if state.error is not None:
            raise state.error
        return state.result

    monkeypatch.setattr(api, "generate_briefing", fake)
    return state


# --- /health ------------------------------------------------------------


def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- /briefing: the response --------------------------------------------


def test_first_briefing_request_runs_the_pipeline(client, fake_generate):
    response = client.get("/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["article_count"] == 3
    assert body["sources"] == ["Source A", "Source B"]
    assert body["generated_at"].startswith("2026-10-28T12:00:00")
    assert body["cached"] is False
    assert body["usage"] is None
    assert fake_generate.calls == 1


def test_the_briefing_is_returned_as_structured_json(client, fake_generate):
    body = client.get("/briefing").json()

    briefing = body["briefing"]
    assert briefing["overview"] == "Overview of the day."
    assert briefing["worth_watching"] == "Watch this."
    assert briefing["themes"][0]["title"] == "Theme"
    bullet = briefing["themes"][0]["bullets"][0]
    assert bullet["text"] == "A bullet."
    assert bullet["sources"] == ["https://example.com/a"]


def test_unknown_sources_are_reported_in_the_response(client, fake_generate):
    fake_generate.result = make_result(unknown_sources=["https://made-up.example/z"])

    body = client.get("/briefing").json()

    assert body["unknown_sources"] == ["https://made-up.example/z"]


def test_unknown_sources_is_empty_when_the_briefing_is_grounded(client, fake_generate):
    assert client.get("/briefing").json()["unknown_sources"] == []


def test_response_reports_the_mode_and_failed_summaries(client, fake_generate):
    fake_generate.result = make_result(mode="map-reduce", failed_summaries=2)

    body = client.get("/briefing").json()

    assert body["mode"] == "map-reduce"
    assert body["failed_summaries"] == 2


def test_usage_is_included_when_there_was_an_api_call(client, fake_generate):
    fake_generate.result = make_result(
        usage=UsageInfo(
            input_tokens=1000, cached_tokens=400, output_tokens=100, cost=0.0114
        )
    )

    body = client.get("/briefing").json()

    assert body["usage"] == {
        "input_tokens": 1000,
        "cached_tokens": 400,
        "output_tokens": 100,
        "estimated_cost_usd": 0.0114,
    }


# --- /briefing: the in-memory cache -------------------------------------


def test_second_request_is_served_from_memory(client, fake_generate):
    client.get("/briefing")

    second = client.get("/briefing").json()

    assert second["cached"] is True
    assert fake_generate.calls == 1


def test_expired_result_is_regenerated(client, fake_generate, monkeypatch):
    monkeypatch.setattr(api, "BRIEFING_TTL_MINUTES", 0)
    client.get("/briefing")

    second = client.get("/briefing").json()

    assert second["cached"] is False
    assert fake_generate.calls == 2


def test_concurrent_requests_share_one_generation(monkeypatch):
    calls = []

    def slow_generate():
        calls.append(1)
        time.sleep(0.2)
        return make_result()

    monkeypatch.setattr(api, "generate_briefing", slow_generate)

    # Call the endpoint function directly from several threads at once.
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: api.get_briefing(), range(5)))

    assert len(calls) == 1
    assert sorted(r.cached for r in responses) == [False, True, True, True, True]


# --- /briefing: errors --------------------------------------------------


def test_no_articles_becomes_503(client, fake_generate):
    fake_generate.error = NoArticlesError("No articles found in any feed.")

    response = client.get("/briefing")

    assert response.status_code == 503


def test_llm_failure_becomes_502_without_leaking_details(client, fake_generate):
    fake_generate.error = OpenAIError("boom: secret internal detail")

    response = client.get("/briefing")

    assert response.status_code == 502
    assert "secret internal detail" not in response.text


def test_an_invalid_model_answer_becomes_502(client, fake_generate):
    fake_generate.error = BriefingFormatError("The model did not return valid JSON.")

    response = client.get("/briefing")

    assert response.status_code == 502


def test_a_failed_request_is_not_cached(client, fake_generate):
    fake_generate.error = NoArticlesError("nothing")
    assert client.get("/briefing").status_code == 503

    fake_generate.error = None
    response = client.get("/briefing")

    assert response.status_code == 200
    assert response.json()["cached"] is False
    assert fake_generate.calls == 2


# --- startup ------------------------------------------------------------


def test_startup_fails_when_the_api_key_is_missing(monkeypatch):
    def missing(key, **kwargs):
        raise RuntimeError(f"{key} not found")

    monkeypatch.setattr(api, "config", missing)

    with pytest.raises(RuntimeError), TestClient(api.app):
        pass


def test_startup_succeeds_when_the_api_key_is_present(monkeypatch):
    monkeypatch.setattr(api, "config", lambda key, **kwargs: "test-key")

    with TestClient(api.app) as client:
        assert client.get("/health").status_code == 200
