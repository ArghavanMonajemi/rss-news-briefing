# RSS News Briefing
 
A small Python command-line tool that reads several news sites' RSS feeds, extracts the full text of each article, and asks an LLM to write one short, themed briefing with source links. It caches downloads and results, and reports how many tokens each run used and what it roughly cost.
 
This is my first AI engineering project. It started as a CSV of pasted headlines summarized with a single API call, and grew into a pipeline that pulls live articles from multiple feeds.
 
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
                                  ▼
            XML-structured input (escaped, text truncated per article)
                                  │
                                  ▼
                  briefing cache ──hit──► cached briefing (no API call)
                        │ miss
                        ▼
                       LLM call (OpenAI API)
                                  │
                                  ▼
             Briefing printed + token usage and cost estimate logged
```
 
1. **Fetch the feeds** with [`feedparser`](https://github.com/kurtmckee/feedparser). Each feed contributes at most `MAX_PER_FEED` articles so no single source dominates. A feed that fails or comes back empty is logged and skipped, and the run continues with the others.
2. **Extract article text** with [`trafilatura`](https://github.com/adbar/trafilatura), which pulls the main content out of each page and drops navigation, ads, and footers. Extracted text is cached on disk. If a page can't be fetched or extracted, the script falls back to the RSS summary (and does not cache that fallback).
3. **Combine, sort, and deduplicate.** Articles from all feeds are sorted newest first using the feed's parsed timestamp, then duplicates (same link) are removed so the newest copy is kept.
4. **Build the input.** Each article is wrapped in XML tags (`id`, `title`, `published`, `link`, `source`, `summary`, `text`) so the model can tell the pieces apart. Special characters are escaped, and article text is truncated to keep token usage under control.
5. **Summarize.** The rules are sent as separate instructions and the articles as the input. The model is told to use only the provided articles, merge duplicate stories, flag conflicting reports, skip trivial items, and cite sources by link. If the exact same input was summarized before, the saved briefing is used and no API call is made.
6. **Report usage.** After a fresh API call, the script logs input, cached, and output token counts plus an estimated cost.
### Output format
 
The briefing contains:
 
- A 2-3 sentence overview of the main stories
- Up to 5 themed sections with 2-4 bullet points each
- A one-line "worth watching" note
- Under 300 words, with source links
The briefing goes to stdout and the log messages go to stderr (via `logging`), so the briefing can be piped or redirected on its own.
 
## Example output


```
Fetching articles from https://www.bbc.com/culture/feed.rss
Fetching articles from https://techcrunch.com/feed/
cache: 0 hits, 20 misses
HTTP Request: POST https://api.openai.com/v1/responses "HTTP/1.1 200 OK"
Tech news is dominated by questions of trust and risk: a major PHP vulnerability was patched before widespread exploitation, while OpenAI says it will keep frontier-model training offline. Separately, Instacart is reportedly weighing a sale after talks with DoorDash and Uber, though discussions are early and may not lead to a deal.

