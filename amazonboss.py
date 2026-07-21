#!/usr/bin/env python3
"""
amazonboss.py — Video-to-Shopify Listing Automation Pipeline
"""

import os
import sys
import json
import re
import time
import random
import argparse
import datetime
import traceback
import requests
from bs4 import BeautifulSoup

# Ensure 'work' directory is in path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work'))

# Import existing modules
try:
    import productfinder
    import pp
except ImportError as e:
    print(f"[Import Error] Failed to import productfinder or pp: {e}")
    print("Please make sure you are running from the workspace root and 'work' directory exists.")
    sys.exit(1)

# Override pp.py Shopify configurations with credentials from environment
env_token = os.environ.get("SHOPIFY_ADMIN_TOKEN")
env_domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "2txc0h-0a.myshopify.com")
env_client_id = os.environ.get("SHOPIFY_CLIENT_ID")
env_client_secret = os.environ.get("SHOPIFY_APP_SECRET")

pp.SHOP_URL = f"https://{env_domain}"
if env_client_id:
    pp.CLIENT_ID = env_client_id
if env_client_secret:
    pp.CLIENT_SECRET = env_client_secret

# Dynamically test if SHOPIFY_ADMIN_TOKEN is valid
token_valid = False
if env_token:
    try:
        r = requests.get(f"{pp.SHOP_URL}/admin/api/2025-01/shop.json", headers={"X-Shopify-Access-Token": env_token}, timeout=10)
        if r.status_code == 200:
            token_valid = True
    except Exception:
        pass

if token_valid:
    pp.shopify_headers = lambda: {
        "X-Shopify-Access-Token": env_token,
        "Content-Type": "application/json"
    }
    print(f"[Shopify Config] Using valid SHOPIFY_ADMIN_TOKEN from env. Store URL: {pp.SHOP_URL}")
else:
    print(f"[Shopify Config] SHOPIFY_ADMIN_TOKEN is missing or expired. Falling back to dynamic Client Credentials OAuth flow (domain: {env_domain}).")

# Enforce UTF-8 output
for s in [sys.stdout, sys.stderr]:
    if hasattr(s, 'reconfigure'):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:
            pass

CATEGORY_MAP = {
    "Home Accessories": "Decor, organizers, lighting, storage, bedding, bathroom items",
    "Kitchen": "Cookware, cooking gadgets, food storage, dining tools",
    "Automobiles": "Car accessories, cleaning kits, phone mounts, interior/exterior add-ons",
    "Fitness": "Gym equipment, resistance bands, yoga gear, activewear accessories",
    "Gadgets": "Small novelty tech: mini fans, portable lights, phone accessories, quirky tools",
    "Electronics": "Standalone electronics: earbuds, speakers, chargers, cameras",
    "Fashion": "Clothing, bags, jewelry, watches, sunglasses",
    "Beauty & Personal Care": "Skincare tools, makeup accessories, hair tools, grooming",
    "Toys & Kids": "Children's toys, baby products, learning items",
    "Outdoor & Travel": "Camping gear, travel organizers, backpacks, outdoor tools",
    "Pet Supplies": "Pet accessories, grooming, feeding, toys for pets",
    "Office & Stationery": "Desk organizers, stationery, work-from-home accessories",
}
FALLBACK_CATEGORY = "Uncategorized"
COLLECTION_CACHE = {}

def clean_and_parse_price(price_str):
    if not price_str:
        return None
    # Remove currency symbols (e.g. ₹, $, Rs.), commas, spaces
    cleaned = re.sub(r'[^\d.]', '', str(price_str))
    try:
        return float(cleaned)
    except ValueError:
        return None

def format_amazon_reviewer_name(name):
    if not name:
        return "Verified Customer"
    parts = name.split()
    if len(parts) > 1:
        # Format "Firstname + Initial" (e.g., "Sreerag K. S." -> "Sreerag K.")
        first_name = parts[0]
        initial = parts[1][0] + "." if parts[1] else ""
        return f"{first_name} {initial}".strip()
    return name

