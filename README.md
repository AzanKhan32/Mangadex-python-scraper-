# Mangadex Python Scraper

Download MangaDex chapters as PDFs using the official MangaDex API. Fast, resumable, and uses data-saver mode by default.

> **Disclaimer**: For educational/personal use only. Respect MangaDex's ToS and API rate limits. Do not redistribute copyrighted content.

## Features

- **PDF output**: Each chapter saves as a single PDF file
- **Resume support**: Skips images/chapters you've already downloaded
- **Multi-threaded**: Downloads images in parallel with `ThreadPoolExecutor`
- **Data saver**: Uses compressed images by default to save bandwidth
- **Language filter**: Set your preferred language with auto-fallback
- **API-based**: Uses official API v5, no HTML scraping

## Setup

### 1. Install requirements
```bash
pip install requests Pillow urllib3
