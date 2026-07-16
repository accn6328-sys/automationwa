#!/usr/bin/env python3
"""
find_product.py — Simple Video -> Product Link Finder

What it does:
  1. Lists video files in the "videos" folder (next to this script).
  2. Lets you pick one (type its number).
  3. Extracts a few frames from the video using ffmpeg.
  4. Asks Gemini Vision to identify the product shown.
  5. Asks Gemini (with Google Search grounding) to find real ecommerce
     product page links for that exact product.
  6. Double-checks the top candidates by comparing their page image against
     the video frames, so you get one confident best link at the end.

FIXES vs. original:
  - identify_product() now prints the raw model reply whenever it can't
    pull a product_name/search_query out of it, and HARD FAILS instead of
    silently continuing with "Unknown product" (which was poisoning every
    downstream search).
  - fetch_og_image() now falls back to a headless-browser fetch when a
    plain `requests` call can't find an og:image (Amazon frequently serves
    a bot-check page to non-browser clients, which has no og:image tag —
    that's why both your candidates showed "no listing photo found").
  - The "confident Amazon match" gate now REQUIRES a real photo comparison
    (had_page_image=True) in addition to score >= 60. A high score with no
    photo comparison is not a verified match, it's just the original guess
    getting echoed back — the old code was treating those the same way.

Requirements:
  pip install requests beautifulsoup4 python-dotenv playwright --break-system-packages
  playwright install chromium
  ffmpeg must be installed and on PATH.
  A .env file (in this same folder) with one of:
      GEMINI_API_KEY=your_key_here
      gemini_pro_key=your_key_here

Usage:
  python find_product.py
"""

import os
import sys
import json
import re
import time
import base64
import subprocess
import urllib.parse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VIDEOS_DIR = os.path.join(SCRIPT_DIR, "videos")
FRAMES_DIR = os.path.join(SCRIPT_DIR, "frames_tmp")

# Set to True (or export DEBUG=1) to always see raw model replies, not just on failure.
DEBUG = os.environ.get("DEBUG", "0") == "1"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

SHOP_DOMAINS = (
    "amazon.in", "amazon.com", "flipkart.com", "meesho.com",
    "myntra.com", "ajio.com", "nykaa.com", "jiomart.com", "snapdeal.com",
)


# ── Small helpers ─────────────────────────────────────────────────────────

def fail(msg: str):
    print(f"\n[Error] {msg}")
    sys.exit(1)


def debug_dump(label: str, text: str):
    preview = (text or "")[:600]
    print(f"\n  [debug] {label} raw model reply (first 600 chars):")
    print(f"  ----------------------------------------------------")
    print(f"  {preview!r}")
    print(f"  ----------------------------------------------------")


def platform_name(url: str) -> str:
    low = url.lower()
    for domain, name in (
        ("amazon.in", "Amazon India"), ("amazon.com", "Amazon"),
        ("flipkart.com", "Flipkart"), ("meesho.com", "Meesho"),
        ("myntra.com", "Myntra"), ("ajio.com", "Ajio"),
        ("nykaa.com", "Nykaa"), ("jiomart.com", "JioMart"),
        ("snapdeal.com", "Snapdeal"),
    ):
        if domain in low:
            return name
    return "Other"


def is_shop_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    low = url.lower()
    return any(d in low for d in SHOP_DOMAINS)


def json_from_text(raw: str) -> dict:
    """Best-effort JSON extraction from an AI text reply."""
    if not raw:
        return {}
    t = raw.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", t)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def image_part(path: str) -> dict:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return {"inline_data": {"mime_type": "image/jpeg", "data": data}}


class GeminiQuotaError(Exception):
    """Raised when the Gemini API quota/rate limit is exceeded."""
    pass