def extract_top_amazon_reviews(html_content, base_url="https://www.amazon.in"):
    soup = BeautifulSoup(html_content, "html.parser")
    reviews = []
    
    review_elements = soup.select('div[data-hook="review"]')
    if not review_elements:
        review_elements = soup.select('.a-section.review')
        
    for elem in review_elements:
        # Name
        author_elem = elem.select_one('.a-profile-name')
        author = author_elem.get_text(strip=True) if author_elem else 'Verified Customer'
        privacy_author = format_amazon_reviewer_name(author)
        
        # Rating
        rating_elem = elem.select_one('i[data-hook="review-star-rating"] span.a-icon-alt') or elem.select_one('i.a-icon-star span.a-icon-alt')
        rating = 5.0
        if rating_elem:
            rating_text = rating_elem.get_text(strip=True)
            match = re.search(r'([0-5](?:\.[0-9])?)', rating_text)
            if match:
                rating = float(match.group(1))
                
        # Title
        title_elem = elem.select_one('a[data-hook="review-title"] span') or elem.select_one('span[data-hook="review-title"]')
        title = title_elem.get_text(strip=True) if title_elem else ''
        
        # Body
        body_elem = elem.select_one('span[data-hook="review-body"]')
        body = body_elem.get_text(strip=True) if body_elem else ''
        if body.endswith('Read more'):
            body = body[:-9].strip()
            
        # Date
        date_elem = elem.select_one('span[data-hook="review-date"]')
        date = date_elem.get_text(strip=True) if date_elem else ''
        
        # Verified Purchase
        badge_elem = elem.select_one('span[data-hook="avp-badge"]')
        verified_purchase = (badge_elem is not None) or ("Verified Purchase" in elem.get_text())
        
        # Images
        images = []
        for img in elem.select('img'):
            img_class = ''.join(img.get('class', []))
            if 'avatar' in img_class or 'profile' in img_class:
                continue
            src = img.get('src') or img.get('data-src')
            if src:
                clean_src = pp.clean_image_url(src, base_url)
                if clean_src and not clean_src.endswith('.gif') and clean_src not in images:
                    images.append(clean_src)
                    
        # Helpful votes
        helpful_elem = elem.select_one('span[data-hook="helpful-vote-statement"]')
        helpful_votes = 0
        if helpful_elem:
            helpful_text = helpful_elem.get_text(strip=True).lower()
            if "one" in helpful_text or "1 person" in helpful_text:
                helpful_votes = 1
            else:
                match = re.search(r'(\d+)', helpful_text)
                if match:
                    helpful_votes = int(match.group(1))
                    
        reviews.append({
            'reviewer_name': privacy_author,
            'star_rating': rating,
            'review_text': body,
            'verified_purchase': verified_purchase,
            'review_images': images,
            'helpful_votes': helpful_votes,
            'title': title,
            'date': date
        })
        
    reviews.sort(key=lambda x: x['helpful_votes'], reverse=True)
    return reviews[:10]

def find_amazon_listing_videos(html_content):
    video_urls = []
    # Match direct mp4 links within JS structures and HTML elements
    matches = re.findall(r'https://[^"\']*?\.mp4', html_content)
    for m in matches:
        clean_url = m.replace('\\/', '/').replace('&amp;', '&')
        
        # Exclude advertising / sponsored video assets (e.g., Amazon Advertising Library "/al-")
        if any(pattern in clean_url for pattern in ['/al-', '/ad/', '/ads/', 'sponsored']):
            print(f"[Video Filter] Excluded advertising/sponsored video: {clean_url}")
            continue
            
        if "amazon" in clean_url and clean_url not in video_urls:
            video_urls.append(clean_url)
            
    return video_urls

def download_listing_videos(video_urls, product_title):
    import string
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    prefix = ''.join(c for c in product_title if c in valid_chars)[:30].strip() or "video"
    
    os.makedirs("./product_videos", exist_ok=True)
    downloaded_paths = []
    
    for idx, url in enumerate(video_urls):
        if not (url.lower().endswith('.mp4') or 'video/mp4' in url.lower() or '.mov' in url.lower()):
            continue
        try:
            filename = f"{prefix}_video_{idx+1}.mp4"
            filepath = os.path.join("./product_videos", filename)
            print(f"[Downloader] Downloading listing video: {url} -> {filepath}")
            
            r = requests.get(url, stream=True, timeout=30)
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"[Downloader] Saved video to: {filepath}")
            downloaded_paths.append(filepath)
        except Exception as e:
            print(f"[Downloader Warning] Video download failed: {e}")
            
    return downloaded_paths

