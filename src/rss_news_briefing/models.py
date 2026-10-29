import re
from pydantic import BaseModel, Field


class BriefingFormatError(Exception):
    """Raised when the model's answer can't be turned into a valid Briefing."""


class Bullet(BaseModel):
    text: str = Field(min_length=1)
    # URLs copied from the articles' <link> tags. Every bullet must cite one.
    sources: list[str] = Field(min_length=1)


class Theme(BaseModel):
    title: str = Field(min_length=1)
    bullets: list[Bullet] = Field(min_length=1, max_length=4)


class Briefing(BaseModel):
    overview: str = Field(min_length=1)
    themes: list[Theme] = Field(min_length=1, max_length=5)
    worth_watching: str = Field(min_length=1)


# Models sometimes wrap JSON in a markdown code fence even when told not to.
_FENCE = re.compile(r"^```[A-Za-z]*\s*(.*?)\s*```$", re.DOTALL)


def parse_briefing(raw):
    """Turn the model's text answer into a validated Briefing.

    Raises pydantic.ValidationError if the text is not valid JSON or does not
    match the Briefing shape.
    """
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    return Briefing.model_validate_json(text)
