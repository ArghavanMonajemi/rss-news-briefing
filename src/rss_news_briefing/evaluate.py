"""Run the pipeline once and check that the briefing is grounded in its input.

    uv run python -m rss_news_briefing.evaluate

Exit code 0: every cited link was in the input.
Exit code 1: the briefing cites at least one link that was not (a hallucination).
Exit code 2: no articles could be fetched, so there was nothing to evaluate.

This calls the real feeds and (unless cached) the real API, so it is a tool
for you to run by hand. It is not part of the automated test suite or CI.
"""

import logging
import sys

from .grounding import check_briefing, format_report
from .pipeline import NoArticlesError, generate_briefing


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = generate_briefing()
    except NoArticlesError as error:
        print(error)
        return 2

    report = check_briefing(result.briefing, result.input_links)
    print(format_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
