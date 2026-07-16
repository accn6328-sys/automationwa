import os
import re
import sys
import json
import time
import base64
import requests
import urllib.parse
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Load environment keys
load_dotenv()

# --- Scraper config -----------------------------------------------------------
SCRAPER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SKIP_IMAGE_KEYWORDS = (
    "logo", "icon", "spinner", "pixel", "avatar", "sprite", "chevron", "arrow",
    "badge", "cart", "banner", "placeholder", "loading", "star", "rating", "review",
    "profile", "payment", "trust", "secure", "swm_", "uedata", "batch/1/op",
)

# ── Shopify credentials ───────────────────────────────────────────────────────
SHOP_NAME     = "2txc0h-0a"
CLIENT_ID     = "b05f53b40ec22a8396eb1ab7a2849ee1"
CLIENT_SECRET = os.environ.get("SHOPIFY_APP_SECRET", "")

SHOP_URL = f"https://{SHOP_NAME}.myshopify.com"

# ── Token cache ───────────────────────────────────────────────────────────────
_token: str | None = None
_token_expires_at: float = 0


def get_access_token() -> str:
    """
    Request a fresh Admin API access token using the Client Credentials Grant.
    Caches the token and auto-refreshes it 60 seconds before it expires.
    """
    global _token, _token_expires_at

    if _token and time.time() < _token_expires_at - 60:
        return _token

    last_err = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(
                f"{SHOP_URL}/admin/oauth/access_token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
                timeout=12,
            )
            resp.raise_for_status()
            body = resp.json()

            _token = body["access_token"]
            _token_expires_at = time.time() + body.get("expires_in", 86399)
            print("[Auth] Access token obtained (expires in 24 h)")
            return _token
        except Exception as e:
            last_err = e
            print(f"[Auth Warning] Attempt {attempt}/3 failed to obtain access token: {e}")
            if attempt < 3:
                time.sleep(2 * attempt)
    raise last_err


def shopify_headers() -> dict:
    """Return headers with a fresh access token for every Shopify API call."""
    return {
        "X-Shopify-Access-Token": get_access_token(),
        "Content-Type": "application/json",
    }


_shop_domain: str | None = None

def get_storefront_domain() -> str:
    """Fetch the custom domain of the shop, or fallback to SHOP_NAME.myshopify.com."""
    global _shop_domain
    if _shop_domain:
        return _shop_domain
    try:
        r = requests.get(
            f"{SHOP_URL}/admin/api/2025-01/shop.json",
            headers=shopify_headers(),
            timeout=10
        )
        if r.status_code == 200:
            shop = r.json().get("shop", {})
            domain = shop.get("domain")
            if domain:
                _shop_domain = domain
                print(f"[Shopify] Storefront domain resolved to: {domain}")
                return domain
    except Exception as e:
        print(f"[Shopify] Warning: Failed to fetch shop domain: {e}")
    
    fallback = f"{SHOP_NAME}.myshopify.com"
    _shop_domain = fallback
    return fallback


def get_or_create_collection_id(input_str: str) -> int | None:
    """
    Resolves a collection ID or name. If numeric, uses it directly.
    If a name, searches for custom or smart collections on Shopify.
    If it doesn't exist, creates a new custom collection.
    """
    input_str = input_str.strip()
    if not input_str:
        return None
    if input_str.isdigit():
        return int(input_str)

    headers = shopify_headers()
    
    # 1. Search custom collections
    try:
        r = requests.get(
            f"{SHOP_URL}/admin/api/2025-01/custom_collections.json",
            headers=headers,
            params={"title": input_str},
            timeout=10
        )
        if r.status_code == 200:
            collections = r.json().get("custom_collections", [])
            if collections:
                col_id = collections[0]["id"]
                print(f"[Shopify] Found existing custom collection '{input_str}' (ID: {col_id})")
                return col_id
        
        r = requests.get(
            f"{SHOP_URL}/admin/api/2025-01/custom_collections.json",
            headers=headers,
            timeout=10
        )
        if r.status_code == 200:
            collections = r.json().get("custom_collections", [])
            for col in collections:
                if col.get("title", "").strip().lower() == input_str.lower():
                    col_id = col["id"]
                    print(f"[Shopify] Found existing custom collection '{col['title']}' (ID: {col_id})")
                    return col_id
    except Exception as e:
        print(f"[Shopify] Warning: Failed searching custom collections: {e}")

    # 2. Search smart collections
    try:
        r = requests.get(
            f"{SHOP_URL}/admin/api/2025-01/smart_collections.json",
            headers=headers,
            params={"title": input_str},
            timeout=10
        )
        if r.status_code == 200:
            smart_cols = r.json().get("smart_collections", [])
            if smart_cols:
                col_id = smart_cols[0]["id"]
                print(f"[Shopify] Found existing smart collection '{input_str}' (ID: {col_id})")
                return col_id
    except Exception as e:
        print(f"[Shopify] Warning: Failed searching smart collections: {e}")

    # 3. Create new custom collection if not found
    print(f"[Shopify] Collection '{input_str}' not found. Creating new custom collection...")
    try:
        create_payload = {
            "custom_collection": {
                "title": input_str,
                "published": True
            }
        }
        r = requests.post(
            f"{SHOP_URL}/admin/api/2025-01/custom_collections.json",
            headers=headers,
            json=create_payload,
            timeout=10
        )
        if r.status_code == 201:
            new_col = r.json().get("custom_collection", {})
            col_id = new_col.get("id")
            print(f"[Shopify] Created new custom collection '{input_str}' (ID: {col_id})")
            return col_id
        else:
            print(f"[Shopify] Failed to create custom collection. Status: {r.status_code}, Body: {r.text}")
    except Exception as e:
        print(f"[Shopify] Error creating collection '{input_str}': {e}")

    return None


