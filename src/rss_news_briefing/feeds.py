import feedparser
from trafilatura import extract, fetch_url
import calendar
import logging
from .config import MAX_PER_FEED
from .cache import load_cached_text, save_cached_article_text

log = logging.getLogger(__name__)

def fetch_articles(feed_url):
    feed = feedparser.parse(feed_url)
    status = feed.get("status")
    if status and status >= 400:
        log.error("%s returned HTTP %s", feed_url, status)
        return [],0
    if feed.bozo and not feed.entries:
        log.error("Could not read %s: %s", feed_url, feed.get("bozo_exception"))
        return [],0

    articles = []
    hits = 0
    for entry in feed.entries[:MAX_PER_FEED]:
        summary = entry.get("summary", "")
        text = load_cached_text(entry.link)
        if text is not None:
            hits += 1
        else:
            downloaded = fetch_url(entry.link)
            text = extract(downloaded) if downloaded else None
            if text:
                save_cached_article_text(
                    entry.link, text
                )  # cache real extractions only
            else:
                text = summary  # fallback, deliberately not cached

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
    return articles, hits

def deduplicate_articles(articles):
    """Remove duplicate articles based on their link."""
    seen_links = set()
    unique_articles = []
    for article in articles:
        if article["link"] not in seen_links:
            seen_links.add(article["link"])
            unique_articles.append(article)
    return unique_articles

def sort_articles(articles):
    return sorted(articles,key=lambda x: x["timestamp"], reverse=True)