def find_working_key(model: str = "gemini-3.1-flash-lite") -> str:
    candidates = [
        ("GEMINI_API_KEY_3", os.environ.get("GEMINI_API_KEY_3")),
        ("GEMINI_API_KEY_4", os.environ.get("GEMINI_API_KEY_4")),
        ("GEMINI_API_KEY_2", os.environ.get("GEMINI_API_KEY_2")),
        ("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY")),
        ("gemini_pro_key", os.environ.get("gemini_pro_key")),
    ]
    candidates = [(name, val) for name, val in candidates if val]
    if not candidates:
        return ""

    for name, val in candidates:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={val}"
        payload = {"contents": [{"parts": [{"text": "Hello"}]}]}
        try:
            r = requests.post(url, json=payload, timeout=4)
            if r.status_code == 200:
                return val
        except Exception:
            continue
    return candidates[0][1]


def generate(contents: list, model: str = "gemini-3.1-flash-lite", use_search_grounding: bool = False) -> tuple[str, list[str]]:
    models_to_try = [model]
    if not use_search_grounding:
        for fallback in ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

    last_err = None
    for target_model in models_to_try:
        key = find_working_key(target_model)
        if not key:
            continue

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={key}"

        processed_parts = []
        for part in contents:
            if isinstance(part, dict):
                new_part = {}
                for k, v in part.items():
                    if k == "inline_data":
                        new_val = {}
                        if isinstance(v, dict):
                            for ik, iv in v.items():
                                if ik == "mime_type":
                                    new_val["mimeType"] = iv
                                else:
                                    new_val[ik] = iv
                        new_part["inlineData"] = new_val
                    else:
                        new_part[k] = v
                processed_parts.append(new_part)
            else:
                processed_parts.append(part)

        payload = {"contents": [{"parts": processed_parts}]}
        if use_search_grounding and "gemini" in target_model.lower():
            payload["tools"] = [{"googleSearch": {}}]

        for attempt in range(1, 4):
            try:
                r = requests.post(url, json=payload, timeout=60)

                if r.status_code == 429:
                    raise GeminiQuotaError(f"API daily/rate limit quota exceeded (429) for {target_model}.")

                if r.status_code >= 500:
                    if attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        r.raise_for_status()

                if r.status_code >= 400:
                    # Surface the actual error body instead of swallowing it —
                    # this is what was hiding why identification failed.
                    print(f"  [generate] {target_model} returned HTTP {r.status_code}: {r.text[:400]}")
                    r.raise_for_status()

                data = r.json()

                if "candidates" not in data or not data["candidates"]:
                    # Blocked by safety filters, empty response, etc.
                    print(f"  [generate] {target_model} returned no candidates. Full response: {json.dumps(data)[:400]}")
                    last_err = RuntimeError("No candidates in response")
                    break

                candidate = data["candidates"][0]
                parts_out = candidate.get("content", {}).get("parts", [])
                if not parts_out or "text" not in parts_out[0]:
                    finish_reason = candidate.get("finishReason", "unknown")
                    print(f"  [generate] {target_model} returned an empty part (finishReason={finish_reason}).")
                    last_err = RuntimeError(f"Empty response part, finishReason={finish_reason}")
                    break

                text = parts_out[0]["text"].strip()

                grounding_urls = []
                if use_search_grounding:
                    chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
                    for chunk in chunks:
                        uri = chunk.get("web", {}).get("uri", "")
                        if uri:
                            grounding_urls.append(uri)

                return text, grounding_urls

            except GeminiQuotaError as e:
                last_err = e
                print(f"  [generate] Model {target_model} rate limited/quota exceeded. Trying fallback...")
                break
            except requests.exceptions.HTTPError as e:
                if r.status_code == 429:
                    last_err = GeminiQuotaError(f"API daily/rate limit quota exceeded for {target_model}.")
                    print(f"  [generate] Model {target_model} rate limited/quota exceeded. Trying fallback...")
                    break
                if attempt < 3:
                    time.sleep(2 ** attempt)
                else:
                    last_err = e
            except Exception as e:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                else:
                    last_err = e

    if last_err and isinstance(last_err, GeminiQuotaError):
        raise last_err
    raise RuntimeError(f"All models failed. Last error: {last_err}")


