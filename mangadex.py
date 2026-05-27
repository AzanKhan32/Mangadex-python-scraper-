import os
import shutil
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image

# ============================================================
# CONFIG
# ============================================================

OUTPUT_DIR = r"C:\A manhwa folder\dmf"
MANGA_ID = "8f3726fc-9c3a-425e-9f85-b78ae94e" #extract the manga ID from the URL, e.g. 
LANGUAGE = "en"

MAX_WORKERS = 20
CHAPTER_CONCURRENCY = 1
RATE_LIMIT_DELAY = 0.1
PDF_JPEG_QUALITY = 85
PDF_MAX_DIMENSION = None
USE_DATA_SAVER = True

BASE_URL = "https://api.mangadex.org"
HEADERS = {"User-Agent": "KomikkuDownloader/2.0"}

LANGUAGE_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "zh-hk": "Chinese (Hong Kong, Traditional)",
    "pt-br": "Portuguese (Brazil)",
    "es": "Spanish",
    "es-la": "Spanish (Latin America)",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ru": "Russian",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "tr": "Turkish",
    "ar": "Arabic",
    "pl": "Polish",
    "nl": "Dutch"
}

# ============================================================
# SESSION + RETRY
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)

retry_strategy = Retry(
    total=3,
    status_forcelist=[429, 500, 502, 503, 504],
    backoff_factor=0.5,
    allowed_methods=["HEAD", "GET", "OPTIONS"]
)

adapter = HTTPAdapter(
    pool_connections=MAX_WORKERS * 2,
    pool_maxsize=MAX_WORKERS * 2,
    max_retries=retry_strategy
)

session.mount("https://", adapter)
session.mount("http://", adapter)

# ============================================================
# MANGA INFO
# ============================================================

def get_manga_title(manga_id):
    r = session.get(f"{BASE_URL}/manga/{manga_id}")
    r.raise_for_status()

    data = r.json()["data"]["attributes"]["title"]
    return data.get("en") or list(data.values())[0]


def get_all_chapters(manga_id, lang="en"):
    language_tally = {}

    def fetch(lang_filter=None):
        chapters = []
        offset = 0
        limit = 100

        while True:
            params = {
                "manga": manga_id,
                "order[chapter]": "asc",
                "limit": limit,
                "offset": offset,
                "contentRating[]": [
                    "safe",
                    "suggestive",
                    "erotica",
                    "pornographic"
                ]
            }
            if lang_filter:
                params["translatedLanguage[]"] = lang_filter

            r = session.get(f"{BASE_URL}/chapter", params=params)
            r.raise_for_status()
            data = r.json()

            for ch in data["data"]:
                attr = ch["attributes"]
                ch_lang = attr.get("translatedLanguage") or "unknown"
                language_tally[ch_lang] = language_tally.get(ch_lang, 0) + 1

                if attr["pages"] == 0:
                    continue

                chapters.append({
                    "id": ch["id"],
                    "chapter": attr["chapter"],
                    "title": attr["title"],
                    "pages": attr["pages"]
                })

            if offset + limit >= data["total"]:
                break

            offset += limit
            time.sleep(0.2)

        return chapters

    chapters = fetch(lang)
    if not chapters:
        print(
            f"No chapters found for language '{lang}'. "
            "Retrying with all languages..."
        )
        chapters = fetch(None)

    if language_tally:
        langs = ", ".join(
            f"{k} ({LANGUAGE_NAMES.get(k, 'Unknown')}) ({v})"
            for k, v in sorted(
                language_tally.items(),
                key=lambda item: item[1],
                reverse=True
            )
        )
        print(f"Chapter languages seen: {langs}")
    else:
        print("Chapter languages seen: unknown")

    return chapters

# ============================================================
# CHAPTER IMAGES
# ============================================================

def get_chapter_images(chapter_id):
    r = session.get(f"{BASE_URL}/at-home/server/{chapter_id}")
    r.raise_for_status()

    data = r.json()

    base_url = data["baseUrl"]
    chapter_hash = data["chapter"]["hash"]
    chapter_data = data["chapter"]
    full_images = chapter_data.get("data", [])
    saver_images = chapter_data.get("dataSaver", [])

    if USE_DATA_SAVER and saver_images:
        return [
            f"{base_url}/data-saver/{chapter_hash}/{img}"
            for img in saver_images
        ]

    return [
        f"{base_url}/data/{chapter_hash}/{img}"
        for img in full_images
    ]


def download_image(url, filepath):
    try:
        urls_to_try = [url]
        if "/data-saver/" in url:
            urls_to_try.append(url.replace("/data-saver/", "/data/"))

        for download_url in urls_to_try:
            try:
                r = session.get(download_url, timeout=30, stream=True)
                r.raise_for_status()

                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)

                return True
            except requests.RequestException:
                continue

        print(f"Failed {os.path.basename(filepath)}")
        return False

    except requests.RequestException as e:
        print(f"Failed {os.path.basename(filepath)}: {e}")
        return False

# ============================================================
# PDF CREATION
# ============================================================

