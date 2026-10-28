import logging

from .pipeline import NoArticlesError, generate_briefing

log = logging.getLogger(__name__)


def main():

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = generate_briefing()
    except NoArticlesError as e:
        log.error("%s", e)
        return

    log.info("cache: %d hits, %d misses", result.cache_hits, result.cache_misses)
    print(result.briefing)
    if usage := result.usage is not None:
        log.info(
            "\ntokens: %d in (%d cached), %d out | est. cost: $%.6f",
            usage.input_tokens,
            usage.cached_tokens,
            usage.output_tokens,
            usage.cost,
        )


if __name__ == "__main__":
    main()