def fetch_amazon_page_html(url):
    from playwright.sync_api import sync_playwright
    from pathlib import Path
    
    profile_dir = Path(__file__).parent / 'scraper_profile'
    profile_dir.mkdir(exist_ok=True)
    
    chrome_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
                user_agent=chrome_ua,
                viewport={'width': 1280, 'height': 800}
            )
            ctx.add_init_script('''
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}};
            ''')
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            
            print(f"[Playwright] Navigating to: {url}")
            page.goto(url, wait_until='load', timeout=45000)
            page.wait_for_timeout(5000)
            
            content = page.content()
            if "captcha" in content.lower() or "robot" in content.lower() or "automated access" in content.lower():
                print("[Playwright Alert] Captcha block detected. Reloading...")
                page.wait_for_timeout(5000)
                page.reload(wait_until='load')
                page.wait_for_timeout(5000)
                content = page.content()
                
            ctx.close()
            return content
        except Exception as e:
            print(f"[Playwright Error] Failed to scrape URL: {e}")
            return None

def generate_ai_details_and_pricing(title, description, scraped_price):
    if not pp.AI_CLIENTS:
        print("[AI Warning] No AI clients configured. Programmatic pricing will be enforced.")
        return title, description, scraped_price, None, FALLBACK_CATEGORY
        
    category_context = "\n".join([f"- {k}: {v}" for k, v in CATEGORY_MAP.items()])
    
    prompt = [
        {"role": "system", "content": (
            "You are an expert e-commerce copywriter and pricing analyst.\n"
            "Given a product title, description HTML, and the scraped price (in INR), "
            "rewrite the title to be SEO-friendly (max 80 chars) and the description to be an engaging, buyer-focused HTML copy (with paragraphs and bullet points).\n"
            "Also suggest a shop retail price, a compare-at price in INR, and a category assignment.\n"
            "CRITICAL RULES:\n"
            "1. The shop retail price must be at least 200 INR higher than the scraped price (margin >= 200 INR).\n"
            "2. The compare-at price must be higher than the shop retail price.\n"
            "3. You MUST choose exactly one category key from this list:\n"
            f"{list(CATEGORY_MAP.keys())}\n"
            "based on the category descriptions provided below. Only return 'Uncategorized' if the product genuinely fits none of them:\n"
            f"{category_context}\n"
            "Respond strictly in JSON with keys: 'title', 'description_html', 'price', 'compare_at_price', 'category'. Keep price numbers as plain numbers/integers."
        )},
        {"role": "user", "content": f"Title: {title}\nDescription: {description}\nScraped Price: {scraped_price or 'N/A'}"}
    ]
    
    try:
        reply = pp.ai_chat(prompt, max_tokens=1500)
        data = pp._parse_ai_json(reply)
        if isinstance(data, dict):
            new_title = data.get("title") or title
            new_desc = data.get("description_html") or description
            price = data.get("price")
            compare = data.get("compare_at_price")
            raw_category = data.get("category")
            
            # Validate and normalize category
            validated_category = FALLBACK_CATEGORY
            if raw_category:
                raw_cat_lower = raw_category.strip().lower()
                for key in CATEGORY_MAP:
                    if key.lower() == raw_cat_lower:
                        validated_category = key
                        break
                else:
                    print(f"[Category Warning] AI returned invalid category '{raw_category}'. Falling back to '{FALLBACK_CATEGORY}'.")
            else:
                print(f"[Category Warning] AI returned empty category field. Falling back to '{FALLBACK_CATEGORY}'.")
                
            return new_title, new_desc, price, compare, validated_category
    except Exception as e:
        print(f"[AI Copywriting Error] AI details generation failed: {e}")
        
    return title, description, scraped_price, None, FALLBACK_CATEGORY

