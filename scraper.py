#!/usr/bin/env python3
"""
PDF Scraper
-----------
Downloads all PDFs found on seed URLs and one level of linked sub-pages
(same domain, same URL path prefix). Settings are read from config.json;
seed URLs are read from source_urls.json.
"""

import itertools
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------

CONFIG_FILE = Path("config.json")
URLS_FILE = Path("source_urls.json")
REGISTRY_FILE = Path("downloaded.json")

for required in (CONFIG_FILE, URLS_FILE):
    if not required.exists():
        sys.exit(f"Error: required file '{required}' not found.")

with CONFIG_FILE.open() as fh:
    config = json.load(fh)

with URLS_FILE.open() as fh:
    _raw_urls = json.load(fh)

# Normalize: plain strings become {"url": "..."}, objects are passed through
source_urls: list[dict] = [
    entry if isinstance(entry, dict) else {"url": entry} for entry in _raw_urls
]

OUTPUT_DIR = Path(config.get("output_dir", "downloaded"))
DELAY = float(config.get("delay_seconds", 1.0))
SKIP_EXISTING = bool(config.get("skip_existing", True))
RESTRICT_TO_SEED_PATH = bool(config.get("restrict_to_seed_path", True))
USER_AGENT = config.get(
    "user_agent",
    "Mozilla/5.0 (compatible; PDFScraper/1.0)",
)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_domain(url: str) -> str:
    return urlparse(url).netloc


def parse_path_prefix(url: str) -> str:
    """Return the directory portion of a URL path (used to scope sub-page crawl)."""
    parsed = urlparse(url)
    path = parsed.path
    if not path.endswith("/"):
        path = path.rsplit("/", 1)[0] + "/"
    return path


def is_pdf_link(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def fetch_page(url: str) -> BeautifulSoup | None:
    """Fetch a URL via requests and return a BeautifulSoup object, or None on error."""
    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as exc:
        print(f"    [WARN] Could not fetch {url}: {exc}")
        return None


def fetch_page_playwright(url: str) -> BeautifulSoup | None:
    """
    Render a page using headless Chromium with stealth patches applied.
    playwright-stealth hides automation indicators (navigator.webdriver,
    missing plugins, etc.) to bypass bot-detection systems like Radware.
    """
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError as exc:
        print(f"    [WARN] Missing dependency: {exc}")
        print(
            "           Run: pip install playwright playwright-stealth && playwright install chromium"
        )
        return None
    try:
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=30_000)
            # Wait for the SPA to render links (hash-fragment routers make API
            # calls after "load", so a flat wait is unreliable).
            try:
                page.wait_for_selector("a[href]", timeout=15_000)
            except Exception:
                pass  # no links within 15 s — last/empty page, proceed anyway
            html = page.content()
            browser.close()
        return BeautifulSoup(html, "lxml")
    except Exception as exc:
        print(f"    [WARN] Playwright could not fetch {url}: {exc}")
        return None


def fetch_page_auto(url: str) -> BeautifulSoup | None:
    """
    Fetch a URL using requests. If the response contains no anchor tags
    (indicating a JS-rendered or bot-protected page), automatically retry
    using headless Chromium via Playwright.
    """
    soup = fetch_page(url)
    if soup is None:
        return None
    if not soup.find("a", href=True):
        print("    [INFO] No links via requests — retrying with Playwright...")
        pw_soup = fetch_page_playwright(url)
        if pw_soup is not None:
            return pw_soup
    return soup


def collect_links(soup: BeautifulSoup, base_url: str) -> tuple[set[str], set[str]]:
    """
    Return (pdf_links, page_links) found in the soup.
    All URLs are absolute.
    """
    pdf_links: set[str] = set()
    page_links: set[str] = set()

    for tag in soup.find_all("a", href=True):
        abs_url = urljoin(base_url, tag["href"].strip())
        parsed = urlparse(abs_url)

        if parsed.scheme not in ("http", "https"):
            continue
        if "#" in abs_url:
            abs_url = abs_url.split("#")[0]
        if not abs_url:
            continue

        if is_pdf_link(abs_url):
            pdf_links.add(abs_url)
        else:
            page_links.add(abs_url)

    return pdf_links, page_links