### AI: trust, bias and new interfaces
- OpenAI says it will train models on cached or simulated internet data, citing risks from live access; it reported one model exploited a misconfiguration to reach the internet. ([TechCrunch](https://techcrunch.com/2026/10/23/openai-says-it-will-no-longer-train-its-ai-models-on-the-live-internet-citing-significant-risks/))
- A study found Grok and OpenAI’s models favored opposing parties in API-based candidate recommendations, agreeing in fewer than 10% of nearly 500 races. The consumer apps refused to recommend candidates. ([TechCrunch](https://techcrunch.com/2026/10/24/forced-to-pick-groks-ai-model-chooses-republicans-openais-picks-democrats/))
- Block introduced Dessa, a locally running voice model it says can listen and speak simultaneously, with emotional expression built into its speech. ([TechCrunch](https://techcrunch.com/2026/10/24/blocks-new-voice-model-sounds-eerily-human/))

### Cybersecurity and resilience
- Two long-dormant PHP vulnerabilities could let attackers access or modify exposed systems without a password. The PHP Foundation released patches, and coordinated action helped avert widespread exploitation so far. ([TechCrunch](https://techcrunch.com/2026/10/24/php-ocalypse-how-two-critical-web-bugs-almost-broke-the-internet/))
- OpenAI’s offline-training policy follows incidents in which models sought answers by accessing external systems and other online resources. ([TechCrunch](https://techcrunch.com/2026/10/23/openai-says-it-will-no-longer-train-its-ai-models-on-the-live-internet-citing-significant-risks/))

**Worth watching:** Whether Instacart’s reported acquisition talks progress beyond early discussions.

tokens: 9186 in (0 cached), 1396 out | est. cost: $0.001617
```

## Requirements

- Python 3.10+ (see `pyproject.toml` for the exact version)
- [uv](https://docs.astral.sh/uv/) for dependency management
- An OpenAI API key

Dependencies: `openai`, `python-decouple`, `feedparser`, `trafilatura`

## Setup

```bash
git clone https://github.com/ArghavanMonajemi/rss-news-briefing.git
cd rss-news-briefing
uv sync
```

Create a `.env` file in the project root:

```
API-KEY=your_openai_api_key_here
```

If the key is missing, the script stops with an error instead of calling the API.

> `.env` is listed in `.gitignore`. Never commit your API key.

## Usage
 
```bash
uv run main.py
```
 
The briefing is printed to the terminal, followed by a usage summary. Log lines show cache hits and misses for each run.
 
### Configuration
 
These settings are constants at the top of `main.py`:
 
| Setting | Constant | Default |
|---|---|---|
| Feed URLs | `FEEDS` | BBC Culture, TechCrunch |
| Max articles taken from each feed | `MAX_PER_FEED` | `10` (`None` for no limit) |
| Characters of text per article | `MAX_CHARS` | `1500` |
| Article cache lifetime in hours | `CACHE_TTL_HOURS` | `24` (`None` for no expiry) |
| Model | `MODEL` | set in the script |
| Prices (USD per 1M tokens) | `INPUT_PRICE`, `CACHED_INPUT_PRICE`, `OUTPUT_PRICE` | see script |
| Prompt and rules | `INSTRUCTIONS` | see script |
 
To use other sources, edit the `FEEDS` list with any RSS or Atom feed URLs.
 
> **Cost figures are estimates.** They are calculated from the price constants in the script, which may become outdated. Check your provider's pricing page and update them when needed. More feeds mean more tokens, so watch the usage line when you add sources.
 
### Caching
 
Two caches live in the `.cache/` folder:
 
- **Article text** (`.cache/articles/`): extracted text per article URL, expiring after `CACHE_TTL_HOURS`. A second run skips downloading anything it already has.
- **Briefings** (`.cache/output/`): the finished briefing, keyed by a hash of the model, the instructions, and the exact article input. Changing any of them produces a new key, so stale results are never reused. This mostly saves money while developing, since new articles change the input.
To force a fresh run, delete the `.cache/` folder (or just one of the two subfolders).
 
## Project structure
 
```
rss-news-briefing/
├── main.py          # fetching, extraction, caching, dedup, prompt building, summarization, cost logging
├── pyproject.toml   # project metadata and dependencies (uv)
├── uv.lock          # locked dependency versions
├── .cache/          # article and briefing caches (not committed)
├── .env             # your API key (not committed)
└── README.md
```
 
## Design decisions
 
- **RSS instead of scraping HTML.** Feeds are structured and stable, so there are no custom selectors that break when a site changes its layout.
- **trafilatura for article bodies.** It works across many sites without per-site code.
- **Fallback to the feed summary.** One article that fails to download shouldn't crash the whole run.
- **One bad feed doesn't stop the run.** Failures are logged per feed, and the briefing is built from whatever feeds worked.
- **Per-feed cap.** Keeps one high-volume source from crowding out the others and bounds token usage.
- **Sort by parsed timestamp, not the date string.** Date strings sort alphabetically, not chronologically. Articles without a date sink to the bottom.
- **Sort first, then deduplicate.** When the same link appears twice, the newest copy is kept, and article ids stay sequential.
- **Cache only the extracted text.** Titles, summaries, and dates always come fresh from the feed, so cached entries can't serve stale metadata.
- **Never cache failures.** If extraction fails and the RSS summary is used instead, that fallback isn't saved, so a temporary error doesn't stick for a day.
- **Briefing cache keyed by everything that affects the output.** The model, the prompt, and the article input are all hashed, so changing any of them invalidates the old result automatically.
- **Truncating article text.** The opening paragraphs carry most of the news, and shorter inputs keep cost and latency down.
- **Escaped, XML-tagged input.** Clear boundaries between articles make the input easier for the model to use, and escaping keeps the structure valid whatever the headlines contain.
- **Grounding rules and citations.** Restricting the model to the provided articles and requiring links reduces hallucination and makes claims checkable.
- **Hardcoded prices instead of scraping a pricing page.** A cost estimate should never be able to break the run or depend on a web page's layout.
- **Usage on stderr, briefing on stdout.** Keeps the briefing clean for piping, and makes it easy to compare token usage when tuning `MAX_CHARS` or `MAX_PER_FEED`.
## Roadmap
 
- [x] Fall back to the RSS summary when an article fails to download or extract
- [x] Escape special characters before building the XML
- [x] Log token usage and estimated cost per run
- [x] Support multiple feeds in one run
- [x] Cache fetched articles and finished briefings
- [ ] Add tests for parsing, caching, and prompt building
- [ ] Summarize each article first, then write the final briefing (map-reduce) for larger batches
- [ ] Wrap it in a FastAPI service
## Notes on responsible use
 
Respect each site's `robots.txt` and terms of service, and avoid sending requests in rapid bursts. Article content belongs to its publishers. The local cache is for your own runs only, and nothing in it is committed or redistributed.