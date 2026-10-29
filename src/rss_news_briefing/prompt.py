from xml.sax.saxutils import escape

from .config import MAX_CHARS

# Used for the single-call mode (full article texts) and for the final
# "reduce" call in map-reduce mode (one short summary per article).
# The answer must be JSON that matches models.Briefing.
INSTRUCTIONS = """You are a news analyst who writes concise briefings.
Rules:
- Use only information from the provided articles. Do not add outside facts.
- Group related stories into themes, and merge duplicates covering the same event.
- Every bullet must cite at least one source. A source is the exact URL from an article's <link> tag. Never invent, shorten, or change a URL.
- If articles conflict, say so in the bullet instead of picking one.
- Skip trivial or promotional items.
Respond with a single JSON object and nothing else: no markdown code fences and no commentary. Use exactly this shape:
{
  "overview": "2-3 sentences on the main stories",
  "themes": [
    {
      "title": "short theme title",
      "bullets": [
        {"text": "one sentence", "sources": ["https://example.com/article"]}
      ]
    }
  ],
  "worth_watching": "one line"
}
Use at most 5 themes and between 1 and 4 bullets per theme. Keep the whole briefing under 300 words."""

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


def build_retry_input(articles_xml, previous_output, error_text):
    """Input for the second attempt after the first answer failed validation."""
    return (
        f"{articles_xml}\n\n"
        "Your previous answer was rejected.\n"
        f"<previous_answer>{escape(previous_output[:4000])}</previous_answer>\n"
        f"<validation_error>{escape(error_text[:1000])}</validation_error>\n"
        "Return the corrected JSON object only, in the required shape."
    )