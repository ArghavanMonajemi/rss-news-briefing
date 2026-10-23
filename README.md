# RSS News Briefing

A small Python command-line tool that reads a news site's RSS feed, extracts the full text of each article, and asks an LLM to write a short, themed briefing with source links.

This is my first AI engineering project. It started as a CSV of pasted headlines summarized with a single API call, and grew into a pipeline that pulls live articles from a feed.

## How it works

```
RSS feed ──► feedparser ──► article list (title, link, date, summary)
                                   │
                                   ▼
                  trafilatura (fetch + extract full text,
                  falls back to the RSS summary on failure)
                                   │
                                   ▼
             XML-structured input (escaped, text truncated per article)
                                   │
                                   ▼
                        LLM call (OpenAI API)
                                   │
                                   ▼
                          Briefing printed to console
```

1. **Fetch the feed** with [`feedparser`](https://github.com/kurtmckee/feedparser). The script currently uses the BBC Culture feed.
2. **Extract article text** with [`trafilatura`](https://github.com/adbar/trafilatura), which pulls the main content out of each page and drops navigation, ads, and footers. If a page can't be fetched or extracted, the script falls back to the RSS summary.
3. **Build the input.** Each article is wrapped in XML tags (`id`, `title`, `published`, `link`, `summary`, `text`) so the model can tell the pieces apart. Special characters are escaped, and article text is truncated to keep token usage under control.
4. **Summarize.** The rules are sent as separate instructions and the articles as the input. The model is told to use only the provided articles, merge duplicate stories, flag conflicting reports, skip trivial items, and cite sources by link.

### Output format

The briefing contains:

- A 2-3 sentence overview of the main stories
- Up to 5 themed sections with 2-4 bullet points each
- A one-line "worth watching" note
- Under 300 words, with source links

## Example output

```
(paste a sample briefing from one of your runs here)
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

The briefing is printed to the terminal.

### Configuration

These settings are constants at the top of `main.py`:

| Setting | Constant | Default |
|---|---|---|
| Feed URL | `FEED_URL` | BBC Culture RSS |
| Characters of text per article | `MAX_CHARS` | `1500` |
| Model | `MODEL` | set in the script |
| Prompt and rules | `INSTRUCTIONS` | see script |

To summarize a different site, point `FEED_URL` at any RSS or Atom feed.

## Project structure

```
rss-news-briefing/
├── main.py          # fetching, extraction, prompt building, summarization
├── pyproject.toml   # project metadata and dependencies (uv)
├── uv.lock          # locked dependency versions
├── .env             # your API key (not committed)
└── README.md
```

## Design decisions

- **RSS instead of scraping HTML.** Feeds are structured and stable, so there are no custom selectors that break when a site changes its layout.
- **trafilatura for article bodies.** It works across many sites without per-site code.
- **Fallback to the feed summary.** One article that fails to download shouldn't crash the whole run.
- **Truncating article text.** The opening paragraphs carry most of the news, and shorter inputs keep cost and latency down.
- **Escaped, XML-tagged input.** Clear boundaries between articles make the input easier for the model to use, and escaping keeps the structure valid whatever the headlines contain.
- **Grounding rules and citations.** Restricting the model to the provided articles and requiring links reduces hallucination and makes claims checkable.

## Roadmap

- [x] Fall back to the RSS summary when an article fails to download or extract
- [x] Escape special characters before building the XML
- [ ] Support multiple feeds in one run
- [ ] Summarize each article first, then write the final briefing (map-reduce) for larger batches
- [ ] Cache fetched articles and summaries to avoid repeat work
- [ ] Log token usage and cost per run
- [ ] Wrap it in a FastAPI service
- [ ] Add tests for parsing and prompt building

## Notes on responsible use

Respect each site's `robots.txt` and terms of service, and avoid sending requests in rapid bursts. Article content belongs to its publishers, so this project does not store or redistribute full texts.