def create_pdf_from_folder(temp_folder, output_pdf):
    image_files = sorted([
        f for f in os.listdir(temp_folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])

    if not image_files:
        return False

    images = []

    for img_file in image_files:
        img_path = os.path.join(temp_folder, img_file)

        try:
            with Image.open(img_path) as raw_img:
                img = raw_img.convert("RGB")
            if PDF_MAX_DIMENSION and max(img.size) > PDF_MAX_DIMENSION:
                img.thumbnail(
                    (PDF_MAX_DIMENSION, PDF_MAX_DIMENSION),
                    Image.Resampling.LANCZOS
                )
            images.append(img)

        except Exception as e:
            print(f" ❌ Failed opening {img_file}: {e}")

    if not images:
        return False

    images[0].save(
        output_pdf,
        save_all=True,
        append_images=images[1:],
        format="PDF",
        resolution=150,
        quality=PDF_JPEG_QUALITY,
        optimize=True
    )

    return True

# ============================================================
# DOWNLOAD CHAPTER
# ============================================================

def download_chapter(chapter_info, output_dir):

    ch_num = chapter_info["chapter"] or "Oneshot"
    ch_title = chapter_info["title"] or ""

    safe_title = "".join(
        c for c in ch_title
        if c.isalnum() or c in " -_"
    ).strip()

    fname = f"Ch {ch_num}"

    if safe_title:
        fname += f" - {safe_title}"

    output_pdf = os.path.join(output_dir, f"{fname}.pdf")

    # temp folder for resume support
    temp_folder = os.path.join(
        output_dir,
        "_temp",
        fname
    )

    # Skip if already done
    if os.path.exists(output_pdf):
        print(f" ⏭ Chapter {ch_num} already exists")
        return True

    os.makedirs(temp_folder, exist_ok=True)

    print(f"\n📥 Chapter {ch_num}")
    print(f"📄 {chapter_info['pages']} pages")

    try:
        img_urls = get_chapter_images(chapter_info["id"])

        if not img_urls:
            print(" ❌ No images found")
            return False

        tasks = []

        for idx, url in enumerate(img_urls, start=1):

            img_name = f"{idx:03d}.jpg"
            img_path = os.path.join(temp_folder, img_name)

            # Resume support
            if os.path.exists(img_path):
                continue

            tasks.append((url, img_path))

        already_have = len(img_urls) - len(tasks)

        if already_have > 0:
            print(
                f" 🔄 Resuming: "
                f"{already_have}/{len(img_urls)} "
                f"already downloaded"
            )

        worker_count = min(MAX_WORKERS, max(1, len(tasks)))

        with ThreadPoolExecutor(
            max_workers=worker_count
        ) as executor:

            futures = {
                executor.submit(
                    download_image,
                    url,
                    path
                ): path
                for url, path in tasks
            }

            completed = already_have

            for future in as_completed(futures):

                success = future.result()

                if success:
                    completed += 1

                print(
                    f" Downloaded "
                    f"{completed}/{len(img_urls)}",
                    end="\r"
                )

        print(
            f"\n✅ All images ready "
            f"({len(img_urls)}/{len(img_urls)})"
        )

        print("📘 Creating PDF...")

        success = create_pdf_from_folder(
            temp_folder,
            output_pdf
        )

        if not success:
            print(" ❌ PDF creation failed")
            return False

        # cleanup temp files
        shutil.rmtree(temp_folder)

        pdf_size = os.path.getsize(output_pdf) // 1024

        print(
            f" ✓ Saved → "
            f"{os.path.basename(output_pdf)} "
            f"({pdf_size} KB)"
        )

        return True

    except Exception as e:
        print(f" ❌ Chapter failed: {e}")
        return False

# ============================================================
# MAIN
# ============================================================

def main():

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(
        os.path.join(OUTPUT_DIR, "_temp"),
        exist_ok=True
    )

    manga_title = get_manga_title(MANGA_ID)

    print("=" * 60)
    print(f"📖 {manga_title}")
    print(f"📁 Output: {OUTPUT_DIR}")
    print("💾 Format: PDF")
    print("=" * 60)

    chapters = get_all_chapters(
        MANGA_ID,
        LANGUAGE
    )

    print(f"\n✅ Found {len(chapters)} chapters")

    start = input("Start chapter [1]: ") or "1"
    end = input(
        f"End chapter [{len(chapters)}]: "
    ) or str(len(chapters))

    try:
        start_idx = int(start) - 1
        end_idx = int(end)

        selected = chapters[
            start_idx:end_idx
        ]

    except:
        print("❌ Invalid range")
        return

    print(
        f"\n📦 {len(selected)} "
        f"chapters to download\n"
    )

    if (
        CHAPTER_CONCURRENCY > 1
        and len(selected) > 1
    ):

        with ThreadPoolExecutor(
            max_workers=min(
                CHAPTER_CONCURRENCY,
                len(selected)
            )
        ) as executor:

            futures = {
                executor.submit(
                    download_chapter,
                    ch,
                    OUTPUT_DIR
                ): ch
                for ch in selected
            }

            for future in as_completed(futures):
                ch = futures[future]

                try:
                    future.result()

                except Exception as e:
                    print(
                        f" ❌ Chapter "
                        f"{ch['chapter']} "
                        f"failed: {e}"
                    )

                time.sleep(
                    RATE_LIMIT_DELAY
                )

    else:

        for i, ch in enumerate(
            selected,
            start=1
        ):

            print(
                f"\n[{i}/{len(selected)}]"
            )

            download_chapter(
                ch,
                OUTPUT_DIR
            )

            time.sleep(
                RATE_LIMIT_DELAY
            )

    print("\n" + "=" * 60)
    print("✅ DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()