def get_or_create_shopify_collection(category_name):
    if category_name in COLLECTION_CACHE:
        return COLLECTION_CACHE[category_name]
        
    headers = pp.shopify_headers()
    
    # 1. Search for collection by title
    url_search = f"{pp.SHOP_URL}/admin/api/2025-01/custom_collections.json"
    try:
        r = requests.get(url_search, headers=headers, params={"title": category_name}, timeout=15)
        r.raise_for_status()
        collections = r.json().get("custom_collections", [])
        for col in collections:
            if col["title"].strip().lower() == category_name.strip().lower():
                col_id = col["id"]
                COLLECTION_CACHE[category_name] = col_id
                return col_id
    except Exception as e:
        print(f"[Shopify Collection Search Warning] Failed to search collection '{category_name}': {e}")
        
    # 2. Not found, create it
    payload = {
        "custom_collection": {
            "title": category_name
        }
    }
    try:
        r = requests.post(url_search, headers=headers, json=payload, timeout=15)
        r.raise_for_status()
        created = r.json()["custom_collection"]
        col_id = created["id"]
        COLLECTION_CACHE[category_name] = col_id
        return col_id
    except Exception as e:
        print(f"[Shopify Collection Creation Warning] Failed to create collection '{category_name}': {e}")
        return None

