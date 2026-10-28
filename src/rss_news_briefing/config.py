import pathlib

CACHE_DIR = pathlib.Path(".cache")
ARTICLES_DIR = pathlib.Path(CACHE_DIR / "articles")
OUTPUT_DIR = pathlib.Path(CACHE_DIR / "output")
SUMMARIES_DIR = pathlib.Path(CACHE_DIR / "summaries")

FEEDS = [
    "https://www.bbc.com/culture/feed.rss",
    "https://techcrunch.com/feed/",
]
MODEL = "gpt-6-luna"
MAX_CHARS = 1500
MAX_PER_FEED = 10  # Max articles to fetch per feed. Set to None for no limit.
CACHE_TTL_HOURS = (
    24  # Cache articles for this many hours. Set to None for no expiration.
)
BRIEFING_TTL_MINUTES = 10  # how long /briefing reuses its last result
# USD per 1M tokens. Last checked 2026-10-24; verify against the pricing page.
INPUT_PRICE = 0.10
CACHED_INPUT_PRICE = 0.01
OUTPUT_PRICE = 0.50
MAP_REDUCE_THRESHOLD = 15  # more articles than this: summarize each one first
MAX_WORKERS = 4  # per-article calls running at the same time
MAP_MAX_SUMMARY_CHARS = 6000  # article text sent in each per-article call
LLM_TIMEOUT_SECONDS = 60
LLM_MAX_RETRIES = 3
