# RSS News Briefing
 
A small Python command-line tool that reads several news sites' RSS feeds, extracts the full text of each article, and asks an LLM to write one short, themed briefing with source links. It also reports how many tokens each run used and what it roughly cost.
 
This is my first AI engineering project. It started as a CSV of pasted headlines summarized with a single API call, and grew into a pipeline that pulls live articles from multiple feeds.
 
## How it works
 
```
RSS feeds ──► feedparser ──► articles per feed (capped, with source + timestamp)
                                   │
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
                        LLM call (OpenAI API)
                                   │
                                   ▼
              Briefing printed + token usage and cost estimate logged
```
 
1. **Fetch the feeds** with [`feedparser`](https://github.com/kurtmckee/feedparser). Each feed contributes at most `MAX_PER_FEED` articles so no single source dominates. A feed that fails or comes back empty is logged and skipped, and the run continues with the others.
2. **Extract article text** with [`trafilatura`](https://github.com/adbar/trafilatura), which pulls the main content out of each page and drops navigation, ads, and footers. If a page can't be fetched or extracted, the script falls back to the RSS summary.
3. **Combine, sort, and deduplicate.** Articles from all feeds are sorted newest first using the feed's parsed timestamp, then duplicates (same link) are removed so the newest copy is kept.
4. **Build the input.** Each article is wrapped in XML tags (`id`, `title`, `published`, `link`, `source`, `summary`, `text`) so the model can tell the pieces apart. Special characters are escaped, and article text is truncated to keep token usage under control.
5. **Summarize.** The rules are sent as separate instructions and the articles as the input. The model is told to use only the provided articles, merge duplicate stories, flag conflicting reports, skip trivial items, and cite sources by link.
6. **Report usage.** After the briefing, the script logs input, cached, and output token counts plus an estimated cost.
### Output format
 
The briefing contains:
 
- A 2-3 sentence overview of the main stories
- Up to 5 themed sections with 2-4 bullet points each
- A one-line "worth watching" note
- Under 300 words, with source links
The briefing goes to stdout and the log messages go to stderr (via `logging`), so the briefing can be piped or redirected on its own.
 
## Example output


```
This week’s culture coverage revisits women’s lives and power across history, from medieval accusations and legal action to Renaissance art. In film, an unconventional romance is stirring online interest, while a Spanish drama and a new film about Elizabeth Holmes draw attention for very different reasons.

### History, power and women’s lives
- Eleanor Cobham’s 1441 conviction for treasonable witchcraft may have been political manoeuvring, though novelist Philippa Gregory portrays her as an active practitioner. [BBC](https://www.bbc.com/culture/article/20261022-the-15th-century-duchess-charged-with-treason-and-witchcraft?ocid=global_culture_rss)
- Records of Jehanne’s 1472 assault case reveal a medieval woman pursuing justice in Dijon, challenging assumptions about women’s ability to bring accusations. [BBC](https://www.bbc.com/culture/article/20261019-the-true-story-of-a-15th-century-sexual-assault-survivors-quest-for-justice?ocid=global_culture_rss)
- Renaissance painter Lavinia Fontana won major commissions and painted suggestive female nudes, pioneering a path for professional women artists. [BBC](https://www.bbc.com/culture/article/20261015-the-trailblazing-erotic-art-of-lavinia-fontana?ocid=global_culture_rss)
- A BBC account of the Cuban missile crisis credits John and Robert Kennedy’s diplomacy with helping avert nuclear war, drawing on interviews with insiders. [BBC](https://www.bbc.com/culture/article/20261015-the-men-who-averted-the-1962-cuban-missile-crisis?ocid=global_culture_rss)

### Films drawing attention
- *Wicker*, about a woman commissioning a woven husband, has sparked an online frenzy over its bizarre romantic premise and Alexander Skarsgård’s role. [BBC](https://www.bbc.com/culture/article/20261021-why-women-are-going-wild-for-freaky-film-romance-wicker?ocid=global_culture_rss)
- Spanish drama *La Bola Negra*, following three gay men across a century, is emerging as a potential best-picture contender. [BBC](https://www.bbc.com/culture/article/20261013-why-la-bola-negra-could-win-the-oscars-top-prize?ocid=global_culture_rss)
- A new film explores why Theranos founder Elizabeth Holmes remains a compelling public figure after her conviction for defrauding investors. [BBC](https://www.bbc.com/culture/article/20261014-why-fraudster-elizabeth-holmes-still-fascinates?ocid=global_culture_rss)

**Worth watching:** Whether *La Bola Negra* can turn awards buzz into a best-picture win.
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
 
The briefing is printed to the terminal, followed by a usage summary.


### Configuration
 
These settings are constants at the top of `main.py`:
 
| Setting | Constant | Default |
|---|---|---|
| Feed URLs | `FEEDS` | BBC Culture, NYT World, TechCrunch |
| Max articles taken from each feed | `MAX_PER_FEED` | `10` (`None` for no limit) |
| Characters of text per article | `MAX_CHARS` | `1500` |
| Model | `MODEL` | set in the script |
| Prices (USD per 1M tokens) | `INPUT_PRICE`, `CACHED_INPUT_PRICE`, `OUTPUT_PRICE` | see script |
| Prompt and rules | `INSTRUCTIONS` | see script |
 
To use other sources, edit the `FEEDS` list with any RSS or Atom feed URLs.
 
> **Cost figures are estimates.** They are calculated from the price constants in the script, which may become outdated. Check your provider's pricing page and update them when needed. More feeds mean more tokens, so watch the usage line when you add sources.
 
## Project structure
 
```
rss-news-briefing/
├── main.py          # fetching, extraction, dedup, prompt building, summarization, cost logging
├── pyproject.toml   # project metadata and dependencies (uv)
├── uv.lock          # locked dependency versions
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
- [ ] Cache fetched articles and summaries to avoid repeat work
- [ ] Add tests for parsing and prompt building
- [ ] Summarize each article first, then write the final briefing (map-reduce) for larger batches
- [ ] Wrap it in a FastAPI service
## Notes on responsible use
 
Respect each site's `robots.txt` and terms of service, and avoid sending requests in rapid bursts. Article content belongs to its publishers, so this project does not store or redistribute full texts.