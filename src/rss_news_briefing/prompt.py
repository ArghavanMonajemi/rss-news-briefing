from xml.sax.saxutils import escape

from .config import MAX_CHARS

# Used for the single-call mode (full article texts) and for the final
# "reduce" call in map-reduce mode (one short summary per article).
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

# Used for the per-article "map" calls.
MAP_INSTRUCTIONS = """You summarize one news article for a briefing editor.
Rules:
- Use only information from the article. Do not add outside facts.
- Write 2-3 sentences covering who, what, and the key facts or numbers.
- If the article is promotional or trivial, say so in one short sentence.
- Do not include links or URLs."""


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


def build_map_input(article, max_chars):
    """Input for one per-article (map) call.

    The link is deliberately left out. The code attaches it later, so the
    model never has a chance to misquote it.
    """
    return (
        "<article>\n"
        f"  <title>{escape(article['title'])}</title>\n"
        f"  <source>{escape(article['source'])}</source>\n"
        f"  <published>{escape(article['published'])}</published>\n"
        f"  <text>{escape(article['text'][:max_chars])}</text>\n"
        "</article>"
    )


def build_summaries_xml(articles):
    """Input for the final (reduce) call: one short summary per article.

    Each article's "summary" field must already hold the model-written
    summary. The full text is not included.
    """
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
            "  </article>"
        )
    parts.append("</articles>")
    return "\n".join(parts)
