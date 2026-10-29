import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from .models import Briefing
from .config import FEEDS, MAP_REDUCE_THRESHOLD
from .feeds import deduplicate_articles, fetch_articles, sort_articles
from .llm import calculate_cost, summarize_articles, summarize_each
from .prompt import build_articles_xml, build_summaries_xml
from .grounding import find_unknown_sources

log = logging.getLogger(__name__)


class NoArticlesError(Exception):
    """Raised when no feed produced any articles."""


@dataclass
class UsageInfo:
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost: float


@dataclass
class BriefingResult:
    briefing: Briefing
    article_count: int
    sources: list[str]  # names of the feeds the articles came from
    usage: UsageInfo | None  # None when nothing was billed (everything cached)
    cache_hits: int
    cache_misses: int
    generated_at: datetime
    mode: str = "single"  # "single" or "map-reduce"
    failed_summaries: int = 0  # map-reduce only: articles that fell back
    input_links: list[str] = field(default_factory=list)  # links given to the model
    unknown_sources: list[str] = field(default_factory=list)  # cited, not in input


def _usage_info(raw_usages):
    """Add up the usage of every LLM call. Returns None if nothing was billed."""
    raw_usages = [u for u in raw_usages if u is not None]
    if not raw_usages:
        return None
    return UsageInfo(
        input_tokens=sum(u.input_tokens for u in raw_usages),
        cached_tokens=sum(u.input_tokens_details.cached_tokens for u in raw_usages),
        output_tokens=sum(u.output_tokens for u in raw_usages),
        cost=sum(calculate_cost(u) for u in raw_usages),
    )


def generate_briefing():
    articles = []
    hits = misses = 0
    for feed in FEEDS:
        log.info("Fetching articles from %s", feed)
        try:
            feed_articles, feed_hits = fetch_articles(feed)
        except Exception:
            log.exception("Error fetching articles from %s", feed)
            continue
        if not feed_articles:
            log.warning("No articles found in %s", feed)
            continue
        articles.extend(feed_articles)
        hits += feed_hits
        misses += len(feed_articles) - feed_hits

    if not articles:
        raise NoArticlesError("No articles found in any feed.")

    articles = deduplicate_articles(sort_articles(articles))

    failed_summaries = 0
    if len(articles) > MAP_REDUCE_THRESHOLD:
        mode = "map-reduce"
        map_results = summarize_each(articles)
        failed_summaries = sum(r.failed for r in map_results)
        cached = sum(r.from_cache for r in map_results)
        log.info(
            "map step: %d new, %d cached, %d failed",
            len(map_results) - cached - failed_summaries,
            cached,
            failed_summaries,
        )
        summarized = [
            {**article, "summary": result.summary}
            for article, result in zip(articles, map_results)
        ]
        briefing, reduce_usages = summarize_articles(build_summaries_xml(summarized))
        raw_usages = [r.usage for r in map_results] + reduce_usages
    else:
        mode = "single"
        briefing, raw_usages = summarize_articles(build_articles_xml(articles))

    input_links = [article["link"] for article in articles]
    unknown_sources = find_unknown_sources(briefing, input_links)
    if unknown_sources:
        log.warning(
            "The briefing cites %d link(s) that were not in the input: %s",
            len(unknown_sources),
            ", ".join(unknown_sources),
        )

    return BriefingResult(
        briefing=briefing,
        article_count=len(articles),
        sources=sorted({a["source"] for a in articles}),
        usage=_usage_info(raw_usages),
        cache_hits=hits,
        cache_misses=misses,
        generated_at=datetime.now(timezone.utc),
        mode=mode,
        failed_summaries=failed_summaries,
        input_links=input_links,
        unknown_sources=unknown_sources,
    )