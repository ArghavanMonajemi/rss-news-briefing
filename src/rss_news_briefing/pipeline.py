import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import FEEDS
from .feeds import fetch_articles, sort_articles, deduplicate_articles
from .llm import summarize_articles, calculate_cost
from .prompt import build_articles_xml

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
    briefing: str
    article_count: int
    sources: list[str]
    usage: UsageInfo | None  # None when served from the briefing cache
    cache_hits: int
    cache_misses: int
    generated_at: datetime


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
    briefing, usage = summarize_articles(build_articles_xml(articles))

    usage_info = None
    if usage is not None:
        usage_info = UsageInfo(
            input_tokens=usage.input_tokens,
            cached_tokens=usage.input_tokens_details.cached_tokens,
            output_tokens=usage.output_tokens,
            cost=calculate_cost(usage),
        )

    return BriefingResult(
        briefing=briefing,
        article_count=len(articles),
        sources=sorted({a["source"] for a in articles}),
        usage=usage_info,
        cache_hits=hits,
        cache_misses=misses,
        generated_at=datetime.now(timezone.utc),
    )