def ensure_no_cod_smart_collection() -> int | None:
    """Ensure that the smart collection 'No COD' exists. If not, create it."""
    headers = shopify_headers()
    try:
        r = requests.get(
            f"{SHOP_URL}/admin/api/2025-01/smart_collections.json",
            headers=headers,
            params={"title": "No COD"},
            timeout=10
        )
        if r.status_code == 200:
            smart_cols = r.json().get("smart_collections", [])
            for c in smart_cols:
                if c.get("title", "").strip().lower() == "no cod":
                    return c["id"]
        
        create_payload = {
            "smart_collection": {
                "title": "No COD",
                "rules": [
                    {
                        "column": "tag",
                        "relation": "equals",
                        "condition": "no-cod"
                    }
                ],
                "published": True
            }
        }
        r = requests.post(
            f"{SHOP_URL}/admin/api/2025-01/smart_collections.json",
            headers=headers,
            json=create_payload,
            timeout=10
        )
        if r.status_code == 201:
            col = r.json().get("smart_collection", {})
            col_id = col.get("id")
            print(f"[Shopify] Created smart collection 'No COD' (ID: {col_id}) for automated tagging exclusion.")
            return col_id
        else:
            print(f"[Shopify Error] Failed to create 'No COD' smart collection. Status: {r.status_code}, Body: {r.text}")
    except Exception as e:
        print(f"[Shopify Error] Exception while ensuring 'No COD' smart collection: {e}")
    return None


def clean_image_url(img_url: str, base_url: str) -> str:
    """Resolve relative URLs, strip Shopify/Amazon resizing parameters."""
    img_url = (img_url or "").strip()
    if not img_url:
        return ""
    if img_url.startswith("//"):
        img_url = "https:" + img_url
    elif not img_url.startswith("http"):
        img_url = urljoin(base_url, img_url)

    if "media-amazon.com" in img_url or "images-amazon.com" in img_url:
        img_url = re.sub(r"\._[A-Z0-9,_-]+(?=\.[a-zA-Z]{3,5}$)", "", img_url)
        img_url = re.sub(r"\._[A-Z]{2}_[^./]+(?=\.[a-zA-Z0-9]+$)", "", img_url)

    if "flipkart" in img_url or "flixcart" in img_url:
        img_url = re.sub(r"/(\d+)/(\d+)/", "/832/832/", img_url)

    img_url = re.sub(
        r'_(?:[0-9]+x[0-9]*|[0-9]*x[0-9]+|thumb|micro|tiny|small|medium|large|grande|compact|master|1024x1024|2048x2048)(?=\.[a-zA-Z0-9]+$)',
        '',
        img_url,
    )
    return img_url.split("?")[0]