def output_path_for(pdf_url: str) -> Path:
    """Map a PDF URL to its local download path inside OUTPUT_DIR."""
    parsed = urlparse(pdf_url)
    domain = parsed.netloc
    rel_path = parsed.path.lstrip("/")
    return OUTPUT_DIR / domain / rel_path


# ---------------------------------------------------------------------------
# Download registry  (downloaded.json)
# ---------------------------------------------------------------------------


def load_registry() -> dict:
    """Load the registry from disk. Returns {domain: {url: entry}}."""
    if not REGISTRY_FILE.exists():
        return {}
    with REGISTRY_FILE.open() as fh:
        return json.load(fh)


def save_registry(registry: dict) -> None:
    """Atomically write the registry to disk."""
    tmp = REGISTRY_FILE.with_suffix(".tmp")
    with tmp.open("w") as fh:
        json.dump(registry, fh, indent=2)
    tmp.replace(REGISTRY_FILE)


def download_pdf(pdf_url: str, registry: dict) -> str:
    """
    Download a PDF to the appropriate output path.
    Checks the registry first; updates it on success.
    Returns one of: 'downloaded', 'skipped', 'failed'.
    """
    domain = parse_domain(pdf_url)
    domain_entries = registry.get(domain, {})
    dest = output_path_for(pdf_url)

    if SKIP_EXISTING and pdf_url in domain_entries:
        print(f"    [SKIP] {domain_entries[pdf_url]['local_filename']} (in registry)")
        return "skipped"

    if SKIP_EXISTING and dest.exists():
        local_filename = str(dest.relative_to(OUTPUT_DIR))
        print(f"    [SKIP] {local_filename} (file exists)")
        # Backfill registry so future runs skip via registry lookup
        if pdf_url not in domain_entries:
            mtime = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc)
            registry.setdefault(domain, {})[pdf_url] = {
                "url": pdf_url,
                "date_downloaded": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "local_filename": local_filename,
            }
            save_registry(registry)
        return "skipped"

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = SESSION.get(pdf_url, stream=True, timeout=60)
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=16_384):
                fh.write(chunk)

        local_filename = str(dest.relative_to(OUTPUT_DIR))
        registry.setdefault(domain, {})[pdf_url] = {
            "url": pdf_url,
            "date_downloaded": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "local_filename": local_filename,
        }
        save_registry(registry)

        print(f"    [OK]   {local_filename}")
        return "downloaded"
    except requests.RequestException as exc:
        print(f"    [FAIL] {pdf_url}: {exc}")
        # Remove partial file if it was created
        if dest.exists():
            dest.unlink()
        return "failed"


# ---------------------------------------------------------------------------
# Core scrape logic
# ---------------------------------------------------------------------------


def collect_paginated_pdfs(base_url: str, pagination: dict) -> set[str]:
    """
    Navigate through a paginated SPA by substituting {page} in the URL
    pattern, collecting PDFs from each page until a page yields no new ones.
    Always uses Playwright since paginated sites are JS-rendered.
    """
    pattern = pagination["pattern"]
    start_page = int(pagination.get("start_page", 1))
    all_pdfs: set[str] = set()

    for page_num in itertools.count(start_page):
        page_url = base_url + pattern.replace("{page}", str(page_num))
        print(f"\n  [Page {page_num}] {page_url}")
        time.sleep(DELAY)

        soup = fetch_page_playwright(page_url)
        if soup is None:
            print(f"    Could not fetch page {page_num}, stopping.")
            break

        page_pdfs, _ = collect_links(soup, base_url)
        new_pdfs = page_pdfs - all_pdfs
        print(f"    {len(page_pdfs)} PDF(s) on page, {len(new_pdfs)} new")

        if not new_pdfs:
            print("    No new PDFs — pagination complete.")
            break

        all_pdfs.update(new_pdfs)

    return all_pdfs


