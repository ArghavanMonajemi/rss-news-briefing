import hashlib
import json
import time

from .config import ARTICLES_DIR, CACHE_TTL_HOURS, OUTPUT_DIR


def url_to_filename(url):
    """Convert a URL to a safe filename for caching."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def cache_article_path(url):
    return ARTICLES_DIR / f"{url_to_filename(url)}.json"


def save_cached_article_text(url, text):
    ARTICLES_DIR.mkdir(exist_ok=True, parents=True)
    cache_article_path(url).write_text(json.dumps({"text": text}), encoding="utf-8")


def load_cached_text(url):
    """Return cached text, or None on a miss, expiry, or unreadable file."""
    path = cache_article_path(url)
    try:
        if CACHE_TTL_HOURS is not None:
            age = time.time() - path.stat().st_mtime
            if age > CACHE_TTL_HOURS * 3600:
                return None
        return json.loads(path.read_text(encoding="utf-8"))["text"]
    except FileNotFoundError, json.JSONDecodeError, KeyError:
        return None


def briefing_cache_path(articles_xml, model, instructions):
    """Cache key covers everything that affects the output."""
    key = json.dumps([model, instructions, articles_xml]).encode("utf-8")
    return OUTPUT_DIR / f"{hashlib.sha256(key).hexdigest()}.txt"


def load_cached_briefing(path):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def save_cached_briefing(path, briefing):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(briefing, encoding="utf-8")