def is_valid_image_url(url: str) -> bool:
    """Heuristic filter — reject tracking pixels, page links, banners."""
    if not url or url.startswith("data:"):
        return False
    low = url.lower()
    if ".svg" in low or ".gif" in low:
        return False
    if any(kw in low for kw in SKIP_IMAGE_KEYWORDS):
        return False
    if "amazon." in low and "/dp/" in low and not low.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return False
    if "fls-eu.amazon" in low or "uedata=" in low:
        return False
    if re.search(r"_cb\d+_", low) and "/images/i/" not in low:
        return False
    if "media-amazon.com/images/i/" in low or "images-amazon.com/images/i/" in low:
        return True
    if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif")):
        return True
    if any(x in low for x in ("cdn.shopify.com", "rukminim", "flixcart", "cloudinary", "imgix")):
        return True
    return False


def create_product(
    title,
    description,
    image_urls,
    video_urls,
    price,
    compare_price,
    collection_id=None,
    reviews=None,
    cod_on=True
):
    # Embed videos in body_html if any are found
    embed_html = ""
    for vurl in video_urls:
        if vurl.lower().endswith(".mp4") or "video/mp4" in vurl.lower() or ".mov" in vurl.lower():
            embed_html += f'\n<div class="product-video" style="text-align: center; margin: 20px 0;">\n  <video controls src="{vurl}" style="max-width: 100%; height: auto; border-radius: 8px;" preload="metadata"></video>\n</div>\n'

    if embed_html:
        description = description + "\n" + embed_html

    product = {
        "product": {
            "title":     title,
            "body_html": description,
            "status":    "active",
            "images":    [{"src": url} for url in image_urls],
            "variants":  [{
                "price":            str(price) if price else "",
                "compare_at_price": str(compare_price) if compare_price else None,
                "taxable":          False
            }]
        }
    }

    if not cod_on:
        product["product"]["template_suffix"] = ""
        product["product"]["tags"] = "no-cod, disable-cod, No COD, cod-disabled, releasit-disable, releasit_disable, releasit-no-cod, releasit_no_cod, disable_cod, no_cod"
        ensure_no_cod_smart_collection()

    r = requests.post(
        f"{SHOP_URL}/admin/api/2025-01/products.json",
        headers=shopify_headers(),
        json=product,
    )
    r.raise_for_status()
    created = r.json()["product"]
    print("Created Shopify Product:", created["title"])

    if collection_id:
        collect_payload = {
            "collect": {
                "product_id":    created["id"],
                "collection_id": collection_id,
            }
        }
        requests.post(
            f"{SHOP_URL}/admin/api/2025-01/collects.json",
            headers=shopify_headers(),
            json=collect_payload,
        )

    return created


# ── AI Client bootstrap (Multi-key Gemini setup) ──────────────────────────────
def build_vision_clients() -> list[tuple[OpenAI, str, str]]:
    clients = []
    if OpenAI is None:
        return clients

    gemini_key_vars = ["gemini_pro_key", "GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4"]
    for key_var in gemini_key_vars:
        key = os.getenv(key_var)
        if key and key.strip():
            try:
                gemini_client = OpenAI(
                    api_key=key.strip(),
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                )
                clients.append((gemini_client, "gemini-3.1-flash-lite", f"Gemini ({key_var} - 3.1-flash-lite)"))
                clients.append((gemini_client, "gemini-2.5-flash-lite", f"Gemini ({key_var} - 2.5-flash-lite)"))
                clients.append((gemini_client, "gemini-2.5-flash", f"Gemini ({key_var} - 2.5-flash)"))
            except Exception:
                continue
    return clients


_PROBED_VISION_CLIENTS = None

def get_working_vision_clients() -> list:
    global _PROBED_VISION_CLIENTS
    if _PROBED_VISION_CLIENTS is not None:
        return _PROBED_VISION_CLIENTS

    raw_clients = build_vision_clients()
    if not raw_clients:
        print("[AI] No Gemini vision clients configured.")
        _PROBED_VISION_CLIENTS = []
        return []

    print(f"[AI] Probing {len(raw_clients)} Gemini configuration(s) in parallel...")

    unique: dict[int, tuple] = {}
    extra: list[tuple] = []
    for entry in raw_clients:
        cid = id(entry[0])
        if cid not in unique:
            unique[cid] = entry
        else:
            extra.append(entry)

    def _probe(entry):
        client, model, label = entry
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with just: OK"}],
                timeout=10,
            )
            result = resp.choices[0].message.content
            if result:
                print(f"  [OK] {label} (model: {model})")
                return ("ok", entry)
            return ("empty", entry)
        except Exception as e:
            err = str(e)
            if "429" in err:
                print(f"  [WARN] {label} (model: {model}) — rate-limited (included as fallback)")
                return ("429", entry)
            print(f"  [FAIL] {label} (model: {model}) — failed check: {err[:120]}")
            return ("fail", entry)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    working = []
    passed_cids = set()
    with ThreadPoolExecutor(max_workers=min(len(unique), 6)) as pool:
        futs = {pool.submit(_probe, e): e for e in unique.values()}
        fut_list = list(futs.keys())
        done_map = {}
        for fut in as_completed(futs):
            done_map[id(fut)] = fut.result()
        for fut in fut_list:
            status, entry = done_map[id(fut)]
            if status in ("ok", "429"):
                working.append(entry)
                passed_cids.add(id(entry[0]))

    for entry in extra:
        if id(entry[0]) in passed_cids:
            working.append(entry)

    _PROBED_VISION_CLIENTS = working
    return working


