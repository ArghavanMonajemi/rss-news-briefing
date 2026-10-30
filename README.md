# RSS News Briefing

![CI](https://github.com/ArghavanMonajemi/rss-news-briefing/actions/workflows/ci.yml/badge.svg)

A Python tool that reads several news sites' RSS feeds, extracts the full text of each article, and asks an LLM to write one short, themed briefing as **validated JSON** in which every bullet cites its sources. It checks that every cited link was really in the input, so invented links are caught. Use it from the command line or as a small HTTP API.

This is my first AI engineering project. It started as a CSV of pasted headlines summarized with a single API call. It grew into a cached, multi-feed pipeline with map-reduce summarization, structured and validated output, a hallucinated-link check, a FastAPI service, an offline test suite, and CI.

## Highlights

- **Structured output.** The briefing is JSON (overview, themes, bullets, sources) validated with Pydantic. An invalid answer is retried once with the validation error attached, and an answer that is still invalid is never cached or shown.
- **Grounding check.** Every URL the briefing cites is compared with the links that were in the input. Links that were not in the input are reported on every run and in the API response, and a script runs a full evaluation.
- **Scales with the input.** Small batches use one LLM call. Large batches use map-reduce: each article is summarized separately (several at a time, with per-article caching and graceful fallbacks), then one final call writes the briefing.
- **Cached at every layer**, so re-runs are fast and cheap.
- **Cost-aware.** Token usage and estimated cost are reported across all calls, including retries.
- **Tested offline.** The whole suite runs without network access or an API key, and CI runs lint, format check, and tests on every push.

## How it works

```
RSS feeds ──► feedparser ──► articles per feed (capped, with source + timestamp)
                                   │
                                   ▼
                  article-text cache ──hit──► cached text
                         │ miss
                         ▼
                  trafilatura (fetch + extract full text,
                  falls back to the RSS summary on failure)
                                   │
                                   ▼
            combine ──► sort newest first ──► deduplicate by link
                                   │
                  ┌────────────────┴─────────────────┐
         few articles                          many articles
                  │                                  │
                  │                        MAP: one short summary per
                  │                        article, run in parallel
                  │                        (cached, with fallbacks)
                  │                                  │
                  ▼                                  ▼
          full texts as XML                  short summaries as XML
                  └────────────────┬─────────────────┘
                                   ▼
                  briefing cache ──hit──► cached briefing (no API call)
                         │ miss
                         ▼
                  LLM call (OpenAI API) ──► JSON
                         │
                         ▼
                  Pydantic validation ── invalid ──► one retry with the error
                         │ valid                              │ still invalid
                         ▼                                    ▼
                  saved to the cache                  BriefingFormatError
                         │
                         ▼
                  grounding check: were all cited links in the input?
                         │
                         ▼
                  BriefingResult (briefing, feeds, usage, cost, unknown links)
                         │                          │
                         ▼                          ▼
               CLI: rendered text           API: JSON response
```

1. **Fetch the feeds** with [`feedparser`](https://github.com/kurtmckee/feedparser). Each feed contributes at most `MAX_PER_FEED` articles so no single source dominates. A feed that fails or comes back empty is logged and skipped, and the run continues with the others.
2. **Extract article text** with [`trafilatura`](https://github.com/adbar/trafilatura), which pulls the main content out of each page and drops navigation, ads, and footers. Extracted text is cached on disk. If a page can't be fetched or extracted, the pipeline falls back to the RSS summary (and does not cache that fallback).
3. **Combine, sort, and deduplicate.** Articles from all feeds are sorted newest first using the feed's parsed timestamp, then duplicates (same link) are removed so the newest copy is kept.
4. **Choose a mode.** Up to `MAP_REDUCE_THRESHOLD` articles are sent in a single call. Above it, map-reduce runs (see below).
5. **Build the input.** Articles are wrapped in XML tags so the model can tell the pieces apart. Special characters are escaped, and text is truncated to keep token usage under control.
6. **Summarize.** The rules are sent as separate instructions and the articles as the input. The model must answer with one JSON object, use only the provided articles, merge duplicates, flag conflicts, skip trivial items, and cite every bullet with the exact URL from an article's `<link>` tag.
7. **Validate.** The answer is parsed (a markdown code fence is tolerated) and validated against the `Briefing` model. If it fails, the call is repeated once with the rejected answer and the validation error. Only a valid briefing is cached.
8. **Check the grounding.** Cited URLs are compared with the links that were in the input, ignoring harmless differences such as a trailing slash or `&amp;`. Unknown links are logged and returned, never silently removed.
9. **Report the result.** `generate_briefing()` returns a plain `BriefingResult` object. The CLI renders it as text, and the API converts it to a validated JSON response.

### Map-reduce mode

With many articles, one prompt would grow with every article. Map-reduce keeps each call small:

- **Map:** each article gets its own short LLM call (2-3 sentences), up to `MAX_WORKERS` at a time. Results keep the input order. Summaries are cached per article, so a re-run only summarizes new articles. If a call fails or returns nothing, that article falls back to its feed summary, the failure is not cached, and the run continues.
- **Reduce:** one final call writes the briefing from the short summaries. The links are attached by the code, not written by the model, so the model never has a chance to misquote one.

Map-reduce uses more total tokens than a single call until the input stops fitting in one prompt, so the threshold matters. Usage and cost are added up across every call, including retries.

### The briefing

```
Briefing
├── overview          2-3 sentences on the main stories
├── themes            1 to 5
│   ├── title
│   └── bullets       1 to 4 per theme
│       ├── text
│       └── sources   at least one URL, copied from the input
└── worth_watching    one line
```

## Example output

Command line:

```
```

## Requirements

- Python 3.10+ (see `pyproject.toml` for the exact version)
- [uv](https://docs.astral.sh/uv/) for dependency management
- An OpenAI API key

Runtime dependencies: `openai`, `python-decouple`, `feedparser`, `trafilatura`, `pydantic`, `fastapi`, `uvicorn`
Development dependencies: `pytest`, `httpx`, `ruff`

## Setup

```bash
git clone https://github.com/ArghavanMonajemi/rss-news-briefing.git
cd rss-news-briefing
uv sync
```

`uv sync` installs both the runtime and the development dependencies.

Create a `.env` file in the project root:

```
API-KEY=your_openai_api_key_here
```

If the key is missing, the CLI stops with an error instead of calling the API, and the API server refuses to start.

> `.env` and `.cache/` are listed in `.gitignore`. Never commit your API key.

## Usage

### Command line

```bash
uv run python -m rss_news_briefing
```

The briefing is printed to stdout as readable text, with a `Sources:` line under each bullet. Log lines (cache hits and misses, mode, token usage, estimated cost, warnings) go to stderr, so the briefing can be piped or redirected on its own.

### HTTP API

```bash
uv run uvicorn rss_news_briefing.api:app --reload
```

Run it from the project root. Then open <http://127.0.0.1:8000/docs> for interactive documentation.

| Endpoint | Description |
|---|---|
| `GET /health` | Returns `{"status": "ok"}`. Does no fetching and makes no LLM call. |
| `GET /briefing` | Runs the pipeline for the configured feeds and returns the briefing as JSON. |

Example response shape from `GET /briefing`:

```json
{
  "briefing": {
    "overview": "...",
    "themes": [
      {
        "title": "...",
        "bullets": [
          {"text": "...", "sources": ["https://example.com/article"]}
        ]
      }
    ],
    "worth_watching": "..."
  },
  "article_count": 18,
  "sources": ["BBC News", "TechCrunch"],
  "generated_at": "2026-10-28T12:00:00Z",
  "cached": false,
  "mode": "single",
  "failed_summaries": 0,
  "unknown_sources": [],
  "usage": {
    "input_tokens": 0,
    "cached_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0
  }
}
```

- `briefing` is a structured object. (Earlier versions returned plain text in this field.)
- `sources` lists the feeds the articles came from. The links cited inside the briefing are in each bullet's own `sources`.
- `unknown_sources` lists cited links that were **not** in the input. It should always be empty. If it isn't, the briefing contains a link the model made up.
- `mode` is `"single"` or `"map-reduce"`, and `failed_summaries` counts articles that fell back to their feed summary (map-reduce only).
- `cached` is `true` when the response came from the API's in-memory cache.
- `usage` is `null` when nothing was billed, because everything came from a cache.

| Status | Meaning |
|---|---|
| `503` | No feed produced any articles. |
| `502` | The summarization request failed, or the model never produced a valid briefing. Details are logged on the server, not returned. |

### Checking a briefing for invented links

```bash
uv run python -m rss_news_briefing.evaluate
```

Runs the pipeline once and prints a report: the number of themes and bullets, how many articles were given to the model, how many distinct links the briefing cites (and what share of the input that covers), and any cited link that was not in the input.

| Exit code | Meaning |
|---|---|
| `0` | Every cited link was in the input. |
| `1` | At least one cited link was not in the input. |
| `2` | No articles could be fetched, so there was nothing to evaluate. |

This calls the real feeds and (unless cached) the real API, so it is a tool to run by hand. It is not part of the test suite or CI. The comparison logic itself is covered by offline tests.

### Configuration

These settings are constants in `src/rss_news_briefing/config.py`:

| Setting | Constant | Purpose |
|---|---|---|
| Feed URLs | `FEEDS` | Which feeds to read |
| Articles per feed | `MAX_PER_FEED` | `None` for no limit |
| Characters per article (single mode) | `MAX_CHARS` | Truncation of the full text |
| Article cache lifetime in hours | `CACHE_TTL_HOURS` | `None` for no expiry |
| API in-memory cache lifetime in minutes | `BRIEFING_TTL_MINUTES` | How long `/briefing` reuses a result |
| Map-reduce threshold | `MAP_REDUCE_THRESHOLD` | More articles than this switches to map-reduce |
| Characters per article (map step) | `MAP_MAX_CHARS` | Text sent in each per-article call |
| Parallel per-article calls | `MAX_WORKERS` | Lower it if you hit rate limits |
| Request timeout and retries | `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES` | Handled by the OpenAI client, with backoff |
| Extra attempts for invalid JSON | `MAX_FORMAT_RETRIES` | `0` disables the retry |
| Model | `MODEL` | |
| Prices (USD per 1M tokens) | `INPUT_PRICE`, `CACHED_INPUT_PRICE`, `OUTPUT_PRICE` | Used for the cost estimate |
| Prompt and rules | `INSTRUCTIONS`, `MAP_INSTRUCTIONS` | In `prompt.py` |

The API always uses the feeds from `FEEDS`. Clients cannot supply their own URLs.

> **Cost figures are estimates.** They are calculated from the price constants in the config, which may become outdated. Check your provider's pricing page and update them when needed. More feeds mean more tokens, so watch the usage figures when you add sources.

### Caching

There are four layers, all under `.cache/` except the last:

- **Article text** (`.cache/articles/`): extracted text per article URL, expiring after `CACHE_TTL_HOURS`. A second run skips downloading anything it already has.
- **Per-article summaries** (`.cache/summaries/`): the map step's output, keyed by a hash of the model, the map instructions, and the article input.
- **Briefings** (`.cache/output/`): the finished briefing as JSON, keyed by a hash of the model, the instructions, and the exact input. Changing any of them produces a new key, so stale results are never reused. A cached entry that no longer validates is ignored and replaced.
- **API memory cache**: the API keeps its latest result for `BRIEFING_TTL_MINUTES` and uses a lock, so simultaneous requests share one pipeline run instead of each starting their own.

To force a fresh run, delete the `.cache/` folder (or one of its subfolders) and restart the API.

## Development

```bash
uv run pytest                  # run the tests
uv run ruff check .            # lint
uv run ruff format .           # format
```

### Tests

The tests run offline and need no API key. Feed parsing, page downloads, and the OpenAI client are faked, and every test writes its cache files to a temporary folder, so your real `.cache/` is never touched.

They cover:

- prompt building (escaping, truncation, ids) and the structured output models (required fields, limits, fenced JSON, invalid answers)
- all three caches (hits, misses, corrupt files, expiry, cache keys)
- cost calculation, including cached tokens
- feed fetching (summary fallback, per-feed cap, broken feeds, sorting, deduplication)
- the map step (ordering, parallelism limit, caching, failures and fallbacks)
- the retry on invalid JSON (what is sent, what is billed, what is never cached)
- the grounding check (URL normalization, invented links, coverage) and the evaluate script's exit codes
- pipeline orchestration (one failing feed doesn't stop the others, mode switch, usage added up across calls)
- the API (structured responses, in-memory cache, error codes, concurrent requests, startup checks)

### Continuous integration

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push to `main` and on every pull request. It installs the locked dependencies with `uv sync --locked`, then runs `ruff check`, `ruff format --check`, and `pytest`. It needs no secrets, because the tests never call the real API.

To reproduce the CI run locally:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Keep `ruff` in the development dependencies (`uv add --dev ruff`) and commit `uv.lock`. CI installs only what the lock file lists, so a tool installed globally on your machine won't exist there.

## Project structure

```
rss-news-briefing/
├── .github/
│   └── workflows/
│       └── ci.yml          # lint, format check, and tests on every push
├── src/
│   └── rss_news_briefing/
│       ├── __init__.py
│       ├── __main__.py     # enables `python -m rss_news_briefing`
│       ├── config.py       # constants: feeds, model, prices, TTLs, limits, cache paths
│       ├── models.py       # Briefing, Theme, Bullet (Pydantic) and the JSON parser
│       ├── cache.py        # article, summary, and briefing caches
│       ├── feeds.py        # fetch articles, sort, deduplicate
│       ├── prompt.py       # instructions and XML input builders
│       ├── llm.py          # map step, briefing call with validation and retry, cost
│       ├── grounding.py    # checks that cited links were in the input
│       ├── pipeline.py     # generate_briefing(): the one function everything calls
│       ├── render.py       # structured briefing -> readable text
│       ├── schemas.py      # Pydantic response models for the API
│       ├── api.py          # FastAPI app: /health and /briefing
│       ├── cli.py          # command-line entry point
│       └── evaluate.py     # run once and report invented links
├── tests/                  # pytest suite (runs offline)
│   ├── conftest.py         # shared fixtures: cache isolation, factories
│   ├── test_prompt.py
│   ├── test_models.py
│   ├── test_cache.py
│   ├── test_feeds.py
│   ├── test_llm.py
│   ├── test_map_reduced.py
│   ├── test_grounding.py
│   ├── test_render_and_evaluate.py
│   ├── test_pipeline.py
│   └── test_api.py
├── pyproject.toml          # project metadata and dependencies (uv)
├── uv.lock                 # locked dependency versions
├── .cache/                 # caches (not committed)
├── .env                    # your API key (not committed)
└── README.md
```

Dependencies point one way: `config` ← `models`, `cache`, `feeds`, `prompt` ← `llm`, `grounding` ← `pipeline` ← `cli`, `api`, `evaluate`. Only the CLI prints, and only the API deals with HTTP.

## Design decisions

- **RSS instead of scraping HTML.** Feeds are structured and stable, so there are no custom selectors that break when a site changes its layout.
- **trafilatura for article bodies.** It works across many sites without per-site code.
- **Fallbacks instead of crashes.** A failed download falls back to the feed summary, a failed per-article summary falls back to the feed summary, and one bad feed doesn't stop the run. Fallbacks are never cached, so a temporary error doesn't stick.
- **Per-feed cap.** Keeps one high-volume source from crowding out the others and bounds token usage.
- **Sort by parsed timestamp, not the date string.** Date strings sort alphabetically, not chronologically. Articles without a date sink to the bottom.
- **Sort first, then deduplicate.** When the same link appears twice, the newest copy is kept, and article ids stay sequential.
- **Cache only the extracted text.** Titles, summaries, and dates always come fresh from the feed, so cached entries can't serve stale metadata.
- **Cache keys cover everything that affects the output.** The model, the prompt, and the input are hashed, so changing any of them invalidates the old result automatically.
- **Escaped, XML-tagged input.** Clear boundaries between articles make the input easier for the model to use, and escaping keeps the structure valid whatever the headlines contain.
- **Prompt plus Pydantic validation for structured output.** It works with any model, and it gives one place to catch bad output and retry. A schema-constrained API feature would be a possible upgrade.
- **Every bullet must cite a source.** The schema enforces at least one source per bullet, so consumers of the API can rely on it.
- **Never cache an invalid answer.** Only a briefing that passed validation is saved.
- **The code attaches links in map-reduce mode.** The per-article prompt never sees the URL, so the model can't misquote it.
- **Report invented links, don't silently delete them.** A hidden fix would hide the problem. The check strips only harmless differences (case, trailing slash, `&amp;`). A changed path or query still counts as a different link.
- **Grounding is a pure function.** It needs no network, so it runs on every request and is fully unit-tested.
- **Results keep input order under concurrency.** Parallel calls finish in any order, but each result is placed back at its article's position.
- **Hardcoded prices instead of scraping a pricing page.** A cost estimate should never be able to break the run or depend on a web page's layout.
- **Pipeline returns data, interfaces present it.** `generate_briefing()` never prints. The CLI renders text, and the API has its own response models, so either can change without touching the core.
- **Plain `def` endpoints.** The pipeline is blocking, so FastAPI runs it in a worker thread instead of freezing the event loop.
- **Lock around regeneration.** When the API's cached result expires, simultaneous requests wait for one pipeline run instead of starting several (and paying for several LLM calls).
- **Errors are mapped, not leaked.** Failures become `503` or `502` with a short message, and details stay in the server log.
- **Fixed feeds in the API.** Letting callers submit URLs would make the server fetch arbitrary addresses, which needs real protection against server-side request forgery first. That is deliberately out of scope.
- **Everything faked in tests.** No network, no API key, and a temporary cache folder per test, so the suite is fast, free, and safe to run in CI.

## Limitations

- **The grounding check verifies links, not claims.** It proves every cited URL was in the input. It does not prove that a bullet accurately reflects the article it cites.
- **Token use grows with the number of articles.** Map-reduce uses more total tokens than a single call until the input stops fitting in one prompt. Accounts with low rate limits may need a smaller `MAX_PER_FEED`, a lower `MAX_WORKERS`, or a higher `MAP_REDUCE_THRESHOLD`. Articles whose per-article call is rate limited fall back to their feed summary.
- **Run the API with a single worker.** The in-memory cache and lock are per process, so multiple workers would each keep their own.
- **Each uncached `/briefing` request can cost money.** There is no authentication or rate limiting, so don't expose the API publicly as it is.
- **A map-reduce run takes a while.** The API's lock is held for the whole run, so other requests wait for it.
- **Feed content is untrusted text** that goes into the model's input. The instructions and XML structure help against prompt injection, but they don't make it impossible.
- **Costs are estimates** based on constants that may be out of date.

## Project status

The planned work is complete:

- [x] Fall back to the RSS summary when an article fails to download or extract
- [x] Escape special characters before building the XML
- [x] Log token usage and estimated cost per run
- [x] Support multiple feeds in one run
- [x] Cache fetched articles and finished briefings
- [x] Wrap it in a FastAPI service
- [x] Add tests for parsing, caching, prompt building, the pipeline, and the API
- [x] Run lint and tests in GitHub Actions
- [x] Summarize each article first, then write the final briefing (map-reduce)
- [x] Return structured output validated by Pydantic
- [x] Check that every cited link was in the input

Ideas that are not planned: a Dockerfile, authentication and rate limiting for the API, accepting caller-supplied feeds (needs protection against server-side request forgery first), and checking whether each bullet is supported by the article it cites.

## Notes on responsible use

Respect each site's `robots.txt` and terms of service, and avoid sending requests in rapid bursts. Article content belongs to its publishers. The local cache is for your own runs only, and nothing in it is committed or redistributed.