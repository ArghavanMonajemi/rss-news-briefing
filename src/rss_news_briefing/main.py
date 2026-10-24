import logging
from xml.sax.saxutils import escape
import calendar
import feedparser
from decouple import config
from openai import OpenAI
from trafilatura import extract, fetch_url


logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


FEEDS = [
    "https://www.bbc.com/culture/feed.rss",
    "https://techcrunch.com/feed/",
]
MODEL = "gpt-6-luna"
MAX_CHARS = 1500
MAX_PER_FEED = 10  # Max articles to fetch per feed. Set to None for no limit.

# USD per 1M tokens. Last checked 2026-10-24; verify against the pricing page.
INPUT_PRICE = 0.10
CACHED_INPUT_PRICE = 0.01
OUTPUT_PRICE = 0.50

INSTRUCTIONS = """You are a news analyst who writes concise briefings.
Rules:
- Use only information from the provided articles. Do not add outside facts.
- Group related stories into themes, and merge duplicates covering the same event.
- Cite sources by including their links.
- If articles conflict, say so instead of picking one.
- Skip trivial or promotional items.
Write a briefing with:
1. A 2-3 sentence overview of the main stories.
2. Up to 5 themed sections, each with 2-4 bullet points.
3. A one-line "worth watching" note at the end.
Keep it under 300 words."""


def get_articles(feed_url):
    feed = feedparser.parse(feed_url)
    status = feed.get("status") 
    if status and status >= 400: 
        log.error("%s returned HTTP %s", feed_url, status) 
        return [] 
    if feed.bozo and not feed.entries: 
        log.error("Could not read %s: %s", feed_url, feed.get("bozo_exception")) 
        return [] 


    articles = []
    for entry in feed.entries[:MAX_PER_FEED]:
        summary = entry.get("summary", "")
        downloaded = fetch_url(entry.link)
        # fetch_url/extract return None on failure, so fall back to the RSS summary
        text = (extract(downloaded) if downloaded else None) or summary
        parsed = entry.get("published_parsed")
        timestamp = calendar.timegm(parsed) if parsed else 0
        articles.append(
            {
                "source": feed.feed.get("title", feed_url),
                "title": entry.title,
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary": summary,
                "text": text,
                "timestamp": timestamp,
            }
        )
    return articles


def build_articles_xml(articles, max_chars=MAX_CHARS):
    parts = ["<articles>"]
    for i, article in enumerate(articles):
        parts.append(
            "  <article>\n"
            f"    <id>{i}</id>\n"
            f"    <title>{escape(article['title'])}</title>\n"
            f"    <published>{escape(article['published'])}</published>\n"
            f"    <link>{escape(article['link'])}</link>\n"
            f"    <source>{escape(article['source'])}</source>\n"
            f"    <summary>{escape(article['summary'])}</summary>\n"
            f"    <text>{escape(article['text'][:max_chars])}</text>\n"
            "  </article>"
        )
    parts.append("</articles>")
    return "\n".join(parts)


def calculate_cost(usage):
    """Estimate the cost in USD. input_tokens already includes cached tokens."""
    cached = usage.input_tokens_details.cached_tokens
    uncached = usage.input_tokens - cached
    return (
        uncached * INPUT_PRICE
        + cached * CACHED_INPUT_PRICE
        + usage.output_tokens * OUTPUT_PRICE
    ) / 1_000_000


def summarize(articles_xml):
    client = OpenAI(api_key=config("API-KEY"))
    response = client.responses.create(
        model=MODEL,
        instructions=INSTRUCTIONS,
        input=articles_xml,
        store=True,
    )
    return response.output_text, response.usage


def deduplicate_articles(articles):
    """Remove duplicate articles based on their link."""
    seen_links = set()
    unique_articles = []
    for article in articles:
        if article["link"] not in seen_links:
            seen_links.add(article["link"])
            unique_articles.append(article)
    return unique_articles


def main():
    articles = []
    for feed in FEEDS:
        log.info("Fetching articles from %s", feed)
        try:
            feed_articles = get_articles(feed)
        except Exception as e:
            log.error("Error fetching articles from %s: %s", feed, e)
            continue
        if not feed_articles:
            log.warning("No articles found in %s", feed)
            continue
        articles.extend(feed_articles)

    if not articles:
        log.error("No articles found in any feed.")
        return

    articles.sort(key=lambda x: x["timestamp"], reverse=True)
    articles = deduplicate_articles(articles)
    briefing, usage = summarize(build_articles_xml(articles))

    print(briefing)

    log.info(
        "\ntokens: %d in (%d cached), %d out | est. cost: $%.6f",
        usage.input_tokens,
        usage.input_tokens_details.cached_tokens,
        usage.output_tokens,
        calculate_cost(usage),
    )


if __name__ == "__main__":
    main()