def ai_chat(messages: list[dict], max_tokens: int = 1024) -> str:
    working_clients = get_working_vision_clients()
    if not working_clients:
        raise RuntimeError("No working Gemini AI clients available. Please check your keys in .env")

    last_err = None
    for client, model, label in working_clients:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                timeout=25
            )
            val = resp.choices[0].message.content
            if val:
                return val.strip()
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All Gemini AI clients failed: {last_err}")


def _parse_ai_json(reply: str) -> dict | None:
    try:
        return json.loads(reply)
    except Exception:
        reply = reply.strip()
        if reply.startswith("```"):
            reply = reply.strip("`").strip()
            if reply.lower().startswith("json"):
                reply = reply[4:].strip()
        try:
            return json.loads(reply)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", reply)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    return None
    return None


def generate_title_description_and_pricing(title: str, description: str, scraped_price: str | None = None) -> tuple[str, str, str | None, str | None]:
    sys_msg = {
        "role": "system",
        "content": (
            "You are an expert ecommerce copywriter. Given an existing product title, HTML description, and an optional price, produce:\n"
            "1) A concise SEO-friendly product title (max 80 chars).\n"
            "2) A buyer-focused product description in HTML, referencing and improving the description, with bullet points and key features.\n"
            "3) A suggested retail price (USD or currency unit) and an optional compare-at price. Keep them as plain numbers without symbols.\n"
        )
    }

    user_msg = {
        "role": "user",
        "content": f"Title: {title}\nExisting description HTML: {description}\nScraped price: {scraped_price or 'N/A'}\n\nRespond ONLY as JSON with keys: title, description_html, price, compare_at_price. Keep numbers as plain numerals without symbols."
    }

    try:
        reply = ai_chat([sys_msg, user_msg], max_tokens=1200)
        j = _parse_ai_json(reply)
        if isinstance(j, dict):
            new_title = j.get("title", title)
            new_desc = j.get("description_html", description)
            price = str(j.get("price")) if j.get("price") else scraped_price
            compare = str(j.get("compare_at_price")) if j.get("compare_at_price") else None
            return new_title, new_desc, price, compare
    except Exception as e:
        print(f"[AI Copywriter Warning] SEO generation failed: {e}")

    return title, description, scraped_price, None


