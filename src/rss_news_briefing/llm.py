import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from decouple import config
from openai import OpenAI, OpenAIError

from .cache import (
    briefing_cache_path,
    load_cached_briefing,
    load_cached_summary,
    save_cached_briefing,
    save_cached_summary,
    summary_cache_path,
)
from .config import (
    CACHED_INPUT_PRICE,
    INPUT_PRICE,
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
    MAP_MAX_SUMMARY_CHARS,
    MAX_WORKERS,
    MODEL,
    OUTPUT_PRICE,
    MAX_FORMAT_RETRIES,
)
from .prompt import INSTRUCTIONS, MAP_INSTRUCTIONS, build_map_input
from .models import BriefingFormatError, parse_briefing

log = logging.getLogger(__name__)

# When a per-article call fails and the feed has no summary, use this much text.
FALLBACK_CHARS = 500


@dataclass
class MapResult:
    """The outcome of summarizing one article in the map step."""

    summary: str
    usage: Any | None  # None when cached or when the call failed
    from_cache: bool = False
    failed: bool = False


def _make_client():
    # The client retries rate limits and server errors on its own, with backoff.
    return OpenAI(
        api_key=config("API-KEY"),
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )


def summarize_articles(articles_xml):
    """One LLM call (plus at most MAX_FORMAT_RETRIES retries) that writes the briefing.

    Returns (briefing, usages): a validated Briefing and a list with the usage
    of every API call made. The list is empty when the briefing came from cache.
    Raises BriefingFormatError if no attempt produced valid JSON.
    """
    path = briefing_cache_path(articles_xml, MODEL, INSTRUCTIONS)
    cached = load_cached_briefing(path)
    if cached is not None:
        try:
            briefing = parse_briefing(cached)
        except ValidationError:
            log.warning("Ignoring an unreadable cached briefing")
        else:
            log.info("Using cached briefing (no API call)")
            return briefing, []

    client = _make_client()
    usages = []
    model_input = articles_xml
    attempts = 1 + MAX_FORMAT_RETRIES
    for attempt in range(1, attempts + 1):
        response = client.responses.create(
            model=MODEL,
            instructions=INSTRUCTIONS,
            input=model_input,
            store=True,
        )
        usages.append(response.usage)
        try:
            briefing = parse_briefing(response.output_text)
        except ValidationError as error:
            log.warning(
                "Briefing failed validation (attempt %d of %d): %s",
                attempt,
                attempts,
                str(error).splitlines()[0],
            )
            last_error = error
            model_input = build_retry_input(
                articles_xml, response.output_text, str(error)
            )
            continue
        save_cached_briefing(path, briefing.model_dump_json())  # only valid ones
        return briefing, usages

    raise BriefingFormatError(
        f"The model did not return a valid briefing after {attempts} attempt(s)."
    ) from last_error


def _fallback_summary(article):
    return article["summary"] or article["text"][:FALLBACK_CHARS]


def _summarize_one(client, article, article_xml, path):
    """Map step for a single article. Never raises for an API failure."""
    try:
        response = client.responses.create(
            model=MODEL,
            instructions=MAP_INSTRUCTIONS,
            input=article_xml,
            store=False,  # no need to keep dozens of intermediate responses
        )
    except OpenAIError as error:
        log.warning("Could not summarize %s; using the feed summary", article["link"],type(error).__name__,)
        return MapResult(_fallback_summary(article), usage=None, failed=True)

    summary = response.output_text.strip()
    if not summary:
        log.warning("Empty summary for %s; using the feed summary", article["link"])
        return MapResult(_fallback_summary(article), usage=None, failed=True)

    save_cached_summary(path, summary)  # only real summaries are cached
    return MapResult(summary, usage=response.usage)


def summarize_each(articles):
    """Map step: summarize every article separately, several at a time.

    Returns one MapResult per article, in the same order as `articles`.
    """
    results = [None] * len(articles)
    jobs = []  # (position, article, article_xml, cache_path) for cache misses

    for position, article in enumerate(articles):
        article_xml = build_map_input(article, MAP_MAX_SUMMARY_CHARS)
        path = summary_cache_path(article_xml, MODEL, MAP_INSTRUCTIONS)
        cached = load_cached_summary(path)
        if cached is not None:
            results[position] = MapResult(cached, usage=None, from_cache=True)
        else:
            jobs.append((position, article, article_xml, path))

    if jobs:  # no client (and no API key) needed when everything was cached
        client = _make_client()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [
                (position, pool.submit(_summarize_one, client, *rest))
                for position, *rest in jobs
            ]
            for position, future in futures:
                results[position] = future.result()

    return results


def calculate_cost(usage):
    """Estimate the cost in USD. input_tokens already includes cached tokens."""
    cached = usage.input_tokens_details.cached_tokens
    uncached = usage.input_tokens - cached
    return (
        uncached * INPUT_PRICE
        + cached * CACHED_INPUT_PRICE
        + usage.output_tokens * OUTPUT_PRICE
    ) / 1_000_000