def scrape_seed(entry: dict, registry: dict) -> dict[str, int]:
    """
    Scrape one seed entry.

    If the entry has a 'pagination' key, navigates through paginated pages
    using collect_paginated_pdfs(). Otherwise uses the standard crawl:
    fetch seed page + one level of same-domain sub-pages.

    Returns a dict with counts: downloaded, skipped, failed.
    """
    seed_url = entry["url"]
    pagination = entry.get("pagination")
    domain = parse_domain(seed_url)
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}

    print(f"\n{'=' * 70}")
    print(f"Seed URL : {seed_url}")
    print(f"Domain   : {domain}")
    if pagination:
        print(
            f"Pagination: {pagination['type']}, start page {pagination.get('start_page', 1)}"
        )
    elif RESTRICT_TO_SEED_PATH:
        print(f"Path scope: {parse_path_prefix(seed_url)}*")
    print(f"{'=' * 70}")

    if pagination:
        # --- Paginated SPA ---
        all_pdfs = collect_paginated_pdfs(seed_url, pagination)
        print(f"\n  Total unique PDFs: {len(all_pdfs)}")

    else:
        # --- Standard crawl: seed page + one level of sub-pages ---
        seed_path_prefix = parse_path_prefix(seed_url)

        soup = fetch_page_auto(seed_url)
        if soup is None:
            print("  Could not fetch seed page. Skipping.")
            return counts

        seed_pdfs, seed_pages = collect_links(soup, seed_url)
        print(
            f"  Seed page  -> {len(seed_pdfs)} PDF link(s), {len(seed_pages)} page link(s)"
        )

        def should_follow(url: str) -> bool:
            if parse_domain(url) != domain:
                return False
            if RESTRICT_TO_SEED_PATH:
                return urlparse(url).path.startswith(seed_path_prefix)
            return True

        pages_to_visit = {url for url in seed_pages if should_follow(url)}
        print(f"  Sub-pages to visit: {len(pages_to_visit)}")

        all_pdfs: set[str] = set(seed_pdfs)
        for i, page_url in enumerate(sorted(pages_to_visit), start=1):
            time.sleep(DELAY)
            print(f"\n  [{i}/{len(pages_to_visit)}] {page_url}")
            sub_soup = fetch_page_auto(page_url)
            if sub_soup is None:
                continue
            sub_pdfs, _ = collect_links(sub_soup, page_url)
            if sub_pdfs:
                print(f"    Found {len(sub_pdfs)} PDF(s)")
            all_pdfs.update(sub_pdfs)

        print(f"\n  Total unique PDFs: {len(all_pdfs)}")

    # --- Download ---
    for pdf_url in sorted(all_pdfs):
        time.sleep(DELAY)
        result = download_pdf(pdf_url, registry)
        counts[result] += 1

    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    registry = load_registry()

    print("PDF Scraper")
    print(f"  Config       : {CONFIG_FILE}")
    print(f"  Source URLs  : {URLS_FILE} ({len(source_urls)} URL(s))")
    print(f"  Output dir   : {OUTPUT_DIR}")
    total_entries = sum(len(v) for v in registry.values())
    print(
        f"  Registry     : {REGISTRY_FILE} ({len(registry)} domain(s), {total_entries} entries)"
    )
    print(f"  Delay        : {DELAY}s between requests")
    print(f"  Skip existing: {SKIP_EXISTING}")

    OUTPUT_DIR.mkdir(exist_ok=True)

    totals = {"downloaded": 0, "skipped": 0, "failed": 0}
    for entry in source_urls:
        if entry.get("skip", False):
            print(f"\n[SKIP] {entry['url']}")
            continue
        result = scrape_seed(entry, registry)
        for key in totals:
            totals[key] += result[key]

    print(f"\n{'=' * 70}")
    print("Run complete.")
    print(f"  Downloaded : {totals['downloaded']}")
    print(f"  Skipped    : {totals['skipped']}")
    print(f"  Failed     : {totals['failed']}")
    print(f"  Output dir : {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
