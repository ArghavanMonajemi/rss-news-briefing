import json

import pytest
from pydantic import ValidationError

from rss_news_briefing.models import Briefing, parse_briefing


def valid():
    """A valid briefing as a plain dict."""
    return {
        "overview": "Overview.",
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


def changed(**changes):
    data = valid()
    data.update(changes)
    return data


def bullet(i):
    return {"text": f"Bullet {i}.", "sources": ["https://example.com/a"]}


# --- the models ---------------------------------------------------------


def test_a_valid_briefing_roundtrips_through_json():
    briefing = Briefing.model_validate(valid())

    again = Briefing.model_validate_json(briefing.model_dump_json())

    assert again == briefing


@pytest.mark.parametrize("missing", ["overview", "themes", "worth_watching"])
def test_each_top_level_field_is_required(missing):
    data = valid()
    del data[missing]

    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


INVALID_BRIEFINGS = [
    changed(overview=""),
    changed(worth_watching=""),
    changed(themes=[]),
    changed(themes=[{"title": f"Theme {i}", "bullets": [bullet(0)]} for i in range(6)]),
    changed(themes="not a list"),
    changed(themes=[{"title": "", "bullets": [bullet(0)]}]),
    changed(themes=[{"title": "Theme", "bullets": []}]),
    changed(themes=[{"title": "Theme", "bullets": [bullet(i) for i in range(5)]}]),
    changed(themes=[{"title": "Theme", "bullets": [{"text": "", "sources": ["u"]}]}]),
    changed(themes=[{"title": "Theme", "bullets": [{"text": "x", "sources": []}]}]),
    changed(themes=[{"title": "Theme", "bullets": [{"text": "x", "sources": "u"}]}]),
]


@pytest.mark.parametrize("data", INVALID_BRIEFINGS)
def test_invalid_shapes_are_rejected(data):
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_the_limits_themselves_are_allowed():
    data = changed(
        themes=[
            {"title": f"Theme {i}", "bullets": [bullet(j) for j in range(4)]}
            for i in range(5)
        ]
    )

    briefing = Briefing.model_validate(data)

    assert len(briefing.themes) == 5
    assert all(len(theme.bullets) == 4 for theme in briefing.themes)


# --- parse_briefing -----------------------------------------------------


def test_parse_accepts_plain_json():
    briefing = parse_briefing(json.dumps(valid()))

    assert briefing.overview == "Overview."


def test_parse_ignores_surrounding_whitespace():
    assert parse_briefing("\n  " + json.dumps(valid()) + "  \n").overview == "Overview."


@pytest.mark.parametrize("fence", ["```json", "```JSON", "```"])
def test_parse_accepts_json_wrapped_in_a_code_fence(fence):
    raw = f"{fence}\n{json.dumps(valid(), indent=2)}\n```"

    assert parse_briefing(raw).overview == "Overview."


def test_parse_ignores_unknown_extra_keys():
    data = changed(confidence=0.9)

    assert parse_briefing(json.dumps(data)).overview == "Overview."


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "Here is your briefing: it was a quiet day.",
        "{not json",
        "[]",
        json.dumps({"overview": "only this"}),
        json.dumps(changed(themes=[])),
    ],
)
def test_parse_rejects_anything_that_is_not_a_valid_briefing(raw):
    with pytest.raises(ValidationError):
        parse_briefing(raw)
