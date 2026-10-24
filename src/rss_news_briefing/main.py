import logging
from xml.sax.saxutils import escape


import feedparser
from decouple import config
from openai import OpenAI
from trafilatura import extract, fetch_url


logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


FEED_URL = "https://www.bbc.com/culture/feed.rss"
MODEL = "gpt-6-luna"
MAX_CHARS = 1500


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
    articles = []
    for entry in feed.entries:
        summary = entry.get("summary", "")
        downloaded = fetch_url(entry.link)
        # fetch_url/extract return None on failure, so fall back to the RSS summary
        text = (extract(downloaded) if downloaded else None) or summary
        articles.append(
            {
                "title": entry.title,
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary": summary,
                "text": text,
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




def main():
    articles = get_articles(FEED_URL)
    if not articles:
        print("No articles found in the feed.")
        return


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

