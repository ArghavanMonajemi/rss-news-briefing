import pathlib

CACHE_DIR = pathlib.Path(".cache")
ARTICLES_DIR = pathlib.Path(CACHE_DIR / "articles")
OUTPUT_DIR = pathlib.Path(CACHE_DIR / "output")

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
# USD per 1M tokens. Last checked 2026-10-24; verify against the pricing page.
INPUT_PRICE = 0.10
CACHED_INPUT_PRICE = 0.01
OUTPUT_PRICE = 0.50