# ── Step 1: pick a video ───────────────────────────────────────────────────

def pick_video() -> str:
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    exts = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
    files = sorted(
        f for f in os.listdir(VIDEOS_DIR)
        if f.lower().endswith(exts) and os.path.isfile(os.path.join(VIDEOS_DIR, f))
    )
    if not files:
        fail(f"No video files found in {VIDEOS_DIR}. Put a video there and re-run.")

    print(f"\nVideos found in '{os.path.basename(VIDEOS_DIR)}':")
    for i, f in enumerate(files, 1):
        print(f"  {i}) {f}")

    choice = input(f"\nPick a video (1-{len(files)}) [1]: ").strip() or "1"
    if os.path.isfile(choice):
        return choice
    if not choice.isdigit() or not (1 <= int(choice) <= len(files)):
        fail("Invalid choice.")

    return os.path.join(VIDEOS_DIR, files[int(choice) - 1])


# ── Step 2: extract frames ─────────────────────────────────────────────────

def video_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True,
        )
        return max(float((r.stdout or "0").strip()), 1.0)
    except Exception:
        return 15.0


def extract_frames(video_path: str) -> list:
    os.makedirs(FRAMES_DIR, exist_ok=True)
    for old in os.listdir(FRAMES_DIR):
        try:
            os.remove(os.path.join(FRAMES_DIR, old))
        except Exception:
            pass

    duration = video_duration(video_path)
    points = [0.15, 0.35, 0.5, 0.65, 0.85]
    frames = []
    print("\n[1/3] Extracting frames from the video...")
    for i, pct in enumerate(points, 1):
        ts = max(0.5, min(duration - 0.2, duration * pct))
        out = os.path.join(FRAMES_DIR, f"frame_{i}.jpg")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", video_path,
                 "-frames:v", "1", "-q:v", "2", out],
                capture_output=True, timeout=30,
            )
        except Exception as e:
            print(f"  [Warning] Frame {i} extraction failed: {e}")
            continue
        if os.path.exists(out) and os.path.getsize(out) > 0:
            try:
                from PIL import Image
                img = Image.open(out)
                img.thumbnail((768, 768))
                img.save(out, "JPEG", quality=85)
            except Exception:
                pass
            frames.append(out)
            print(f"  Frame {i} OK")

    if not frames:
        fail("Could not extract any frames. Is ffmpeg installed and on PATH?")
    return frames


# ── Step 3: identify the product ───────────────────────────────────────────

def identify_product(frames: list) -> dict:
    print("\n[2/3] Identifying the product from the frames...")
    parts = [image_part(p) for p in frames]
    parts.append({"text": (
        "These frames are from one product video. Identify the single product shown "
        "(ignore any background, hands, or people). Return ONLY JSON with keys:\n"
        '  "product_name": short common name of the product\n'
        '  "visual_signature": one sentence describing exact shape, color, material, '
        "size, and any visible text/branding\n"
        '  "search_query": one precise search phrase (include brand if visible, plus '
        "distinctive visual details) that would find this exact product for sale online"
    )})

    try:
        text, _ = generate(parts, model="gemini-3.1-flash-lite")
    except GeminiQuotaError:
        print("[Gemini] Quota exceeded, stopping")
        sys.exit(1)
    except RuntimeError as e:
        fail(f"Could not identify the product — the model call failed: {e}")

    if DEBUG:
        debug_dump("identify_product", text)

    data = json_from_text(text)

    product_name = str(data.get("product_name") or "").strip()
    visual_signature = str(data.get("visual_signature") or "").strip()
    search_query = str(data.get("search_query") or "").strip()

    # HARD FAIL instead of silently continuing with "Unknown product" —
    # that garbage value was what poisoned every downstream search in your run.
    if not product_name or not search_query:
        debug_dump("identify_product (FAILED TO PARSE)", text)
        fail(
            "Could not identify a product from the video frames. The raw model reply "
            "is printed above — it likely wasn't valid JSON, or the model said it "
            "couldn't recognize the product. Try a closer, better-lit, single-product "
            "video, or re-run with DEBUG=1 for more detail."
        )

    print(f"  Product      : {product_name}")
    if visual_signature:
        print(f"  Description  : {visual_signature}")
    print(f"  Search query : {search_query}")

    return {
        "product_name": product_name,
        "visual_signature": visual_signature,
        "search_query": search_query,
    }


