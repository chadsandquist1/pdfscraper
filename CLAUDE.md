# pdfScraper — Project Guide for Claude

## Purpose
Configurable Python tool that scrapes PDF documents from one or more seed URLs
and downloads them to a local directory. Tracks all downloads in a JSON registry
to avoid re-downloading files on subsequent runs.

## Project Structure

```
pdfScraper/
├── scraper.py            # Main scraper — run this
├── backfill_registry.py  # One-shot utility to seed downloaded.json from disk
├── source_urls.json      # List of seed URLs to scrape (edit to add sites)
├── config.json           # Runtime settings
├── requirements.txt      # Python dependencies (requests, beautifulsoup4, lxml)
├── README.md             # User-facing documentation
├── downloaded/           # Output directory (gitignored)
│   └── <domain>/
│       └── <url-path>/
│           └── file.pdf
└── downloaded.json       # Download registry (gitignored, lives locally only)
```

## Key Files

### `source_urls.json`
JSON array of seed URLs. Add any page that links to PDFs here.
```json
["https://insurance.delaware.gov/information/bulletins/"]
```

### `config.json`
| Key | Default | Purpose |
|-----|---------|---------|
| `output_dir` | `"downloaded"` | Root folder for downloaded PDFs |
| `delay_seconds` | `1.0` | Polite pause between HTTP requests |
| `skip_existing` | `true` | Skip files already in registry |
| `restrict_to_seed_path` | `true` | Only follow sub-page links under the seed URL's path |
| `user_agent` | `"Mozilla/5.0 …"` | HTTP User-Agent header |

### `downloaded.json` (local only, gitignored)
Nested registry keyed by domain then URL:
```json
{
  "insurance.delaware.gov": {
    "https://insurance.delaware.gov/.../file.pdf": {
      "url": "https://...",
      "date_downloaded": "2026-03-01T03:17:27Z",
      "local_filename": "insurance.delaware.gov/.../file.pdf"
    }
  }
}
```

## How the Scraper Works

1. Loads `source_urls.json` and `downloaded.json`
2. For each seed URL:
   - Fetches the seed page and collects all PDF links and same-domain page links
   - Filters page links to those under the seed URL's path (if `restrict_to_seed_path` is true)
   - Visits each qualifying sub-page and collects additional PDF links
   - Downloads each unique PDF, skipping any already in the registry
   - Records each successful download in `downloaded.json` immediately (crash-safe)
3. Prints a summary of downloaded / skipped / failed counts

## Running

```bash
# First time setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # one-time: installs headless browser

# Run the scraper
python scraper.py

# Rebuild the registry from files already on disk (no network)
python backfill_registry.py
```

## Registry Format Rules
- Top-level keys are domain names (e.g. `"insurance.delaware.gov"`)
- Second-level keys are full URLs
- Each entry has exactly 3 fields: `url`, `date_downloaded` (ISO 8601 UTC), `local_filename`
- `downloaded.json` is written atomically (via `.tmp` rename) to prevent corruption

## Gitignored Files
- `downloaded/` — binary PDF files, not suited for version control
- `downloaded.json` — local machine state, regeneratable via `backfill_registry.py`
- `.venv/` — Python virtual environment

## Playwright fallback
`fetch_page_auto()` tries `requests` first. If the response contains zero `<a href>` tags (indicating a JS-rendered or bot-protected page), it automatically retries using headless Chromium via Playwright. Playwright is imported lazily — if not installed, requests-only scraping continues normally with a warning.

## Dependencies
- `requests` — HTTP downloads
- `beautifulsoup4` + `lxml` — HTML parsing for link extraction
- `playwright` — headless Chromium for JS-rendered / bot-protected pages (requires `playwright install chromium` after pip install)

## IMPORTANT

- make sure you don't even check into git any sensitve information like passwords or terraform state files.