# ── Playwright Scraping Fallback (Isolated daemon thread) ─────────────────────
def _fetch_page_with_pw(url: str) -> str | None:
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
                Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
                Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
                Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
                window.chrome={runtime:{}};
            """)
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=25_000)
            try:
                page.wait_for_selector("img", timeout=8000)
            except Exception:
                pass
            time.sleep(3)
            html = page.content()
            browser.close()
            return html
        except Exception as e:
            print(f"    [Playwright] Navigation failed: {type(e).__name__}: {e}")
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
    t.join(timeout=32)
    return res[0]


# ── Universal AI-Based Extractor ──────────────────────────────────────────────
def parse_srcset(srcset_str: str) -> list[str]:
    urls = []
    if not srcset_str:
        return urls
    parts = srcset_str.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if tokens:
            urls.append(tokens[0])
    return urls


def find_json_ld_images(obj, base_url: str, found_list: list):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "image":
                if isinstance(v, str):
                    found_list.append(v)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            found_list.append(item)
                        elif isinstance(item, dict) and item.get("url"):
                            found_list.append(item.get("url"))
                elif isinstance(v, dict) and v.get("url"):
                    found_list.append(v.get("url"))
            else:
                find_json_ld_images(v, base_url, found_list)
    elif isinstance(obj, list):
        for item in obj:
            find_json_ld_images(item, base_url, found_list)


def extract_ld_product_info(obj, found_info: list):
    if isinstance(obj, dict):
        ptype = obj.get("@type")
        types = ptype if isinstance(ptype, list) else [ptype]
        if any(t == "Product" for t in types if isinstance(t, str)):
            found_info.append(obj)
        for v in obj.values():
            extract_ld_product_info(v, found_info)
    elif isinstance(obj, list):
        for item in obj:
            extract_ld_product_info(item, found_info)


def extract_query_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    parts = [p for p in path.split("/") if p.strip()]
    if not parts:
        return parsed.netloc
    slug = max(parts, key=len)
    query = slug.replace("-", " ").replace("_", " ").strip()
    domain = parsed.netloc.replace("www.", "")
    domain_label = domain.split(".")[0]
    return f"{query} {domain_label}"


def parse_images_from_html(html: str, url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    raw_urls = []

    # 1. Grab og:image
    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name")
        if prop == "og:image":
            val = meta.get("content")
            if val:
                raw_urls.append(val)

    # 2. JSON-LD images
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            find_json_ld_images(data, url, raw_urls)
        except Exception:
            continue

    # 3. img src, data-src, srcset
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original", "data-fallback-src"):
            val = img.get(attr)
            if val:
                raw_urls.append(val)
        srcset = img.get("srcset")
        if srcset:
            raw_urls.extend(parse_srcset(srcset))

    # Clean and validate image URLs
    clean_deduped_urls = []
    for raw_url in raw_urls:
        cleaned = clean_image_url(raw_url, url)
        if cleaned and is_valid_image_url(cleaned) and cleaned not in clean_deduped_urls:
            clean_deduped_urls.append(cleaned)

    return clean_deduped_urls


def extract_product_with_ai(url: str) -> dict:
    print(f"Fetching page HTML from {url}...")
    html = None
    try:
        r = requests.get(url, headers=SCRAPER_HEADERS, timeout=12)
        low_text = r.text.lower()
        is_blocked = (
            r.status_code in (403, 503) or
            any(sig in low_text for sig in ("captcha", "robot", "access denied", "just a moment", "cloudflare"))
        )
        if not is_blocked:
            html = r.text
        else:
            print("    [Scraper] Block signals detected (403/503/captcha/cloudflare). Trying Playwright...")
    except Exception as e:
        print(f"    [Scraper] HTTP request failed: {e}. Trying Playwright...")

    if not html:
        html = _fetch_page_with_pw(url)

    candidate_images = []
    if html:
        candidate_images = parse_images_from_html(html, url)

    # Retry ONCE for meesho.com on mobile URL if no images found
    if not candidate_images and "meesho.com" in url.lower():
        mobile_url = url
        if "m.meesho.com" not in url.lower():
            if "://www.meesho.com" in url.lower():
                mobile_url = url.replace("://www.meesho.com", "://m.meesho.com")
            elif "://meesho.com" in url.lower():
                mobile_url = url.replace("://meesho.com", "://m.meesho.com")
        
        if mobile_url != url:
            print(f"    [Scraper] 0 images found. Retrying once against mobile site: {mobile_url}...")
            html_mobile = _fetch_page_with_pw(mobile_url)
            if html_mobile:
                html = html_mobile
                candidate_images = parse_images_from_html(html_mobile, mobile_url)

    # If no images, do NOT substitute, fail clearly
    if not candidate_images:
        print("[Error] Could not extract any images from the actual product page after multiple attempts. "
              "This site is blocking automated access too aggressively. "
              "Try saving the page manually (open it in your browser, Ctrl+S, save as HTML) and "
              "modify this script to read from that local file instead of fetching the live URL.")
        return {"title": "", "description": "", "price": None, "compare_at_price": None, "image_urls": []}

    soup = BeautifulSoup(html, "html.parser")

    # Gather text context
    og_title = ""
    og_desc = ""
    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name")
        if prop == "og:title":
            og_title = meta.get("content") or ""
        elif prop == "og:description":
            og_desc = meta.get("content") or ""

    page_title = soup.title.string.strip() if soup.title else ""

    ld_products = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            extract_ld_product_info(data, ld_products)
        except Exception:
            continue

    ld_text = ""
    if ld_products:
        ld_text = json.dumps(ld_products[:2], indent=2)

    # Invisible cleanup for visible text
    for element in soup(["script", "style", "noscript", "iframe", "head", "header", "footer", "nav"]):
        element.decompose()
    visible_body = soup.get_text(" ", strip=True)
    trimmed_body = visible_body[:4000]

    # If visible text is under 200 chars and candidate_images is empty (guaranteed not empty here, but check matches requirement)
    if len(visible_body) < 200 and not candidate_images:
        return {"title": "", "description": "", "price": None, "compare_at_price": None, "image_urls": []}

    page_text_context = (
        f"HTML Title: {page_title}\n"
        f"og:title: {og_title}\n"
        f"og:description: {og_desc}\n"
        f"JSON-LD Product Block: {ld_text}\n"
        f"Visible Body Excerpt:\n{trimmed_body}"
    )

    print(f"Found {len(candidate_images)} candidate product images. Querying Gemini AI extractor...")

    sys_msg = {
        "role": "system",
        "content": (
            "You are an expert ecommerce data extractor. Your task is to extract exact details from the product page visible text context and select product photos.\n"
            "Respond ONLY with a valid JSON object. Do not explain, wrapper markup, markdown, or leading/trailing text."
        )
    }

    user_msg = {
        "role": "user",
        "content": (
            f"Product Page URL: {url}\n\n"
            f"Candidate Image URLs:\n{json.dumps(candidate_images, indent=2)}\n\n"
            f"Page Text Context:\n{page_text_context}\n\n"
            "Return ONLY JSON with keys:\n"
            "  - title (string: clean product name)\n"
            "  - description_html (string: a clean 3-6 sentence buyer-focused description with paragraphs or list HTML tags, rewritten in your own words. Do not copy description text verbatim)\n"
            "  - price (string: plain number suggesting the retail price, or null)\n"
            "  - compare_at_price (string: plain number suggesting compare-at/original retail price, or null)\n"
            "  - selected_image_urls (array of strings: ONLY the actual product photos of the main item from the candidate list, sorted with the best hero image first. Omit unrelated logos, ads, layout icons, or cross-sell options)"
        )
    }

    try:
        reply = ai_chat([sys_msg, user_msg], max_tokens=1500)
        j = _parse_ai_json(reply)
        if isinstance(j, dict) and j.get("title"):
            print("Successfully extracted product details with Gemini AI.")
            return {
                "title":            str(j.get("title")).strip(),
                "description":      str(j.get("description_html") or "").strip(),
                "price":            str(j.get("price")) if j.get("price") else None,
                "compare_at_price": str(j.get("compare_at_price")) if j.get("compare_at_price") else None,
                "image_urls":       j.get("selected_image_urls") or []
            }
    except Exception as e:
        print(f"[AI Extraction Warning] Universal AI extraction failed: {e}")

    # Fallback to minimal safe defaults
    print("Falling back to safe HTML metadata defaults...")
    fallback_title = og_title or page_title or urlparse(url).netloc or "Product"
    fallback_desc = og_desc or f"Product imported from {url}."
    return {
        "title":            fallback_title,
        "description":      f"<p>{fallback_desc}</p>",
        "price":            None,
        "compare_at_price": None,
        "image_urls":       candidate_images[:8]
    }


def _print_scraped_summary(data: dict) -> None:
    print(f"\n--- Scraped Details ---")
    print(f"Title         : {data.get('title')}")
    desc_plain = BeautifulSoup(data.get("description", ""), "html.parser").get_text(" ", strip=True)
    print(f"Description   : {desc_plain[:160]}{'...' if len(desc_plain) > 160 else ''}")
    print(f"Price         : {data.get('price') or 'not found'}")
    print(f"Compare Price : {data.get('compare_at_price') or 'not found'}")
    print(f"Images found  : {len(data.get('image_urls', []))}")
    for i, img in enumerate(data.get("image_urls", []), 1):
        print(f"  [{i}] {img}")
    print("-----------------------\n")


def post_product_to_whatsapp_channel(created_prod: dict, product_url: str) -> None:
    product_id = created_prod.get("id")
    if not product_id:
        print("[WhatsApp Channel] Cannot post: missing product ID.")
        return

    # Basic idempotency check
    posted_file = "posted_products.json"
    posted_ids = []
    if os.path.exists(posted_file):
        try:
            with open(posted_file, "r") as f:
                posted_ids = json.load(f)
                if not isinstance(posted_ids, list):
                    posted_ids = []
        except Exception:
            pass

    if product_id in posted_ids:
        print(f"[WhatsApp Channel] Product {product_id} already posted. Skipping to prevent double-posting.")
        return

    channel_jid = os.getenv("WHATSAPP_CHANNEL_JID")
    if not channel_jid:
        print("[WhatsApp Channel] Warning: WHATSAPP_CHANNEL_JID not configured in environment. Skipping channel post.")
        return

    print(f"[WhatsApp Channel] Preparing channel post for: {created_prod.get('title')}")

    try:
        # Resolve bot number from app.js status or default env/owner
        bot_number = os.getenv("WHATSAPP_BOT_NUMBER", "916282444918")
        try:
            status_resp = requests.get("http://127.0.0.1:3000/api/status", timeout=4)
            if status_resp.status_code == 200:
                s_data = status_resp.json()
                if s_data.get("botNumber"):
                    bot_number = s_data["botNumber"]
        except Exception as e:
            print(f"[WhatsApp Channel] Note: Could not fetch bot number dynamically: {e}. Using fallback.")

        # Build clean highlight bullets from description HTML
        bullets = []
        body_html = created_prod.get("body_html", "")
        if body_html:
            try:
                soup = BeautifulSoup(body_html, "html.parser")
                for li in soup.find_all("li"):
                    t = li.get_text().strip()
                    if t and len(t) < 95:
                        bullets.append(t)
                        if len(bullets) >= 3:
                            break
                if len(bullets) < 2:
                    for p in soup.find_all(["p", "div"]):
                        for sentence in p.get_text().split("."):
                            sentence = sentence.strip()
                            if sentence and 12 < len(sentence) < 85:
                                bullets.append(sentence)
                                if len(bullets) >= 3:
                                    break
                        if len(bullets) >= 3:
                            break
            except Exception as e:
                print(f"[WhatsApp Channel] Bullet parsing error: {e}")

        # Format highlights
        highlight_text = ""
        if bullets:
            highlight_text = "\n" + "\n".join([f"• {b}" for b in bullets])

        # Get price
        price = ""
        variants = created_prod.get("variants", [])
        if variants:
            price = variants[0].get("price", "")
        if not price:
            price = created_prod.get("price", "")

        price_text = f"\n*Price:* ₹{price}" if price else ""

        # Deep link keyword
        keyword = created_prod.get("handle", created_prod.get("title", ""))
        keyword_enc = urllib.parse.quote(keyword)
        wa_link = f"wa.me/{bot_number}?text={keyword_enc}"

        # Construct scannable text message
        post_text = (
            f"*{created_prod.get('title')}*\n"
            f"{price_text}"
            f"{highlight_text}\n\n"
            f"🛒 *Buy on site:* {product_url}\n"
            f"💬 *Buy on WhatsApp:* {wa_link}"
        )

        # Base64-encode first product image
        image_data = None
        images = created_prod.get("images", [])
        if images and "src" in images[0]:
            img_url = images[0]["src"]
            try:
                img_resp = requests.get(img_url, timeout=10)
                if img_resp.status_code == 200:
                    img_base64 = base64.b64encode(img_resp.content).decode("utf-8")
                    image_data = f"data:image/jpeg;base64,{img_base64}"
            except Exception as e:
                print(f"[WhatsApp Channel] Warning: Failed to encode product image: {e}")

        # Hit /api/send endpoint to dispatch to channel
        payload = {
            "number": channel_jid,
            "text": post_text
        }
        if image_data:
            payload["image"] = image_data

        send_url = "http://127.0.0.1:3000/api/send"
        resp = requests.post(send_url, json=payload, timeout=15)
        
        if resp.status_code == 200:
            print("[WhatsApp Channel] Successfully posted product to channel.")
            # Record in posted list
            posted_ids.append(product_id)
            with open(posted_file, "w") as f:
                json.dump(posted_ids, f, indent=2)
        else:
            raise Exception(f"Server returned status {resp.status_code}: {resp.text}")

    except Exception as e:
        print(f"[WhatsApp Channel Error] Failed to post to channel: {e}")
        # Log payload and error to failed_channel_posts.log
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "product_id": product_id,
            "error": str(e),
            "product_data": created_prod,
            "product_url": product_url
        }
        try:
            with open("failed_channel_posts.log", "a") as f:
                f.write(json.dumps(log_entry, indent=2) + "\n\n")
        except Exception:
            pass


# ── Main Flow ─────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Shopify AI Universal Product Pusher (pushshop.py)")
    print("=" * 60)

    # Build and check clients
    working_clients = get_working_vision_clients()
    if not working_clients:
        print("[Error] No working Gemini AI clients. Please configure gemini_pro_key or GEMINI_API_KEY in .env")
        sys.exit(1)

    product_url = input("Enter product URL: ").strip()
    if not product_url:
        print("[Error] Product URL is required.")
        sys.exit(1)

    cod_choice = input("Turn on Cash on Delivery (COD)? (y/n) [y]: ").strip().lower()
    cod_on = (cod_choice != "n")

    collection_name_or_id = input("Enter collection name or ID (optional, blank if none): ").strip()

    # Extract
    data = extract_product_with_ai(product_url)
    if not data.get("title") and not data.get("image_urls"):
        print("[Error] Extraction returned empty data. Aborting.")
        sys.exit(1)

    # Print Summary
    _print_scraped_summary(data)

    # Belt and braces image validation
    selected_image_urls = data.get("image_urls", [])
    validated = [url for url in selected_image_urls if is_valid_image_url(url)]
    if not validated:
        print("[Error] No valid product images after validation. Cannot push to Shopify.")
        sys.exit(1)
    print(f"Validated images: {len(validated)} of {len(selected_image_urls)}")
    data["image_urls"] = validated

    print("\nWhat do you want to do?")
    print("  1) Rewrite title, description, price & compare price with AI, then push")
    print("  2) Push scraped data as-is (images already validated)")
    print("  3) Cancel")
    mode = input("Choose (1/2/3): ").strip()

    if mode == "3":
        print("Cancelled.")
        sys.exit()
    if mode not in ("1", "2"):
        print("Invalid choice.")
        sys.exit()

    final_title = data["title"]
    final_desc = data["description"]
    final_price = data.get("price")
    final_compare = data.get("compare_at_price")

    if mode == "1":
        print("\nRewriting copy with AI Copywriter...")
        ai_title, ai_desc, ai_price, ai_compare = generate_title_description_and_pricing(
            data["title"], data["description"], data.get("price")
        )
        print(f"\nAI Title         : {ai_title}")
        print(f"AI Price         : {ai_price}")
        print(f"AI Compare Price : {ai_compare}")
        print(f"AI Description   : {BeautifulSoup(ai_desc, 'html.parser').get_text(' ', strip=True)[:200]}...")

        if input("Use AI title? (y/n) [y]: ").strip().lower() != "n":
            final_title = ai_title
        if input("Use AI description? (y/n) [y]: ").strip().lower() != "n":
            final_desc = ai_desc
        if ai_price and input(f"Use AI price {ai_price}? (y/n) [y]: ").strip().lower() != "n":
            final_price = ai_price
        if ai_compare and input(f"Use AI compare price {ai_compare}? (y/n) [n]: ").strip().lower() == "y":
            final_compare = ai_compare

    # Manual overrides
    override = input(f"\nTitle [{final_title}] (Enter to keep): ").strip()
    if override:
        final_title = override

    if not final_price:
        final_price = input("Price (required): ").strip()
    else:
        p = input(f"Price [{final_price}] (Enter to keep): ").strip()
        if p:
            final_price = p

    if final_compare:
        c = input(f"Compare Price [{final_compare}] (Enter to keep, blank to clear): ").strip()
        final_compare = c if c else None
    else:
        final_compare = input("Compare Price (blank if none): ").strip() or None

    if not final_price:
        print("Price is required. Cancelled.")
        sys.exit(1)

    confirm = input(f"\nPush '{final_title}' to Shopify with {len(data['image_urls'])} image(s)? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        sys.exit()

    # Resolve collection ID
    collection_id = get_or_create_collection_id(collection_name_or_id) if collection_name_or_id else None

    # Push to Shopify
    created_prod = create_product(
        title=final_title,
        description=final_desc,
        image_urls=data["image_urls"],
        video_urls=[],
        price=final_price,
        compare_price=final_compare,
        collection_id=collection_id,
        reviews=None,
        cod_on=cod_on
    )

    if created_prod and "handle" in created_prod:
        domain = get_storefront_domain()
        product_url = f"https://{domain}/products/{created_prod['handle']}"
        print(f"\n[Success] Product published live on Shopify storefront!")
        print(f"Storefront URL: {product_url}")
        
        # Post to WhatsApp Channel using existing Baileys session
        post_product_to_whatsapp_channel(created_prod, product_url)


if __name__ == "__main__":
    main()