# ── Step 4: search Amazon India candidates exhaustively ───────────────────

def _fetch_amazon_pw(query: str) -> list[str]:
    def _nav():
        from playwright.sync_api import sync_playwright
        pw = None
        browser = None
        try:
            pw_cm = sync_playwright()
            pw = pw_cm.__enter__()
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            ctx = browser.new_context(
                viewport={"width": 1536, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
            """)
            page = ctx.new_page()
            quoted = urllib.parse.quote(query)
            url = f"https://www.amazon.in/s?k={quoted}"
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            time.sleep(3)
            html = page.content()
            browser.close()
            return html
        except Exception as e:
            print(f"    [Playwright Amazon] Navigation failed: {type(e).__name__}: {e}")
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            return None
        finally:
            if pw:
                try:
                    pw_cm.__exit__(None, None, None)
                except Exception:
                    pass

    import threading
    res = [None]
    def _run():
        res[0] = _nav()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=35)

    html = res[0]
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    amazon_urls = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        decoded_href = urllib.parse.unquote(href)
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", decoded_href, re.IGNORECASE)
        if m:
            asin = m.group(1).upper()
            clean_url = f"https://www.amazon.in/dp/{asin}"
            if clean_url not in seen:
                seen.add(clean_url)
                amazon_urls.append(clean_url)
    return amazon_urls


def search_amazon_candidates(frames: list, info: dict) -> list:
    print("\n[Amazon Search] Looking for Amazon India candidates...")
    amazon_urls = []
    seen = set()

    print("  [Amazon Method A] Trying Serper site:amazon.in search...")
    serper_key = os.getenv("SERPER_API_KEY")
    if serper_key:
        try:
            q = f"{info['search_query']} site:amazon.in"
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": q, "num": 10},
                timeout=10
            )
            if r.status_code == 200:
                for item in r.json().get("organic", []):
                    link = item.get("link", "")
                    if "amazon.in" in link:
                        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", link, re.IGNORECASE)
                        if m:
                            asin = m.group(1).upper()
                            clean_url = f"https://www.amazon.in/dp/{asin}"
                            if clean_url not in seen:
                                seen.add(clean_url)
                                amazon_urls.append((clean_url, 70))
        except Exception as e:
            print(f"  [Amazon Search] Serper method failed: {e}")
    else:
        print("  [Amazon Method A] Skipped: SERPER_API_KEY not set.")

    if amazon_urls:
        print(f"  [Amazon Method A] Success: Found {len(amazon_urls)} candidate(s).")
        return [{"platform": "Amazon India", "title": info["product_name"], "url": url, "confidence": conf} for url, conf in amazon_urls[:5]]

    print("  [Amazon Method B] Trying DuckDuckGo site search...")
    try:
        quoted = urllib.parse.quote(info["search_query"])
        url = f"https://www.duckduckgo.com/html/?q={quoted}+site:amazon.in"
        r = requests.get(url, headers=HTTP_HEADERS, timeout=12)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                decoded_href = urllib.parse.unquote(href)
                if "amazon.in" in decoded_href:
                    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", decoded_href, re.IGNORECASE)
                    if m:
                        asin = m.group(1).upper()
                        clean_url = f"https://www.amazon.in/dp/{asin}"
                        if clean_url not in seen:
                            seen.add(clean_url)
                            amazon_urls.append((clean_url, 55))
    except Exception as e:
        print(f"  [Amazon Search] DuckDuckGo method failed: {e}")

    if amazon_urls:
        print(f"  [Amazon Method B] Success: Found {len(amazon_urls)} candidate(s).")
        return [{"platform": "Amazon India", "title": info["product_name"], "url": url, "confidence": conf} for url, conf in amazon_urls[:5]]

    print("  [Amazon Method C] Trying Playwright search...")
    try:
        p_urls = _fetch_amazon_pw(info["search_query"])
        for url in p_urls:
            if url not in seen:
                seen.add(url)
                amazon_urls.append((url, 50))
    except Exception as e:
        print(f"  [Amazon Search] Playwright method failed: {e}")

    if amazon_urls:
        print(f"  [Amazon Method C] Success: Found {len(amazon_urls)} candidate(s).")
        return [{"platform": "Amazon India", "title": info["product_name"], "url": url, "confidence": conf} for url, conf in amazon_urls[:5]]

    print("  [Amazon Search] No Amazon India candidates found.")
    return []


# ── Step 5: search other platforms (Flipkart, Meesho, etc.) ───────────────

def call_serper_search(query: str) -> list:
    key = os.getenv("SERPER_API_KEY")
    if not key:
        return []
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": key, "Content-Type": "application/json"}
    site_filter = " OR ".join(f"site:{d}" for d in SHOP_DOMAINS)
    full_query = f"{query} ({site_filter})"
    try:
        r = requests.post(url, headers=headers, json={"q": full_query, "num": 10}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            urls = []
            for item in data.get("organic", []):
                link = item.get("link")
                if link and is_shop_url(link):
                    urls.append(link)
            return urls
    except Exception as e:
        print(f"  [Serper] Search failed: {e}")
    return []


def search_other_platforms(frames: list, info: dict) -> list:
    print("\n[Other Platforms Search] Searching the web for the exact product...")

    prompt = (
        "Use the attached product photos as the reference. Search the web and find "
        "real ecommerce PRODUCT PAGE links (not search pages, not category pages, not "
        "homepages) where this exact same product is sold. Strongly prefer Indian sites: "
        "Amazon India (amazon.in), Flipkart, Meesho, Myntra, Ajio, Nykaa, JioMart — but "
        "any legitimate ecommerce product page is fine if it's a strong match.\n\n"
        f"Product: {info['product_name']}\n"
        f"Visual details: {info['visual_signature']}\n"
        f"Search phrase: {info['search_query']}\n\n"
        "Return ONLY JSON in this exact shape:\n"
        '{"candidates": [{"platform": "...", "title": "...", "url": "...", '
        '"confidence": 0-100}]}\n'
        "confidence should reflect how sure you are this is the SAME product (not just "
        "similar). Only include links you actually found through search, do not invent URLs."
    )
    parts = [image_part(p) for p in frames[:4]] + [{"text": prompt}]

    grounding_urls = []
    data = {}
    try:
        text, grounding_urls = generate(parts, model="gemini-3.1-flash-lite", use_search_grounding=True)
        if DEBUG:
            debug_dump("search_other_platforms", text)
        data = json_from_text(text)
        if not data:
            debug_dump("search_other_platforms (FAILED TO PARSE)", text)
    except GeminiQuotaError:
        print("[Gemini] Quota exceeded, stopping")
        sys.exit(1)
    except Exception as e:
        print(f"  [Gemini Grounding] Grounding query failed: {e}")

    candidates = []
    seen_urls = set()

    for row in data.get("candidates", []) if isinstance(data, dict) else []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", "")).strip()
        if not url.startswith("http") or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append({
            "platform": row.get("platform") or platform_name(url),
            "title": row.get("title") or info["product_name"],
            "url": url,
            "confidence": int(row.get("confidence") or 50),
        })

    for url in grounding_urls:
        if url not in seen_urls and is_shop_url(url):
            seen_urls.add(url)
            candidates.append({
                "platform": platform_name(url),
                "title": info["product_name"],
                "url": url,
                "confidence": 55,
            })

    if not candidates:
        print("  [Serper] Gemini grounding returned zero candidates. Trying Serper Google Search fallback...")
        serper_urls = call_serper_search(info["search_query"])
        for url in serper_urls:
            if url not in seen_urls:
                seen_urls.add(url)
                candidates.append({
                    "platform": platform_name(url),
                    "title": info["product_name"],
                    "url": url,
                    "confidence": 60,
                })

    if not candidates:
        fail(
            "No product link candidates were found. Try a clearer video "
            "(closer, well-lit, single product) and re-run."
        )

    print(f"  Found {len(candidates)} candidate link(s).")
    return candidates


# ── Step 6: verify candidate against the video frames ─────────────────────

def fetch_og_image(url: str) -> bytes | None:
    """Best-effort fetch of a product page's main image. Never raises.
    Tries a plain request first, falling back to a headless browser if that
    fails to find an og:image (common with Amazon, which serves a bot-check
    page to non-browser clients)."""
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=10, allow_redirects=True)
        if r.status_code < 400:
            soup = BeautifulSoup(r.text, "html.parser")
            img_tag = soup.find("meta", property="og:image")
            img_url = img_tag.get("content") if img_tag else None
            if img_url:
                img_url = urllib.parse.urljoin(r.url, img_url)
                img_resp = requests.get(img_url, headers=HTTP_HEADERS, timeout=10)
                if img_resp.status_code < 400 and len(img_resp.content) > 500:
                    return img_resp.content
    except Exception:
        pass

    # Fallback: plain requests likely hit a bot-check page. Try a real browser.
    return _fetch_page_image_pw(url)


def _fetch_page_image_pw(url: str) -> bytes | None:
    def _nav():
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                ctx = browser.new_context(
                    viewport={"width": 1366, "height": 900},
                    user_agent=HTTP_HEADERS["User-Agent"],
                )
                ctx.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                """)
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                time.sleep(2)
                html = page.content()
                final_url = page.url
                browser.close()
                return html, final_url
        except Exception as e:
            print(f"    [Playwright verify] Navigation failed for {url}: {type(e).__name__}: {e}")
            return None, None

    import threading
    res = [None, None]
    def _run():
        res[0], res[1] = _nav()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=30)

    html, final_url = res
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    img_url = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        img_url = og["content"]
    else:
        # Amazon-specific fallback: main product image tag
        landing = soup.find("img", id="landingImage") or soup.find("img", {"data-old-hires": True})
        if landing:
            img_url = landing.get("data-old-hires") or landing.get("src")

    if not img_url:
        return None

    img_url = urllib.parse.urljoin(final_url or url, img_url)
    try:
        img_resp = requests.get(img_url, headers=HTTP_HEADERS, timeout=10)
        if img_resp.status_code < 400 and len(img_resp.content) > 500:
            return img_resp.content
    except Exception:
        pass
    return None


