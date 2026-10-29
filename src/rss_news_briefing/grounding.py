from dataclasses import dataclass
from html import unescape
from urllib.parse import urlsplit, urlunsplit


def normalize_url(url):
    """Make harmless differences between two spellings of a URL disappear.

    Ignored: surrounding whitespace, HTML escaping (&amp;), upper/lower case in
    the scheme and host, a trailing slash, and a #fragment. Anything else, such
    as a different path, query, or http vs https, still counts as different.
    """
    parts = urlsplit(unescape(url.strip()))
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            parts.query,
            "",
        )
    )


def cited_urls(briefing):
    """Every distinct URL the briefing cites, in order of first appearance."""
    seen = set()
    urls = []
    for theme in briefing.themes:
        for bullet in theme.bullets:
            for url in bullet.sources:
                key = normalize_url(url)
                if key not in seen:
                    seen.add(key)
                    urls.append(url)
    return urls


def find_unknown_sources(briefing, input_links):
    """Cited URLs that were NOT in the input. These are the hallucinated ones."""
    known = {normalize_url(link) for link in input_links}
    return [url for url in cited_urls(briefing) if normalize_url(url) not in known]


def find_uncited_links(briefing, input_links):
    """Input article links that the briefing never cites."""
    cited = {normalize_url(url) for url in cited_urls(briefing)}
    seen = set()
    uncited = []
    for link in input_links:
        key = normalize_url(link)
        if key not in cited and key not in seen:
            seen.add(key)
            uncited.append(link)
    return uncited


@dataclass
class GroundingReport:
    theme_count: int
    bullet_count: int
    input_link_count: int  # distinct links given to the model
    cited_count: int  # distinct links the briefing cites
    unknown_sources: list[str]
    uncited_links: list[str]
    coverage: float  # share of input links that the briefing cites (0 to 1)

    @property
    def passed(self):
        return not self.unknown_sources


def check_briefing(briefing, input_links):
    distinct_inputs = {normalize_url(link) for link in input_links}
    uncited = find_uncited_links(briefing, input_links)
    coverage = 0.0
    if distinct_inputs:
        coverage = (len(distinct_inputs) - len(uncited)) / len(distinct_inputs)
    return GroundingReport(
        theme_count=len(briefing.themes),
        bullet_count=sum(len(theme.bullets) for theme in briefing.themes),
        input_link_count=len(distinct_inputs),
        cited_count=len(cited_urls(briefing)),
        unknown_sources=find_unknown_sources(briefing, input_links),
        uncited_links=uncited,
        coverage=coverage,
    )


def format_report(report):
    lines = [
        "Briefing evaluation",
        f" themes: {report.theme_count}, bullets: {report.bullet_count}",
        f" articles given to the model: {report.input_link_count}",
        (
            f" distinct links cited: {report.cited_count} "
            f"(coverage {report.coverage:.0%})"
        ),
        f" links cited that were not in the input: {len(report.unknown_sources)}",
        f" result: {'PASS' if report.passed else 'FAIL'}",
    ]
    if report.unknown_sources:
        lines += ["", "Unknown links (possible hallucinations):"]
        lines += [f"  - {url}" for url in report.unknown_sources]
    if report.uncited_links:
        lines += ["", "Articles the briefing never cites:"]
        lines += [f"  - {url}" for url in report.uncited_links]
    return "\n".join(lines)