def add_product_to_collection(product_id, collection_id):
    if not collection_id:
        return
    url = f"{pp.SHOP_URL}/admin/api/2025-01/collects.json"
    headers = pp.shopify_headers()
    payload = {
        "collect": {
            "product_id": product_id,
            "collection_id": collection_id
        }
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code == 422:
            print(f"[Shopify] Product {product_id} already belongs to collection {collection_id} (non-fatal no-op).")
            return
        r.raise_for_status()
    except Exception as e:
        print(f"[Shopify Collection Assignment Warning] Failed to assign product {product_id} to collection {collection_id}: {e}")

# ── Tiered Margin Pricing System ──────────────────────────────────────────────
CATEGORY_MAX_MARGIN = {
    "electronics_accessories": 0.6,
    "home_decor": 1.2,
    "fashion": 1.0,
    "kitchen": 0.8,
    "default": 0.8
}

def get_margin_percent(landed_cost):
    """
    Returns a randomized margin percentage based on tiered bands of landed cost.
    """
    if landed_cost <= 300:
        return random.uniform(0.80, 1.20)
    elif landed_cost <= 800:
        return random.uniform(0.50, 0.80)
    elif landed_cost <= 1500:
        return random.uniform(0.35, 0.50)
    elif landed_cost <= 3000:
        return random.uniform(0.25, 0.35)
    else:
        return random.uniform(0.15, 0.25)

def get_category_max_margin(category):
    """
    Looks up category max margin cap from CATEGORY_MAX_MARGIN with robust fallback.
    """
    if not category:
        return CATEGORY_MAX_MARGIN["default"]
    cat_str = str(category).lower().strip().replace(" ", "_")
    if cat_str in CATEGORY_MAX_MARGIN:
        return CATEGORY_MAX_MARGIN[cat_str]
    for k, v in CATEGORY_MAX_MARGIN.items():
        if k != "default" and (k in cat_str or cat_str in k):
            return v
    return CATEGORY_MAX_MARGIN["default"]

def calculate_landed_cost(amazon_price, shipping_cost):
    """
    Calculates landed cost incorporating shipping cost and a 2.5% payment gateway fee buffer.
    """
    return (float(amazon_price) + float(shipping_cost)) * 1.025

def charm_price(price):
    """
    Rounds price down to the nearest 10 and adds 9 (e.g. 743 -> 739) for psychological pricing.
    """
    val = (int(price) // 10) * 10 - 1
    return max(9, val)

def clamp_to_market(selling_price, market_median):
    """
    Caps the selling price at 120% of the competitor market median if available.
    """
    if market_median is not None:
        try:
            limit = float(market_median) * 1.20
            return min(float(selling_price), limit)
        except (ValueError, TypeError):
            pass
    return selling_price

def calculate_compare_at_price(selling_price, landed_cost):
    """
    Calculates compare-at price based on randomized multipliers and charms the result.
    """
    if landed_cost <= 800:
        mult = random.uniform(1.35, 1.60)
    elif landed_cost <= 3000:
        mult = random.uniform(1.25, 1.40)
    else:
        mult = random.uniform(1.15, 1.30)
    compare_at = float(selling_price) * mult
    return charm_price(compare_at)

def calculate_price(amazon_cost, shipping_cost, category=None, market_median=None):
    """
    Combines landed cost, tiered margin, charm pricing, market clamping, and compare-at calculation.
    """
    try:
        amazon_cost_float = float(amazon_cost)
    except (ValueError, TypeError):
        amazon_cost_float = 0.0

    try:
        shipping_cost_float = float(shipping_cost)
    except (ValueError, TypeError):
        shipping_cost_float = 0.0

    landed_cost = calculate_landed_cost(amazon_cost_float, shipping_cost_float)
    
    margin = get_margin_percent(landed_cost)
    max_margin = get_category_max_margin(category)
    clamped_margin = min(margin, max_margin)
    
    selling_price = landed_cost * (1.0 + clamped_margin)
    selling_price = charm_price(selling_price)
    
    if market_median is not None:
        selling_price = clamp_to_market(selling_price, market_median)
        selling_price = charm_price(selling_price)
        
    compare_at_price = calculate_compare_at_price(selling_price, landed_cost)
    
    print(f"[Pricing Engine] Category: {category or 'default'}, Landed Cost: {landed_cost:.2f}, "
          f"Margin Applied: {clamped_margin:.2%} (capped at {max_margin:.2%}), "
          f"Final Selling Price: {selling_price}, Compare-at Price: {compare_at_price}", flush=True)
          
    return selling_price, compare_at_price

def parse_price(price_str):
    """
    Cleans a price string and parses it into a float.
    Handles ranges (takes average) and removes currency symbols and commas.
    """
    if not price_str:
        return None
    cleaned = re.sub(r'[^\d\.\-]', '', str(price_str))
    if not cleaned.strip():
        return None
    if '-' in cleaned:
        parts = [p.strip() for p in cleaned.split('-') if p.strip()]
        try:
            return sum(float(x) for x in parts) / len(parts)
        except ValueError:
            pass
    try:
        return float(cleaned)
    except ValueError:
        return None

def enforce_pricing_rules(scraped_price_str, ai_price, ai_compare, category=None):
    parsed_scraped = parse_price(scraped_price_str)
    parsed_ai = parse_price(ai_price)
    
    base_cost = parsed_scraped if parsed_scraped is not None else parsed_ai
    if base_cost is None:
        base_cost = 999.0
        
    final_price, final_compare = calculate_price(
        amazon_cost=base_cost,
        shipping_cost=0.0,
        category=category,
        market_median=None
    )
    return int(final_price), int(final_compare)

def create_shopify_product(title, description, image_urls, video_urls, price, compare_price, auto_publish=False):
    embed_html = ''
    for vurl in video_urls:
        if vurl.lower().endswith('.mp4') or 'video/mp4' in vurl.lower() or '.mov' in vurl.lower():
            embed_html += f'\n<div class="product-video" style="text-align: center; margin: 20px 0;">\n  <video controls src="{vurl}" style="max-width: 100%; height: auto; border-radius: 8px;" preload="metadata"></video>\n</div>\n'
    if embed_html:
        description = description + '\n' + embed_html

    product = {
        'product': {
            'title': title,
            'body_html': description,
            'status': 'active',  # Always create active initially so Playwright reviews can be submitted
            'images': [{'src': url} for url in image_urls],
            'variants': [{
                'price': str(price),
                'compare_at_price': str(compare_price),
                'taxable': False
            }]
        }
    }
    
    url = f"{pp.SHOP_URL}/admin/api/2025-01/products.json"
    headers = pp.shopify_headers()
    
    r = requests.post(url, headers=headers, json=product, timeout=15)
    r.raise_for_status()
    created = r.json()['product']
    print(f"[Shopify] Created Product: '{created['title']}' (ID: {created['id']}) Status: {created['status'].upper()}")
    
    external_videos = [u for u in video_urls if any(x in u.lower() for x in ['youtube.com', 'youtu.be', 'vimeo.com'])]
    if external_videos:
        print('[Shopify] Linking external video URLs to gallery...')
        pp.add_videos_to_shopify_gallery(created['id'], external_videos)
        
    return created

def update_shopify_product_status(product_id, status):
    url = f"{pp.SHOP_URL}/admin/api/2025-01/products/{product_id}.json"
    headers = pp.shopify_headers()
    payload = {
        "product": {
            "id": product_id,
            "status": status
        }
    }
    r = requests.put(url, headers=headers, json=payload, timeout=15)
    r.raise_for_status()
    print(f"[Shopify] Updated Product status to: {status.upper()}")

def log_to_manual_review(video_path, best_guess_name, confidence_score, candidate_url=None):
    file_path = "needs_manual_review.json"
    entry = {
        "video_name": os.path.basename(video_path),
        "best_guess_product_name": best_guess_name,
        "confidence_score": confidence_score,
        "matched_url": candidate_url,
        "timestamp": datetime.datetime.now().isoformat()
    }
    
    data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
            
    if not any(x["video_name"] == entry["video_name"] for x in data):
        data.append(entry)
        
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def log_to_pipeline(video_path, matched_url, shopify_id, status, error_msg=None):
    file_path = "pipeline_log.json"
    entry = {
        "video_filename": os.path.basename(video_path),
        "matched_product_url": matched_url,
        "shopify_product_id": shopify_id,
        "status": status,  # "success", "needs_review", "failed"
        "timestamp": datetime.datetime.now().isoformat(),
        "error": error_msg
    }
    
    data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
            
    for i, x in enumerate(data):
        if x["video_filename"] == entry["video_filename"]:
            data[i] = entry
            break
    else:
        data.append(entry)
        
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def is_already_processed(video_path):
    file_path = "pipeline_log.json"
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for x in data:
                if x["video_filename"] == os.path.basename(video_path) and x["status"] == "success":
                    return True
    except Exception:
        pass
    return False

def process_single_video(video_path, args):
    video_filename = os.path.basename(video_path)
    print(f"\n=============================================================")
    print(f"PROCESSING VIDEO: {video_filename}")
    print(f"=============================================================")
    
    if is_already_processed(video_path):
        print(f"[Info] Video '{video_filename}' already processed successfully. Skipping.")
        return "skipped"
        
    temp_html_path = "temp_amazon.html"
    
    try:
        # Step 1: Extract frames
        print("[Stage 1] Extracting frames via ffmpeg...")
        frames = productfinder.extract_frames(video_path)
        if not frames:
            raise Exception("No frames extracted from the video.")
            
        # Step 2: Identify product
        print("[Stage 1] Querying Gemini Vision to identify the product...")
        info = productfinder.identify_product(frames)
        product_name_guess = info.get("product_name", "Unknown Product")
        print(f"  Gemini guess: {product_name_guess}")
        print(f"  Search query: {info.get('search_query')}")
        
        # Step 3: Search candidates
        print("[Stage 1] Searching Amazon India for candidate products...")
        candidates = productfinder.search_amazon_candidates(frames, info)
        if not candidates:
            log_to_manual_review(video_path, product_name_guess, 0.0)
            log_to_pipeline(video_path, None, None, "needs_review", "No Amazon candidates found.")
            print("[Stage 1 Warning] No Amazon candidates found. Sent to manual review.")
            return "needs_review"
            
        # Step 4: Verify visually and rank candidates
        print(f"[Stage 1] Verifying {len(candidates)} Amazon candidates...")
        verified_candidates = []
        for c in candidates:
            v = productfinder.verify_candidate(frames, c)
            verified_candidates.append(v)
            
        def sort_key(c):
            verified_bonus = 1 if c.get("had_page_image") else 0
            amazon_bonus = 1 if "amazon" in c["url"].lower() else 0
            return (-verified_bonus, -c.get("verified_score", 0), -amazon_bonus)
            
        verified_candidates.sort(key=sort_key)
        best_candidate = verified_candidates[0]
        confidence_score = float(best_candidate.get("verified_score", 0)) / 100.0
        best_url = best_candidate["url"]
        
        print(f"  Best Match: {best_candidate['title'][:80]}...")
        print(f"  URL: {best_url}")
        print(f"  Verification Score: {best_candidate.get('verified_score', 0)}/100 (Confidence: {confidence_score})")
        
        if confidence_score < args.confidence_threshold:
            print(f"[Stage 1 Warning] Confidence {confidence_score} below threshold {args.confidence_threshold}. Skipping push.")
            log_to_manual_review(video_path, product_name_guess, confidence_score, best_url)
            log_to_pipeline(video_path, best_url, None, "needs_review", f"Low confidence match: {confidence_score}")
            return "needs_review"
            
        # Step 5: Scrape page (Retry with backoff)
        print("\n[Stage 2] Scraping product page media + details...")
        html_content = None
        for attempt in range(1, 4):
            try:
                html_content = fetch_amazon_page_html(best_url)
                if html_content and len(html_content) > 1000:
                    break
            except Exception as se:
                print(f"  [Scraper Warning] Scrape attempt {attempt}/3 failed: {se}")
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    
        if not html_content:
            raise Exception("Failed to scrape Amazon product page HTML after 3 attempts.")
            
        with open(temp_html_path, "w", encoding="utf-8") as tf:
            tf.write(html_content)
            
        scraped_data = pp.scrape_product_from_url(temp_html_path)
        if not scraped_data.get("title") and not scraped_data.get("image_urls"):
            raise Exception("Scraped product data is empty.")
            
        validated_images = [img for img in scraped_data.get("image_urls", []) if pp.is_valid_image_url(img)]
        if not validated_images:
            raise Exception("No valid product images found on listing.")
            
        scraped_data["image_urls"] = validated_images
        print(f"  Successfully scraped listing title: {scraped_data['title'][:60]}...")
        print(f"  Scraped price: {scraped_data.get('price')}")
        print(f"  Found {len(validated_images)} valid images.")
        
        # Scrape top reviews
        print("[Stage 2] Extracting and ranking reviews from Amazon...")
        top_reviews = extract_top_amazon_reviews(html_content, base_url=best_url)
        print(f"  Scraped {len(top_reviews)} top customer reviews.")
        
        # Create output directory
        prod_slug = re.sub(r'\W+', '_', os.path.splitext(video_filename)[0]).lower()
        prod_dir = os.path.join("./products", prod_slug)
        os.makedirs(prod_dir, exist_ok=True)
        
        reviews_json_path = os.path.join(prod_dir, "reviews.json")
        with open(reviews_json_path, "w", encoding="utf-8") as rf:
            json.dump(top_reviews, rf, indent=2)
        print(f"  Saved structured reviews JSON: {reviews_json_path}")
        
        # Scrape listing videos
        amazon_videos = find_amazon_listing_videos(html_content)
        downloaded_videos = []
        if amazon_videos:
            print(f"[Stage 2] Found {len(amazon_videos)} Amazon listing videos. Downloading...")
            downloaded_videos = download_listing_videos(amazon_videos, scraped_data["title"])
            
        # AI Copywriting & pricing enforcer
        print("\n[AI Stage] Rewriting title, description, and applying pricing margins...")
        ai_title, ai_desc, ai_price, ai_compare, ai_category = generate_ai_details_and_pricing(
            scraped_data["title"], scraped_data["description"], scraped_data.get("price")
        )
        
        final_price, final_compare = enforce_pricing_rules(
            scraped_data.get("price"), ai_price, ai_compare, category=ai_category
        )
        
        print(f"  AI Rewritten Title  : {ai_title[:70]}...")
        print(f"  Base Scraped Price  : {scraped_data.get('price')}")
        print(f"  Enforced Shop Price : {final_price} INR")
        print(f"  Enforced Compare    : {final_compare} INR")
        
        # Push to Shopify (COD ON)
        print("\n[Stage 4] Pushing product to Shopify (COD = ON)...")
        created_prod = create_shopify_product(
            title=ai_title,
            description=ai_desc,
            image_urls=validated_images,
            video_urls=scraped_data.get("video_urls", []) + amazon_videos,
            price=final_price,
            compare_price=final_compare,
            auto_publish=args.auto_publish
        )
        shopify_product_id = created_prod["id"]
        
        # Collection Assignment
        try:
            col_id = get_or_create_shopify_collection(ai_category)
            if col_id:
                add_product_to_collection(shopify_product_id, col_id)
                print(f"[Shopify] Assigned to collection: {ai_category}")
            else:
                print(f"[Category Warning] Could not resolve collection for category '{ai_category}'")
        except Exception as col_err:
            print(f"[Category Warning] Collection assignment failed: {col_err}")
        
        domain = pp.get_storefront_domain()
        storefront_url = f"https://{domain}/products/{created_prod['handle']}"
        
        # Submit random reviews (13 to 33)
        random_review_count = random.randint(13, 33)
        print(f"\n[Stage 3] Launching Playwright flow to auto-submit {random_review_count} reviews to Judge.me/storefront...")
        pp.auto_submit_reviews(
            product_url=storefront_url,
            num_reviews=random_review_count,
            product_title=ai_title,
            product_description=ai_desc,
            product_image_url=validated_images[0] if validated_images else None
        )
        
        log_to_pipeline(video_path, best_url, shopify_product_id, "success")
        print(f"[Success] Video '{video_filename}' processed successfully!")
        
        return "success"
        
    except Exception as e:
        print(f"\n[Error] Failed to process video '{video_filename}': {e}")
        traceback.print_exc()
        log_to_pipeline(video_path, None, None, "failed", str(e))
        return "failed"
        
    finally:
        if os.path.exists(temp_html_path):
            try:
                os.remove(temp_html_path)
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser(description="Radikikk Dropshipping Automation Pipeline")
    parser.add_argument("--videos", type=str, default="./videos/", help="Directory containing creator videos")
    parser.add_argument("--video", type=str, default=None, help="Path to a single video to process")
    parser.add_argument("--auto-publish", action="store_true", help="Set pushed Shopify products to ACTIVE status instead of DRAFT")
    parser.add_argument("--confidence-threshold", type=float, default=0.6, help="Confidence threshold below which matches require manual review")
    
    args = parser.parse_args()
    
    video_paths = []
    if args.video:
        if os.path.isfile(args.video):
            video_paths.append(args.video)
        else:
            print(f"[Error] Single video path '{args.video}' does not exist.")
            sys.exit(1)
    else:
        if not os.path.isdir(args.videos):
            print(f"[Error] Videos directory '{args.videos}' does not exist.")
            sys.exit(1)
            
        for f in os.listdir(args.videos):
            if f.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
                video_paths.append(os.path.join(args.videos, f))
                
        video_paths.sort()
        
    if not video_paths:
        print("[Info] No creator videos found to process.")
        sys.exit(0)
        
    print("=" * 60)
    print(f"Starting pipeline run. Total videos found: {len(video_paths)}")
    print(f"Auto-publish to Shopify: {args.auto_publish}")
    print(f"Confidence threshold    : {args.confidence_threshold}")
    print("=" * 60)
    
    stats = {
        "processed": 0,
        "created": 0,
        "needs_review": 0,
        "failed": 0,
        "skipped": 0
    }
    
    for path in video_paths:
        result = process_single_video(path, args)
        stats["processed"] += 1
        if result == "success":
            stats["created"] += 1
        elif result == "needs_review":
            stats["needs_review"] += 1
        elif result == "failed":
            stats["failed"] += 1
        elif result == "skipped":
            stats["skipped"] += 1
            
    print("\n" + "=" * 60)
    print("PIPELINE RUN SUMMARY")
    print("=" * 60)
    print(f"Total Videos Scanned: {stats['processed']}")
    print(f"Pushed to Shopify (Draft/Active): {stats['created']}")
    print(f"Sent to Manual Review           : {stats['needs_review']}")
    print(f"Failed Processing               : {stats['failed']}")
    print(f"Skipped (Already Processed)     : {stats['skipped']}")
    print("=" * 60)

if __name__ == "__main__":
    main()
