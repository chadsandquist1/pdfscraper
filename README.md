# PDF Scraper

A configurable Python script that downloads PDFs from one or more seed URLs. For each seed URL it:

1. Fetches the seed page and collects any direct PDF links.
2. Follows all page links that are on the same domain (and optionally the same URL path prefix).
3. Collects PDFs from each of those sub-pages.
4. Downloads all unique PDFs into an organised output directory.

---

## Project layout

```
pdfScraper/
├── scraper.py          # Main script
├── source_urls.json    # List of seed URLs to scrape
├── config.json         # Runtime settings
├── requirements.txt    # Python dependencies
└── downloaded/         # Created automatically; PDFs saved here
    └── <domain>/
        └── <url-path>/
            └── file.pdf
```

---

## Quick start

```bash
# 1. Create and activate a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate.bat     # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the scraper
python scraper.py
```

PDFs are saved to `downloaded/<domain>/<path>/file.pdf`, mirroring the URL structure of each source site.

---

## Configuration — `config.json`

| Key | Default | Description |
|-----|---------|-------------|
| `output_dir` | `"downloaded"` | Root folder where PDFs are saved. |
| `delay_seconds` | `1.0` | Seconds to pause between HTTP requests (be polite to servers). |
| `skip_existing` | `true` | If `true`, files already present on disk are not re-downloaded. Set to `false` to always overwrite. |
| `restrict_to_seed_path` | `true` | If `true`, only follow sub-page links whose URL path starts with the seed URL's path. Prevents the crawler from wandering to unrelated sections of a large site. |
| `user_agent` | `"Mozilla/5.0 …"` | HTTP `User-Agent` header sent with every request. |

### Example `config.json`

```json
{
  "output_dir": "downloaded",
  "delay_seconds": 1.0,
  "skip_existing": true,
  "restrict_to_seed_path": true,
  "user_agent": "Mozilla/5.0 (compatible; PDFScraper/1.0)"
}
```

---

## Adding more seed URLs — `source_urls.json`

Add any number of seed URLs to the JSON array:

```json
[
  "https://insurance.delaware.gov/information/bulletins/",
  "https://example.com/reports/"
]
```

Each URL is scraped independently. PDFs are always filed under their own domain subdirectory inside `output_dir`.

---

## Output structure

```
downloaded/
└── insurance.delaware.gov/
    └── app/
        └── uploads/
            └── 2023/
                ├── bulletin-001.pdf
                └── bulletin-002.pdf
```

---

## Incremental runs

By default (`"skip_existing": true`) re-running the script only downloads new PDFs — already-downloaded files are skipped. This makes it safe to run on a schedule (e.g. via `cron`) to pick up newly published documents.

---

## Requirements

- Python 3.10 or later
- See `requirements.txt` for package dependencies
