from .config import INPUT_PRICE,CACHED_INPUT_PRICE,OUTPUT_PRICE,MODEL
from .prompt import INSTRUCTIONS
from .cache import briefing_cache_path,load_cached_briefing,save_cached_briefing
import logging
from decouple import config
from openai import OpenAI

log = logging.getLogger(__name__)

def summarize_articles(articles_xml):
    path = briefing_cache_path(articles_xml,MODEL,INSTRUCTIONS)
    cached = load_cached_briefing(path)
    if cached is not None:
        log.info("Using cached briefing (no API call)")
        return cached, None

    client = OpenAI(api_key=config("API-KEY"))
    response = client.responses.create(
        model=MODEL,
        instructions=INSTRUCTIONS,
        input=articles_xml,
        store=True,
    )
    save_cached_briefing(path, response.output_text)
    return response.output_text, response.usage

def calculate_cost(usage):
    """Estimate the cost in USD. input_tokens already includes cached tokens."""
    cached = usage.input_tokens_details.cached_tokens
    uncached = usage.input_tokens - cached
    return (
        uncached * INPUT_PRICE
        + cached * CACHED_INPUT_PRICE
        + usage.output_tokens * OUTPUT_PRICE
    ) / 1_000_000