def verify_candidate(frames: list, candidate: dict) -> dict:
    """Adds a 'verified_score' and 'reason' to the candidate. Never raises —
    on any failure it just keeps the AI's original confidence score, but
    that fallback score is treated as UNVERIFIED, not confirmed (see main())."""
    page_image = fetch_og_image(candidate["url"])

    parts = [image_part(p) for p in frames[:3]]
    if page_image:
        b64 = base64.b64encode(page_image).decode("utf-8")
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    parts.append({"text": (
        "Compare the product in the video frames with this ecommerce listing. "
        f"Listing title: {candidate['title']}\n"
        "If a listing photo is attached, weigh it heavily. Return ONLY JSON with keys: "
        '"match_score" (0-100) and "reason" (one short sentence).'
    )})

    try:
        text, _ = generate(parts, model="gemini-3.1-flash-lite")
        if DEBUG:
            debug_dump(f"verify_candidate ({candidate['url']})", text)
        data = json_from_text(text)
        candidate["verified_score"] = int(float(data.get("match_score", candidate["confidence"])))
        candidate["reason"] = str(data.get("reason", "")).strip()
    except GeminiQuotaError:
        print("[Gemini] Quota exceeded, stopping")
        sys.exit(1)
    except Exception:
        candidate["verified_score"] = candidate["confidence"]
        candidate["reason"] = "Could not verify with a page image; using AI's initial confidence."

    candidate["had_page_image"] = page_image is not None
    return candidate


# ── handle_product_search (Allows importing as module) ────────────────────

def handle_product_search():
    main()


# ── Main ────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Video -> Exact Product Link Finder")
    print("=" * 55)

    video_path = pick_video()
    print(f"Selected video: {video_path}")

    frames = extract_frames(video_path)
    info = identify_product(frames)  # now hard-fails on bad identification

    amazon_candidates = search_amazon_candidates(frames, info)
    verified = []

    if amazon_candidates:
        print(f"\nVerifying {len(amazon_candidates)} Amazon candidate(s) against the video...")
        verified_amazon = [verify_candidate(frames, c) for c in amazon_candidates]

        # A "confident" match now REQUIRES an actual photo comparison.
        # A high score with had_page_image=False is just the unverified
        # original guess bouncing back — that's what produced the false
        # "70/100" result on both candidates in your run.
        has_good_amazon = any(
            c.get("verified_score", 0) >= 60 and c.get("had_page_image")
            for c in verified_amazon
        )
        if has_good_amazon:
            print("\n[Success] Found a confident, photo-verified Amazon match. Skipping other platforms.")
            verified = verified_amazon
        else:
            print("\n[Info] Amazon candidates were found, but none could be photo-verified with high confidence.")

    if not verified:
        print("\n[Info] Amazon did not yield a confident, verified match.")
        print("Searching other platforms...")
        other_candidates = search_other_platforms(frames, info)

        other_candidates.sort(key=lambda c: -c["confidence"])
        to_verify = other_candidates[:6]
        print(f"\nVerifying top {len(to_verify)} candidate(s) against the video...")
        verified = [verify_candidate(frames, c) for c in to_verify]

        # If none of these are photo-verified either, and the earlier Amazon
        # candidates existed, bring those back in as a last resort so the
        # user still sees something instead of nothing.
        if not any(c.get("had_page_image") for c in verified) and amazon_candidates:
            verified = verified + verified_amazon

    def sort_key(c):
        # Photo-verified matches always outrank unverified guesses now.
        verified_bonus = 1 if c.get("had_page_image") else 0
        amazon_bonus = 1 if "amazon" in c["url"].lower() else 0
        return (-verified_bonus, -c["verified_score"], -amazon_bonus)

    verified.sort(key=sort_key)

    print("\n" + "=" * 55)
    print("RESULTS (best match first)")
    print("=" * 55)
    for i, c in enumerate(verified, 1):
        img_note = "" if c["had_page_image"] else "  (UNVERIFIED — no listing photo could be compared)"
        print(f"\n{i}. [{c['platform']}] match={c['verified_score']}/100{img_note}")
        print(f"   {c['title'][:100]}")
        print(f"   {c['url']}")
        if c.get("reason"):
            print(f"   Reason: {c['reason']}")

    best = verified[0]
    print("\n" + "*" * 55)
    print("BEST MATCH")
    print("*" * 55)
    print(f"  {best['platform']} — match {best['verified_score']}/100")
    if not best.get("had_page_image"):
        print("  ⚠ UNVERIFIED: could not fetch a listing photo to confirm this visually.")
    print(f"  {best['url']}")
    print("*" * 55)


if __name__ == "__main__":
    main()