# Decompiled with PyLingual (https://pylingual.io)
# Internal filename: 'productpush.py'
# Bytecode version: 3.11a7e (3495)
# Source timestamp: 2026-07-01 17:31:08 UTC (1782927068)

# irreducible cflow, using cdg fallback
global _shop_domain
global _token_expires_at
global _token
global _PROBED_VISION_CLIENTS
import requests
import json
import time
import sys
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
from bs4 import BeautifulSoup
import re
import os
import base64
from urllib.parse import urljoin, urlparse
from dotenv import load_dotenv
try:
    from openai import OpenAI
except Exception:
    OpenAI = None
load_dotenv()
_KEY_CONFIGS = [('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/openai/', 'gemini-2.5-flash'), ('GEMINI_API_KEY_2', 'https://generativelanguage.googleapis.com/v1beta/openai/', 'gemini-2.5-flash'), ('GEMINI_API_KEY_3', 'https://generativelanguage.googleapis.com/v1beta/openai/', 'gemini-2.5-flash'), ('gemini_pro_key', 'https://generativelanguage.googleapis.com/v1beta/openai/', 'gemini-2.5-pro'), ('GROQ_API_KEY', 'https://api.groq.com/openai/v1', 'meta-llama/llama-4-scout-17b-16e-instruct'), ('GROQ_API_KEY_ALT', 'https://api.groq.com/openai/v1', 'meta-llama/llama-4-scout-17b-16e-instruct'), ('GROQ_API_KEY_ALT2', 'https://api.groq.com/openai/v1', 'meta-llama/llama-4-scout-17b-16e-instruct'), ('XAI_API_KEY', 'https://api.x.ai/v1', 'grok-2'), ('XAI_API_KEY_ALT', 'https://api.x.ai/v1', 'grok-2'), ('XAI_API_KEY_NEW', 'https://api.x.ai/v1', 'grok-2')]
SKIP_IMAGE_KEYWORDS = ('logo', 'icon', 'spinner', 'pixel', 'avatar', 'sprite', 'chevron', 'arrow', 'badge', 'cart', 'banner', 'placeholder', 'loading', 'star', 'rating', 'review', 'profile', 'payment', 'trust', 'secure', 'swm_', 'uedata', 'batch/1/op')
def _build_clients() -> list[tuple[OpenAI, str, str]]:
    clients = []
    if OpenAI is None:
        return clients
    else:
        for env_var, base_url, model in _KEY_CONFIGS:
            key = os.getenv(env_var)
            if key and key.strip():
                try:
                    clients.append((OpenAI(api_key=key.strip(), base_url=base_url), model, f'{env_var}'))
                except Exception:
                    pass
        return clients
def build_vision_clients() -> list[tuple[OpenAI, str, str]]:
    clients = []
    if OpenAI is None:
        return clients
    else:
        for key_var in ['GEMINI_API_KEY', 'GEMINI_API_KEY_2', 'GEMINI_API_KEY_3', 'gemini_pro_key']:
            key = os.getenv(key_var)
            if key and key.strip():
                try:
                    gemini_client = OpenAI(api_key=key.strip(), base_url='https://generativelanguage.googleapis.com/v1beta/openai/')
                    clients.append((gemini_client, 'gemini-2.5-flash', f'Gemini ({key_var} - 2.5-flash)'))
                    clients.append((gemini_client, 'gemini-2.0-flash', f'Gemini ({key_var} - 2.0-flash)'))
                    clients.append((gemini_client, 'gemini-flash-latest', f'Gemini ({key_var} - flash-latest)'))
                except Exception:
                    pass
        for key_var in ['GROQ_API_KEY', 'GROQ_API_KEY_ALT', 'GROQ_API_KEY_ALT2']:
            key = os.getenv(key_var)
            if key and key.strip():
                try:
                    groq_client = OpenAI(api_key=key.strip(), base_url='https://api.groq.com/openai/v1')
                    clients.append((groq_client, 'llama-3.2-11b-vision-preview', f'Groq ({key_var} - 11b-vision)'))
                except Exception:
                    pass
        for key_var in ['XAI_API_KEY_NEW', 'XAI_API_KEY_ALT', 'XAI_API_KEY']:
            key = os.getenv(key_var)
            if key and key.strip():
                try:
                    xai_client = OpenAI(api_key=key.strip(), base_url='https://api.x.ai/v1')
                    clients.append((xai_client, 'grok-2-vision', f'xAI ({key_var})'))
                except Exception:
                    pass
        return clients
_PROBED_VISION_CLIENTS = None
def get_working_vision_clients() -> list:
    global _PROBED_VISION_CLIENTS
    if _PROBED_VISION_CLIENTS is not None:
        return _PROBED_VISION_CLIENTS
    else:
        raw_clients = build_vision_clients()
        if not raw_clients:
            print('[AI] No vision clients configured.')
            _PROBED_VISION_CLIENTS = []
            return []
        else:
            print(f'[AI] Probing {len(raw_clients)} vision client(s) — one-time key check...')
            working = []
            tested_client_ids = set()
            for client, model, label in raw_clients:
                cid = id(client)
                if cid in tested_client_ids:
                    working.append((client, model, label))
                    continue
                else:
                    try:
                        kwargs = {'model': model, 'messages': [{'role': 'user', 'content': 'Reply with just: OK'}], 'timeout': 10}
                        if 'Gemini' not in label:
                            kwargs['max_tokens'] = 5
                        resp = client.chat.completions.create(**kwargs)
                        result = resp.choices[0].message.content
                        if result:
                            working.append((client, model, label))
                            tested_client_ids.add(cid)
                            print(f'  [OK] {label} (model: {model})')
                        else:
                            print(f'  [EMPTY] {label} (model: {model})')
                    except Exception as e:
                        err = str(e)
                        if '429' in err:
                            print(f'  [WARN] {label} (model: {model}) — rate-limited (included as fallback)')
                            working.append((client, model, label))
                            tested_client_ids.add(cid)
                        else:
                            print(f'  [FAIL] {label} (model: {model}) — failed check: {err[:120]}')
            _PROBED_VISION_CLIENTS = working
            return working
AI_CLIENTS = _build_clients()
if OpenAI is None:
    print('[AI] openai package not installed — AI features disabled. Run: pip install openai')
else:
    print(f'[AI] Text clients: {len(AI_CLIENTS)}')
    if len(AI_CLIENTS) == 0:
        print('[AI] No API keys found in environment. Set GROQ_API_KEY or XAI_API_KEY to enable AI.')
def ai_chat(messages: list[dict], max_tokens: int=1024) -> str:
    """\n    Try configured AI clients in order and return the first successful reply.\n    Messages must be in Chat format: {\"role\": \"user\"/\"system\"/\"assistant\", \"content\": \"...\"}\n    """
    last_err = None
    for client, model, label in AI_CLIENTS:
        try:
            resp = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            last_err = e
    raise RuntimeError(f'AI request failed: {last_err}')
def _parse_ai_json(reply: str) -> dict | None:
    try:
        return json.loads(reply)
    except Exception:
        try:
            m = re.search(r'\{[\s\S]*\}', reply)
            if m:
                return json.loads(m.group(0))
        except Exception:
            return None
    return None
def is_valid_image_url(url: str) -> bool:
    """Heuristic filter — reject tracking pixels, page links, banners."""
    if not url or url.startswith('data:'):
        return False
    else:
        low = url.lower()
        if '.svg' in low or '.gif' in low:
            return False
        else:
            if any((kw in low for kw in SKIP_IMAGE_KEYWORDS)):
                return False
            else:
                if 'amazon.' in low and '/dp/' in low and (not low.endswith(('.jpg', '.jpeg', '.png', '.webp'))):
                            return False
                if 'fls-eu.amazon' in low or 'uedata=' in low:
                    return False
                else:
                    if re.search('_cb\\d+_', low) and '/images/i/' not in low:
                            return False
                    if 'media-amazon.com/images/i/' in low or 'images-amazon.com/images/i/' in low:
                        return True
                    else:
                        if any((low.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.avif'])):
                            return True
                        else:
                            if any((x in low for x in ['cdn.shopify.com', 'rukminim', 'flixcart', 'cloudinary', 'imgix'])):
                                return True
                            else:
                                return False
def _download_image_b64(url: str, max_bytes: int=1500000) -> tuple[str, str] | None:
    try:
        resp = requests.get(url, headers=SCRAPER_HEADERS, timeout=12, stream=True)
        resp.raise_for_status()
        ctype = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0]
        data = b''
        for chunk in resp.iter_content(8192):
            data += chunk
            if len(data) > max_bytes:
                return None
        if len(data) < 500:
            return None
        return (ctype, base64.b64encode(data).decode('ascii'))
    except Exception:
        return None
def _vision_chat(messages: list[dict], max_tokens: int=300) -> str:
    working_clients = get_working_vision_clients()
    last_err = None
    for client, model, label in working_clients:
        try:
            resp = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
            content = resp.choices[0].message.content
            if content is not None:
                return content.strip()
            else:
                raise ValueError('Response content was None')
        except Exception as e:
            print(f'  [AI Vision] Client \'{label}\' (model: {model}) failed: {e}')
            last_err = e
    raise RuntimeError(f'Vision request failed: {last_err}')
def verify_images_with_ai(title: str, image_urls: list[str]) -> list[str]:
    """\n    Validate product images before Shopify upload.\n    1) Heuristic URL filter\n    2) Vision AI check bypassed (returns all candidates)\n    """
    candidates = [u for u in image_urls if is_valid_image_url(u)]
    print(f'[Images] AI validation disabled — keeping all {len(candidates)} candidate image(s) from heuristic filter.')
    return candidates
def analyze_scraped_product_with_ai(data: dict) -> str:
    """Return a short AI analysis of scraped product data."""
    if not AI_CLIENTS:
        return 'AI analysis unavailable (no API keys).'
    else:
        plain_desc = BeautifulSoup(data.get('description', ''), 'html.parser').get_text(' ', strip=True)[:2000]
        prompt = [{'role': 'system', 'content': 'You are an ecommerce analyst. Summarize scraped product data and note gaps or quality issues.'}, {'role': 'user', 'content': f"Title: {data.get('title')}\nPrice: {data.get('price')}\nCompare price: {data.get('compare_at_price')}\nImages: {len(data.get('image_urls', []))}\nVideos: {len(data.get('video_urls', []))}\nReviews: {len(data.get('reviews', []))}\nDescription excerpt: {plain_desc}\n\nGive 4-6 bullet points: product category, key features, pricing notes, image/description quality, and Shopify listing recommendations."}]
        try:
            return ai_chat(prompt, max_tokens=500)
        except Exception as e:
            return f'AI analysis failed: {e}'
def generate_title_description_and_pricing(title: str, description: str, scraped_price: str | None=None) -> tuple[str, str, str | None, str | None]:
    if not AI_CLIENTS:
        return (title, description, scraped_price, None)
    try:
        sys_msg = {'role': 'system', 'content': 'You are an expert ecommerce copywriter. Given an existing product title, HTML description, and an optional scraped price, produce:\n1) A concise SEO-friendly product title (max 80 chars).\n2) A buyer-focused product description in HTML, referencing and improving the existing description, with bullet points and key features.\n3) A suggested retail price (USD) and an optional compare-at price. If the scraped price is exactly 399, prefer suggesting a shop price of 699 and compare_at_price like 949 unless you think another price is better.\n'}
        user_msg = {'role': 'user', 'content': f"Title: {title}\nExisting description HTML:{description}\nScraped price: {scraped_price or 'N/A'}\n\nRespond as JSON with keys: title, description_html, price, compare_at_price. Keep numbers as plain numerals without $ sign."}
        reply = ai_chat([sys_msg, user_msg], max_tokens=1200)
        j = _parse_ai_json(reply)
        if isinstance(j, dict):
            new_title = j.get('title', title)
            new_desc = j.get('description_html', description)
            price = str(j.get('price')) if j.get('price') else scraped_price
            compare = str(j.get('compare_at_price')) if j.get('compare_at_price') else None
            return (new_title, new_desc, price, compare)
    except Exception:
        pass
    return (title, description, scraped_price, None)
SHOP_NAME = '2txc0h-0a'
CLIENT_ID = 'b05f53b40ec22a8396eb1ab7a2849ee1'
CLIENT_SECRET = __import__('os').environ.get("SHOPIFY_APP_SECRET", "")
SHOP_URL = f'https://{SHOP_NAME}.myshopify.com'
_token: str | None = None
_token_expires_at: float = 0
def get_access_token() -> str:
    """\n    Request a fresh Admin API access token using the Client Credentials Grant.\n    Caches the token and auto-refreshes it 60 seconds before it expires (24h).\n    """
    global _token_expires_at
    global _token
    if _token and time.time() < _token_expires_at - 60:
        return _token
    else:
        last_err = None
        for attempt in range(1, 4):
            try:
                resp = requests.post(f'{SHOP_URL}/admin/oauth/access_token', headers={'Content-Type': 'application/x-www-form-urlencoded'}, data={'grant_type': 'client_credentials', 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}, timeout=12)
                resp.raise_for_status()
                body = resp.json()
                _token = body['access_token']
                _token_expires_at = time.time() + body.get('expires_in', 86399)
                print('[Auth] Access token obtained (expires in 24 h)')
                return _token
            except Exception as e:
                last_err = e
                print(f'[Auth Warning] Attempt {attempt}/3 failed to obtain access token: {e}')
                if attempt < 3:
                    time.sleep(2 * attempt)
        raise last_err
def shopify_headers() -> dict:
    """Return headers with a fresh access token for every Shopify API call."""
    return {'X-Shopify-Access-Token': get_access_token(), 'Content-Type': 'application/json'}
_shop_domain: str | None = None
def get_storefront_domain() -> str:
    global _shop_domain
    if _shop_domain:
        return _shop_domain
    try:
        r = requests.get(f'{SHOP_URL}/admin/api/2025-01/shop.json', headers=shopify_headers(), timeout=10)
        if r.status_code == 200:
            shop = r.json().get('shop', {})
            domain = shop.get('domain')
            if domain:
                _shop_domain = domain
                print(f'[Shopify] Storefront domain resolved to: {domain}')
                return domain
    except Exception as e:
        print(f'[Shopify] Warning: Failed to fetch shop domain: {e}')
    fallback = f'{SHOP_NAME}.myshopify.com'
    _shop_domain = fallback
    return fallback
def get_latest_products_graphql(limit: int=10) -> list[dict]:
    graphql_url = f'{SHOP_URL}/admin/api/2025-01/graphql.json'
    query = '\n    query getLatestProducts($limit: Int!) {\n      products(first: $limit, sortKey: CREATED_AT, reverse: true) {\n        edges {\n          node {\n            id\n            title\n            handle\n            bodyHtml\n            images(first: 1) {\n              edges {\n                node {\n                  url\n                }\n              }\n            }\n            variants(first: 20) {\n              edges {\n                node {\n                  price\n                }\n              }\n            }\n          }\n        }\n      }\n    }\n    '
    try:
        resp = requests.post(graphql_url, headers=shopify_headers(), json={'query': query, 'variables': {'limit': limit}}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            edges = data.get('data', {}).get('products', {}).get('edges', [])
            products = []
            for edge in edges:
                node = edge.get('node', {})
                raw_id = node.get('id', '')
                num_id = raw_id.split('/')[(-1)] if raw_id else ''
                body_html = node.get('bodyHtml') or ''
                img_url = None
                img_edges = node.get('images', {}).get('edges', [])
                if img_edges:
                    img_url = img_edges[0].get('node', {}).get('url')
                price_val = None
                var_edges = node.get('variants', {}).get('edges', [])
                if var_edges:
                    prices = []
                    for v_edge in var_edges:
                        raw_price = v_edge.get('node', {}).get('price')
                        if raw_price:
                            try:
                                prices.append(float(raw_price))
                            except Exception:
                                pass
                    if prices:
                        price_val = str(int(max(prices)))
                products.append({'id': num_id, 'title': node.get('title', ''), 'handle': node.get('handle', ''), 'body_html': body_html, 'image_url': img_url, 'price': price_val or '0'})
            return products
    except Exception as e:
        print(f'[GraphQL] Error fetching latest products: {e}')
    return []
def get_latest_products(limit: int=10) -> list[dict]:
    """Get the latest products using GraphQL first, falling back to REST API."""
    products = get_latest_products_graphql(limit)
    if products:
        return products
    else:
        print('[Shopify] GraphQL failed. Falling back to REST API...')
        try:
            r = requests.get(f'{SHOP_URL}/admin/api/2025-01/products.json', headers=shopify_headers(), params={'limit': limit}, timeout=10)
            r.raise_for_status()
            raw_products = r.json().get('products', [])
            products = []
            for p in raw_products:
                img_url = None
                if p.get('images'):
                    img_url = p['images'][0].get('src')
                price_val = None
                variants = p.get('variants', [])
                if variants:
                    prices = []
                    for v in variants:
                        try:
                            v_price = float(v.get('price', 0))
                            if v_price:
                                prices.append(v_price)
                        except Exception:
                            continue
                    if prices:
                        price_val = str(int(max(prices)))
                products.append({'id': str(p.get('id')), 'title': p.get('title', ''), 'handle': p.get('handle', ''), 'body_html': p.get('body_html') or '', 'image_url': img_url, 'price': price_val or '0'})
            return products
        except Exception as e:
            print(f'[Error] Failed to fetch products via REST API: {e}')
            return []
SCRAPER_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36', 'Accept-Language': 'en-US,en;q=0.9'}
def clean_image_url(img_url: str, base_url: str) -> str:
    """Resolve relative URLs, strip Shopify/Amazon resizing parameters."""
    img_url = (img_url or '').strip()
    if not img_url:
        return ''
    else:
        if img_url.startswith('//'):
            img_url = 'https:' + img_url
        else:
            if not img_url.startswith('http'):
                img_url = urljoin(base_url, img_url)
        if 'media-amazon.com' in img_url or 'images-amazon.com' in img_url:
            img_url = re.sub('\\._[A-Z0-9,_-]+(?=\\.[a-zA-Z]{3,5}$)', '', img_url)
            img_url = re.sub('\\._[A-Z]{2}_[^./]+(?=\\.[a-zA-Z0-9]+$)', '', img_url)
        if 'flipkart' in img_url or 'flixcart' in img_url:
            img_url = re.sub('/(\\d+)/(\\d+)/', '/832/832/', img_url)
        img_url = re.sub('_(?:[0-9]+x[0-9]*|[0-9]*x[0-9]+|thumb|micro|tiny|small|medium|large|grande|compact|master|1024x1024|2048x2048)(?=\\.[a-zA-Z0-9]+$)', '', img_url)
        return img_url.split('?')[0]
def _is_product_type(item: dict) -> bool:
    ptype = item.get('@type', '')
    if isinstance(ptype, list):
        return 'Product' in ptype
    else:
        return ptype == 'Product'
def _iter_json_ld_items(soup: BeautifulSoup):
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '')
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and '@graph' in data:
                items = list(items) + list(data['@graph'])
        for item in items:
            if isinstance(item, dict):
                yield item
def _add_product_image(urls: list[str], seen: set[str], raw: str, base: str) -> None:
    clean = clean_image_url(raw, base)
    if clean and is_valid_image_url(clean) and (clean not in seen):
                seen.add(clean)
                urls.append(clean)
def _clean_product_title(title: str) -> str:
    title = re.sub('\\s*:\\s*Amazon\\.[a-z.]+.*$', '', title or '', flags=re.I)
    title = re.sub('\\s*\\|\\s*Amazon\\.[a-z.]+.*$', '', title, flags=re.I)
    return title.strip()
def _extract_price_from_text(text: str) -> str | None:
    if not text:
        return None
    else:
        text = text.replace(',', '').strip()
        m = re.search('(?:₹|Rs\\.?|\\$|USD)\\s*([\\d]+(?:\\.\\d{1,2})?)', text, re.I)
        if m:
            return m.group(1)
        else:
            m = re.search('([\\d]{1,6}(?:\\.\\d{1,2})?)', text)
            if m and float(m.group(1)) > 0:
                return m.group(1)
            else:
                return None
def extract_amazon_product(soup: BeautifulSoup, base_url: str) -> dict:
    title = ''
    description = ''
    images = []
    seen = set()
    price = None
    compare_at = None
    t = soup.select_one('#productTitle') or soup.find('span', id='productTitle')
    if t:
        title = _clean_product_title(t.get_text(strip=True))
    if not title:
        og = soup.find('meta', property='og:title')
        if og:
            title = _clean_product_title(og.get('content', ''))
    for sel in ['#feature-bullets ul', '#productDescription', '#aplus_feature_div', '#productFactsDesktopExpander']:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 30:
                description = str(el)
                break
    if not description:
        ogd = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        if ogd:
            description = f"<p>{ogd.get('content', '')}</p>"
    for img in soup.select('#imgTagWrapperId img, #landingImage, #altImages img, #imageBlock img, .imageThumbnail img'):
        for attr in ['data-old-hires', 'data-a-hires', 'data-src', 'src']:
            val = img.get(attr, '')
            if val:
                _add_product_image(images, seen, val, base_url)
        dynamic = img.get('data-a-dynamic-image')
        if dynamic:
            try:
                for key in json.loads(dynamic):
                    _add_product_image(images, seen, key, base_url)
            except Exception:
                pass
    for item in _iter_json_ld_items(soup):
        if not _is_product_type(item):
            continue
        else:
            if not title and item.get('name'):
                    title = _clean_product_title(item['name'])
            if (not description or len(BeautifulSoup(description, 'html.parser').get_text(strip=True)) < 40) and item.get('description'):
                    description = f"<p>{item['description']}</p>"
            ld_images = item.get('image')
            if ld_images:
                if isinstance(ld_images, str):
                    ld_images = [ld_images]
                else:
                    if isinstance(ld_images, dict):
                        ld_images = [ld_images.get('url', '')]
                    else:
                        ld_images = [x.get('url') if isinstance(x, dict) else x for x in ld_images]
                for src in ld_images:
                    if isinstance(src, str):
                        _add_product_image(images, seen, src, base_url)
            offers = item.get('offers')
            offer_list = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
            for offer in offer_list:
                if not isinstance(offer, dict):
                    continue
                else:
                    if not price and offer.get('price'):
                            price = str(offer.get('price'))
                    if not compare_at and offer.get('highPrice'):
                            compare_at = str(offer.get('highPrice'))
    for sel in ['#corePrice_feature_div .a-price .a-offscreen', '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen', '.priceToPay .a-offscreen', '#tp_price_block_total_price_ww .a-offscreen', 'span.a-price-whole']:
        el = soup.select_one(sel)
        if el:
            price = _extract_price_from_text(el.get_text(strip=True)) or price
            if price:
                break
    strike = soup.select_one('.basisPrice .a-offscreen, .a-text-price .a-offscreen')
    if strike:
        compare_at = _extract_price_from_text(strike.get_text(strip=True)) or compare_at
    return {'title': title, 'description': description, 'image_urls': images, 'price': price, 'compare_at_price': compare_at}
def extract_flipkart_product(soup: BeautifulSoup, base_url: str) -> dict:
    title = ''
    description = ''
    images = []
    seen = set()
    price = None
    h1 = soup.select_one('span.B_NuCI, h1.yhB1nd, h1[class*=\'title\']') or soup.find('h1')
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content', '')
    for sel in ['div._1mXcCf.RmoJUa', 'div._2418kt', 'div[class*=\'description\']']:
        el = soup.select_one(sel)
        if el:
            description = str(el)
            break
    if not description:
        desc_header = None
        for tag in soup.find_all(['h2', 'h3', 'h4', 'span', 'p', 'div']):
            text = tag.get_text(strip=True).lower()
            if 'product details' in text or 'description' in text:
                desc_header = tag
                break
        if desc_header:
            parent = desc_header.parent
            desc_text = parent.get_text('\n', strip=True)
            if len(desc_text) > 50:
                description = '\n'.join((f'<p>{line}</p>' for line in desc_text.splitlines() if line.strip()))
    if not description:
        og_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        if og_desc:
            description = f"<p>{og_desc.get('content', '')}</p>"
    for selector in ['div._37M-3 img', 'div.CXW8mj img', 'div.q6DClP img', 'img[src*=\'rukminim\']', 'img[src*=\'flixcart\']', 'img']:
        for img in soup.select(selector):
            for attr in ['src', 'data-src', 'data-srcset', 'srcset']:
                val = img.get(attr, '')
                if val:
                    urls_to_check = [val]
                    if ',' in val and (not val.startswith('data:')):
                            urls_to_check = [u.strip().split()[0] for u in val.split(',') if u.strip()]
                    for u in urls_to_check:
                        clean_u = clean_image_url(u, base_url)
                        if clean_u and is_valid_image_url(clean_u) and (clean_u not in seen):
                                    seen.add(clean_u)
                                    images.append(clean_u)
    for item in _iter_json_ld_items(soup):
        if not _is_product_type(item):
            continue
        else:
            if not title and item.get('name'):
                    title = item['name']
            offers = item.get('offers')
            if isinstance(offers, dict) and offers.get('price') and (not price):
                        price = str(offers.get('price'))
    price_el = soup.select_one('div._30jeq3, div[class*=\'price\'], .Nx9bqj')
    if price_el and (not price):
            price = _extract_price_from_text(price_el.get_text(strip=True))
    if not price:
        for tag in soup.find_all(['h2', 'h3', 'h4', 'span', 'p', 'div']):
            text = tag.get_text(strip=True)
            if text.startswith('₹') or '₹' in text:
                match = re.search('₹\\s*([\\d,]+)', text)
                if match:
                    price = match.group(1).replace(',', '')
                    break
    return {'title': title, 'description': description, 'image_urls': images, 'price': price, 'compare_at_price': None}
def extract_meesho_product(soup: BeautifulSoup, base_url: str) -> dict:
    title = ''
    description = ''
    images = []
    seen = set()
    price = None
    h1 = soup.find('h1')
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content', '')
    if not title:
        title_el = soup.select_one('[class*=\'ProductTitle\'], [class*=\'title\'], [class*=\'Name\']')
        if title_el:
            title = title_el.get_text(strip=True)
    for tag in soup.find_all(['h2', 'h3', 'h4', 'span', 'p', 'div']):
        text = tag.get_text(strip=True)
        if text.startswith('₹') or '₹' in text:
            match = re.search('₹\\s*([\\d,]+)', text)
            if match:
                price = match.group(1).replace(',', '')
                break
    if not price:
        price_meta = soup.find('meta', property='product:price:amount')
        if price_meta:
            price = price_meta.get('content')
    desc_header = None
    for tag in soup.find_all(['h2', 'h3', 'h4', 'span', 'p', 'div']):
        text = tag.get_text(strip=True).lower()
        if 'product details' in text or 'description' in text:
            desc_header = tag
            break
    if desc_header:
        parent = desc_header.parent
        desc_text = parent.get_text('\n', strip=True)
        if len(desc_text) > 50:
            description = '\n'.join((f'<p>{line}</p>' for line in desc_text.splitlines() if line.strip()))
    if not description:
        og_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        if og_desc:
            description = f"<p>{og_desc.get('content', '')}</p>"
    for img in soup.find_all('img'):
        for attr in ['src', 'data-src', 'data-srcset', 'srcset']:
            val = img.get(attr, '')
            if val:
                urls_to_check = [val]
                if ',' in val and (not val.startswith('data:')):
                        urls_to_check = [u.strip().split()[0] for u in val.split(',') if u.strip()]
                for u in urls_to_check:
                    clean_u = clean_image_url(u, base_url)
                    if clean_u and ('meesho.com' in clean_u or 'meesho' in clean_u) and (clean_u not in seen) and is_valid_image_url(clean_u):
                                    seen.add(clean_u)
                                    images.append(clean_u)
    if not images:
        for img in soup.find_all('img'):
            for attr in ['src', 'data-src']:
                val = img.get(attr, '')
                if val:
                    clean_u = clean_image_url(val, base_url)
                    if clean_u and is_valid_image_url(clean_u) and (clean_u not in seen):
                                seen.add(clean_u)
                                images.append(clean_u)
    return {'title': title.strip() if title else 'Meesho Product', 'description': description.strip(), 'image_urls': images, 'price': price, 'compare_at_price': None}
def _looks_like_shopify_url(url: str) -> bool:
    low = url.lower()
    return not any((x in low for x in ['amazon.', 'amzn.', 'flipkart.com', 'ebay.', 'aliexpress.', 'meesho.com', 'meesho.']))
def get_embed_url(url: str) -> str:
    """Helper to convert standard YouTube/Vimeo links into correct embed links."""
    if 'youtube.com/watch' in url:
        match = re.search('v=([a-zA-Z0-9_-]+)', url)
        if match:
            return f'https://www.youtube.com/embed/{match.group(1)}'
    else:
        if 'youtu.be/' in url:
            match = re.search('youtu\\.be/([a-zA-Z0-9_-]+)', url)
            if match:
                return f'https://www.youtube.com/embed/{match.group(1)}'
        else:
            if 'vimeo.com/' in url and 'player.vimeo' not in url:
                match = re.search('vimeo\\.com/([0-9]+)', url)
                if match:
                    return f'https://player.vimeo.com/video/{match.group(1)}'
    return url
def get_or_create_collection_id(input_str: str) -> int | None:
    input_str = input_str.strip()
    if not input_str:
        return None
    if input_str.isdigit():
        return int(input_str)
        
    headers = shopify_headers()
    try:
        r = requests.get(f'{SHOP_URL}/admin/api/2025-01/custom_collections.json', headers=headers, params={'title': input_str}, timeout=10)
        if r.status_code == 200:
            collections = r.json().get('custom_collections', [])
            if collections:
                col_id = collections[0]['id']
                print(f'[Shopify] Found existing custom collection \'{input_str}\' (ID: {col_id})')
                return col_id
    except Exception as e:
        print(f'[Shopify] Warning: Failed searching custom collections: {e}')

    try:
        r = requests.get(f'{SHOP_URL}/admin/api/2025-01/custom_collections.json', headers=headers, timeout=10)
        if r.status_code == 200:
            collections = r.json().get('custom_collections', [])
            for col in collections:
                if col.get('title', '').strip().lower() == input_str.lower():
                    col_id = col['id']
                    print(f"[Shopify] Found existing custom collection \'{col['title']}\' (ID: {col_id})")
                    return col_id
    except Exception as e:
        print(f'[Shopify] Warning: Failed searching custom collections list: {e}')

    try:
        r = requests.get(f'{SHOP_URL}/admin/api/2025-01/smart_collections.json', headers=headers, params={'title': input_str}, timeout=10)
        if r.status_code == 200:
            smart_cols = r.json().get('smart_collections', [])
            if smart_cols:
                col_id = smart_cols[0]['id']
                print(f'[Shopify] Found existing smart collection \'{input_str}\' (ID: {col_id})')
                return col_id
    except Exception as e:
        print(f'[Shopify] Warning: Failed searching smart collections: {e}')

    print(f'[Shopify] Collection \'{input_str}\' not found. Creating new custom collection...')
    try:
        create_payload = {'custom_collection': {'title': input_str, 'published': True}}
        r = requests.post(f'{SHOP_URL}/admin/api/2025-01/custom_collections.json', headers=headers, json=create_payload, timeout=10)
        if r.status_code == 201:
            new_col = r.json().get('custom_collection', {})
            col_id = new_col.get('id')
            print(f'[Shopify] Created new custom collection \'{input_str}\' (ID: {col_id})')
            return col_id
        else:
            print(f'[Shopify] Failed to create custom collection. Status: {r.status_code}, Body: {r.text}')
    except Exception as e:
        print(f'[Shopify] Error creating collection \'{input_str}\': {e}')
    return None
def ensure_no_cod_smart_collection() -> int | None:
    """Ensure that the smart collection \'No COD\' exists. If not, create it."""
    headers = shopify_headers()
    try:
        r = requests.get(f'{SHOP_URL}/admin/api/2025-01/smart_collections.json', headers=headers, params={'title': 'No COD'}, timeout=10)
        if r.status_code == 200:
            smart_cols = r.json().get('smart_collections', [])
            for c in smart_cols:
                if c.get('title', '').strip().lower() == 'no cod':
                    return c['id']
        create_payload = {'smart_collection': {'title': 'No COD', 'rules': [{'column': 'tag', 'relation': 'equals', 'condition': 'no-cod'}], 'published': True}}
        r = requests.post(f'{SHOP_URL}/admin/api/2025-01/smart_collections.json', headers=headers, json=create_payload, timeout=10)
        if r.status_code == 201:
            col = r.json().get('smart_collection', {})
            col_id = col.get('id')
            print(f'[Shopify] Created smart collection \'No COD\' (ID: {col_id}) for automated tagging exclusion.')
            return col_id
        else:
            print(f'[Shopify Error] Failed to create \'No COD\' smart collection. Status: {r.status_code}, Body: {r.text}')
    except Exception as e:
        print(f'[Shopify Error] Exception while ensuring \'No COD\' smart collection: {e}')
    return None
def scrape_amazon_reviews(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Scrape customer reviews and images from an Amazon product HTML page."""
    reviews = []
    review_elements = soup.select('div[data-hook=\"review\"]')
    if not review_elements:
        review_elements = soup.select('.a-section.review')
    for elem in review_elements:
        author_elem = elem.select_one('.a-profile-name')
        author = author_elem.get_text(strip=True) if author_elem else 'Verified Customer'
        rating_elem = elem.select_one('i[data-hook=\"review-star-rating\"] span.a-icon-alt') or elem.select_one('i.a-icon-star span.a-icon-alt')
        rating = '5'
        if rating_elem:
            rating_text = rating_elem.get_text(strip=True)
            match = re.search('([0-5](?:\\.[0-9])?)', rating_text)
            if match:
                rating = match.group(1)
        title_elem = elem.select_one('a[data-hook=\"review-title\"] span') or elem.select_one('span[data-hook=\"review-title\"]')
        title = title_elem.get_text(strip=True) if title_elem else ''
        date_elem = elem.select_one('span[data-hook=\"review-date\"]')
        date = date_elem.get_text(strip=True) if date_elem else ''
        body_elem = elem.select_one('span[data-hook=\"review-body\"]')
        body = body_elem.get_text(strip=True) if body_elem else ''
        if body.endswith('Read more'):
            body = body[:(-9)].strip()
        images = []
        for img in elem.select('img'):
            img_class = ''.join(img.get('class', []))
            if 'avatar' in img_class or 'profile' in img_class:
                continue
            else:
                src = img.get('src') or img.get('data-src')
                if src:
                    clean_src = clean_image_url(src, base_url)
                    if clean_src and (not clean_src.endswith('.gif')) and (clean_src not in images):
                                images.append(clean_src)
        reviews.append({'author': author, 'rating': rating, 'title': title, 'date': date, 'body': body, 'images': images})
    return reviews
def scrape_generic_reviews(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Scrape generic product reviews from standard e-commerce elements (Judge.me, Loox, Shopify, etc.)."""
    reviews = []
    review_selectors = ['.review', '.reviews', '.review-item', '.review-list-item', '.testimonial', '.comment-item', '.feedback-item', '.review-card', '.spr-review', '.jdgm-rev', '.loox-review', 'div[id*=\"review\"]', 'div[class*=\"review-item\"]']
    review_elements = []
    for selector in review_selectors:
        found = soup.select(selector)
        if found:
            review_elements = found
            break
    for elem in review_elements[:15]:
        author = 'Verified Customer'
        author_selectors = ['.author', '.name', '.reviewer', '.review-author', '.review-name', '.jdgm-rev__author', '.spr-review-header-byline', '.loox-author', 'strong']
        for a_sel in author_selectors:
            a_elem = elem.select_one(a_sel)
            if a_elem:
                author_text = a_elem.get_text(strip=True)
                if author_text and len(author_text) < 50:
                        author = author_text
                        break
        rating = '5'
        rating_selectors = ['.rating', '.stars', '.score', '.review-rating', '.jdgm-rev__rating', '.spr-starrating', '.loox-rating', '[data-rating]', '[data-score]']
        for r_sel in rating_selectors:
            r_elem = elem.select_one(r_sel)
            if r_elem:
                for attr in ['data-rating', 'data-score', 'data-value']:
                    val = r_elem.get(attr)
                    if val:
                        rating = val
                        break
                if rating!= '5':
                    break
                else:
                    text = r_elem.get_text(strip=True)
                    match = re.search('([0-5](?:\\.[0-9])?)', text)
                    if match:
                        rating = match.group(1)
                        break
                    else:
                        stars_count = text.count('★') or text.count('⭐')
                        if stars_count > 0:
                            rating = str(stars_count)
                            break
        title = ''
        title_selectors = ['.title', '.review-title', '.jdgm-rev__title', '.spr-review-header-title', '.loox-review-title', 'h3', 'h4']
        for t_sel in title_selectors:
            t_elem = elem.select_one(t_sel)
            if t_elem:
                title = t_elem.get_text(strip=True)
                if title:
                    break
        date = ''
        date_selectors = ['.date', '.time', '.review-date', '.jdgm-rev__timestamp', '.spr-review-header-date', '.loox-date']
        for d_sel in date_selectors:
            d_elem = elem.select_one(d_sel)
            if d_elem:
                date = d_elem.get_text(strip=True)
                if date:
                    break
        body = ''
        body_selectors = ['.body', '.content', '.text', '.review-body', '.review-content', '.review-text', '.jdgm-rev__body', '.spr-review-content-body', '.loox-review-body', 'p']
        for b_sel in body_selectors:
            b_elem = elem.select_one(b_sel)
            if b_elem:
                body = b_elem.get_text(strip=True)
                if body:
                    break
        images = []
        for img in elem.select('img'):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src:
                img_class = ''.join(img.get('class', []))
                if 'avatar' in img_class or 'profile' in img_class or 'star' in img_class:
                    continue
                else:
                    clean_src = clean_image_url(src, base_url)
                    if clean_src and (not clean_src.endswith('.gif')) and (clean_src not in images):
                                images.append(clean_src)
        if body or title:
            reviews.append({'author': author, 'rating': rating, 'title': title, 'date': date, 'body': body, 'images': images})
    return reviews
def format_reviews_html(reviews: list[dict]) -> str:
    """Generate an elegant, styled HTML section representing reviews and review images."""
    if not reviews:
        return ''
    else:
        html = []
        html.append('\n<!-- Shopify Reviews Section -->')
        html.append('<div class=\"shopify-reviews-section\" style=\"margin-top: 50px; border-top: 1px solid #e2e8f0; padding-top: 30px; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Oxygen, Ubuntu, Cantarell, \'Open Sans\', \'Helvetica Neue\', sans-serif;\">')
        html.append('  <h2 style=\"font-size: 24px; font-weight: 700; color: #1a202c; margin-bottom: 24px;\">Customer Reviews</h2>')
        html.append('  <div class=\"reviews-list\" style=\"display: flex; flex-direction: column; gap: 24px;\">')
        for r in reviews:
            author = r.get('author', 'Verified Customer')
            rating = r.get('rating', '5')
            title = r.get('title', '')
            date = r.get('date', '')
            body = r.get('body', '')
            images = r.get('images', [])
            try:
                val = float(rating)
                stars_filled = int(round(val))
            except ValueError:
                stars_filled = 5
            stars_html = '★' * stars_filled + '☆' * (5 - stars_filled)
            html.append('    <div class=\"review-item\" style=\"border-bottom: 1px solid #edf2f7; padding-bottom: 20px;\">')
            html.append('      <div class=\"review-meta\" style=\"display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 8px;\">')
            html.append(f'        <span class=\"review-stars\" style=\"color: #ecc94b; font-size: 18px; letter-spacing: 1px;\">{stars_html}</span>')
            html.append(f'        <span class=\"review-author\" style=\"font-weight: 600; color: #2d3748; font-size: 14px;\">{author}</span>')
            if date:
                html.append(f'        <span class=\"review-date\" style=\"color: #a0aec0; font-size: 12px;\">{date}</span>')
            html.append('      </div>')
            if title:
                html.append(f'      <h4 class=\"review-title\" style=\"margin: 0 0 6px 0; font-size: 15px; font-weight: 600; color: #1a202c;\">{title}</h4>')
            if body:
                html.append(f'      <p class=\"review-body\" style=\"margin: 0; color: #4a5568; font-size: 14px; line-height: 1.6;\">{body}</p>')
            if images:
                html.append('      <div class=\"review-images\" style=\"display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px;\">')
                for img_url in images:
                    html.append(f'        <a href=\"{img_url}\" target=\"_blank\" style=\"display: inline-block;\">')
                    html.append(f'          <img src=\"{img_url}\" style=\"width: 80px; height: 80px; object-fit: cover; border-radius: 6px; border: 1px solid #e2e8f0; transition: transform 0.2s;\" onmouseover=\"this.style.transform=\'scale(1.05)\'\" onmouseout=\"this.style.transform=\'scale(1)\'\" alt=\"Review image\" />')
                    html.append('        </a>')
                html.append('      </div>')
            html.append('    </div>')
        html.append('  </div>')
        html.append('</div>')
        html.append('<!-- End Shopify Reviews Section -->\n')
        return '\n'.join(html)
def add_videos_to_shopify_gallery(product_id: int, video_urls: list):
    """Add YouTube/Vimeo videos directly to Shopify\'s product media gallery using GraphQL."""
    graphql_url = f'{SHOP_URL}/admin/api/2025-01/graphql.json'
    graphql_id = f'gid://shopify/Product/{product_id}'
    media_inputs = []
    for url in video_urls:
        if any((x in url.lower() for x in ['youtube.com', 'youtu.be', 'vimeo.com'])):
            normal_url = url
            if 'youtube.com/embed/' in url:
                video_id = url.split('youtube.com/embed/')[(-1)].split('?')[0]
                normal_url = f'https://www.youtube.com/watch?v={video_id}'
            else:
                if 'player.vimeo.com/video/' in url:
                    video_id = url.split('player.vimeo.com/video/')[(-1)].split('?')[0]
                    normal_url = f'https://vimeo.com/{video_id}'
            media_inputs.append({'mediaContentType': 'EXTERNAL_VIDEO', 'originalSource': normal_url, 'alt': 'Product Video'})
    if not media_inputs:
        return None
    else:
        mutation = '\n    mutation productCreateMedia($media: [CreateMediaInput!]!, $productId: ID!) {\n      productCreateMedia(media: $media, productId: $productId) {\n        media {\n          id\n          mediaContentType\n        }\n        mediaUserErrors {\n          code\n          field\n          message\n        }\n      }\n    }\n    '
        try:
            resp = requests.post(graphql_url, headers=shopify_headers(), json={'query': mutation, 'variables': {'productId': graphql_id, 'media': media_inputs}}, timeout=15)
            if resp.status_code == 200:
                res_data = resp.json()
                errors = res_data.get('data', {}).get('productCreateMedia', {}).get('mediaUserErrors', [])
                if errors:
                    print(f'[GraphQL] Warnings adding video media to gallery: {errors}')
                else:
                    created_media = res_data.get('data', {}).get('productCreateMedia', {}).get('media', [])
                    print(f'[GraphQL] Successfully added {len(created_media)} videos to the Shopify gallery.')
            else:
                print(f'[GraphQL] Failed to add videos to gallery. Status: {resp.status_code}, Body: {resp.text}')
        except Exception as e:
            print(f'[GraphQL] Error adding video media: {e}')
def scrape_product_from_url(url: str) -> dict:
    """
    Scrape product title, description, images, and videos from a public product URL or local HTML file.
    - First tries Shopify's JSON endpoint if url is a web address (reliable for Shopify stores).
    - Parses JSON-LD structured data (schema.org Product).
    - Falls back to robust HTML parsing (lazy-loaded images, Open Graph tags, videos).
    - Scrapes reviews (with stars and images) from Amazon or generic sites.
    """
    url = url.strip()
    title = ''
    description = ''
    image_urls = []
    video_urls = []
    reviews = []
    soup = None

    if os.path.isfile(url):
        print(f'[Scraper] Loading local HTML file: {url}')
        try:
            with open(url, 'r', encoding='utf-8') as f:
                html_content = f.read()
            soup = BeautifulSoup(html_content, 'html.parser')
            clean_url = 'https://www.amazon.com/' if 'amazon' in url.lower() else 'https://localhost/'
        except Exception as e:
            print(f'[Error] Failed to read local file: {e}')
            return {'title': '', 'description': '', 'image_urls': [], 'video_urls': [], 'reviews': []}
    else:
        clean_url = url.split('?')[0]

    # Shopify JSON check (only if not a local file)
    if not os.path.isfile(url) and _looks_like_shopify_url(clean_url):
        try:
            json_url = clean_url + '.json' if not clean_url.endswith('.json') else clean_url
            print(f'[Scraper] Trying Shopify JSON endpoint: {json_url}')
            resp = requests.get(json_url, headers=SCRAPER_HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if 'product' in data:
                    prod = data['product']
                    title = prod.get('title', '')
                    description = prod.get('body_html', '')
                    price = str(prod.get('variants', [{}])[0].get('price', '')) if prod.get('variants') else None
                    compare_at = str(prod.get('variants', [{}])[0].get('compare_at_price') or '') or None
                    for img in prod.get('images', []):
                        src = img.get('src')
                        if src:
                            clean_src = clean_image_url(src, url)
                            if clean_src and is_valid_image_url(clean_src) and (clean_src not in image_urls):
                                image_urls.append(clean_src)
                    for media in prod.get('media', []):
                        if media.get('media_type') == 'video':
                            sources = media.get('sources', [])
                            mp4_sources = [s for s in sources if s.get('format') == 'mp4' or 'video/mp4' in s.get('mime_type', '')]
                            if mp4_sources:
                                mp4_sources.sort(key=lambda s: s.get('height', 0), reverse=True)
                                video_urls.append(mp4_sources[0].get('url'))
                        if media.get('media_type') == 'external_video':
                            src = media.get('external_id')
                            host = media.get('host')
                            if host == 'youtube' and src:
                                video_urls.append(f'https://www.youtube.com/watch?v={src}')
                            if host == 'vimeo' and src:
                                video_urls.append(f'https://vimeo.com/{src}')
                    if description:
                        desc_soup = BeautifulSoup(description, 'html.parser')
                        for video in desc_soup.find_all('video'):
                            vsrc = video.get('src')
                            if vsrc:
                                video_urls.append(clean_image_url(vsrc, url))
                            for source in video.find_all('source'):
                                ssrc = source.get('src')
                                if ssrc:
                                    video_urls.append(clean_image_url(ssrc, url))
                        for iframe in desc_soup.find_all('iframe'):
                            isrc = iframe.get('src')
                            if isrc and any((x in isrc for x in ['youtube.com', 'youtu.be', 'vimeo.com'])):
                                video_urls.append(isrc)
                    video_urls = list(dict.fromkeys(video_urls))
                    print(f'[Scraper] Shopify JSON OK — images: {len(image_urls)}, videos: {len(video_urls)}')
                    try:
                        h_resp = requests.get(clean_url, headers=SCRAPER_HEADERS, timeout=10)
                        if h_resp.status_code == 200:
                            reviews = scrape_generic_reviews(BeautifulSoup(h_resp.text, 'html.parser'), clean_url)
                    except Exception as e:
                        print(f'[Scraper] Review fetch warning: {e}')
                    return {'title': title.strip(), 'description': description.strip(), 'image_urls': image_urls, 'video_urls': video_urls, 'reviews': reviews, 'price': price, 'compare_at_price': compare_at}
        except Exception as e:
            print(f'[Scraper] Shopify JSON attempt failed: {e}. Falling back to HTML parsing.')

    # Otherwise parse HTML (either already fetched local soup, or web request)
    if not soup:
        try:
            resp = None
            req_err = None
            try:
                resp = requests.get(url, headers=SCRAPER_HEADERS, timeout=15)
            except Exception as e:
                req_err = e
            is_amazon = 'amazon.' in url.lower()
            is_flipkart = 'flipkart' in url.lower()
            is_meesho = 'meesho' in url.lower()
            use_playwright_fallback = False
            if resp is None:
                use_playwright_fallback = True
            else:
                if resp.status_code in [403, 503] or 'captcha' in resp.text.lower() or 'robot' in resp.text.lower():
                    use_playwright_fallback = True
            if use_playwright_fallback:
                if is_amazon or is_flipkart or is_meesho:
                    platform_name = 'Amazon' if is_amazon else 'Flipkart' if is_flipkart else 'Meesho'
                    print('\n================================================================================')
                    print(f'[Warning] {platform_name} scraping block detected (Captcha/Robot/HTTP/Bot Block).')
                    print(f'{platform_name} heavily guards against direct automated requests.')
                    print('To bypass this, please do the following:')
                    print(f'  1. Save the {platform_name} product page source (Right-click -> Save Page As -> Webpage, HTML Only) to a local file.')
                    print(f'  2. Provide the local file path (e.g., \'{platform_name.lower()}.html\') to this script instead of the web URL.')
                    print('================================================================================\n')
                else:
                    print(f"[Scraper] HTTP error or block detected (status: {(resp.status_code if resp else 'Error')}). Trying Playwright fallback...")
                try:
                    from playwright.sync_api import sync_playwright
                    from fb_reposter import new_browser
                    from pathlib import Path
                    print('[Scraper] Attempting Playwright fallback to render the page...')
                    with sync_playwright() as p:
                        profile_dir = Path(__file__).parent / 'scraper_profile'
                        ctx, page = new_browser(p, profile_dir, headless=True)
                        page.goto(url, timeout=30000)
                        page.wait_for_timeout(6000)
                        html = page.content()
                        soup = BeautifulSoup(html, 'html.parser')
                        print('[Scraper] Playwright rendered page — continuing parse.')
                        ctx.close()
                except Exception as e:
                    print(f'[Scraper] Playwright fallback failed or not installed: {e}')
                    if resp is not None:
                        resp.raise_for_status()
                    else:
                        raise req_err
            else:
                if resp is not None:
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.text, 'html.parser')
                else:
                    raise req_err
        except Exception as e:
            print(f'[Error] Failed to fetch product page HTML: {e}')
            return {'title': '', 'description': '', 'image_urls': [], 'video_urls': [], 'reviews': []}

    site_data = {}
    scraped_price = None
    compare_at_price = None
    low_url = url.lower()
    is_amazon_platform = 'amazon' in low_url or (soup and any(('amazon.' in str(tag) for tag in soup.find_all(['link', 'script', 'meta']))))
    is_flipkart_platform = 'flipkart' in low_url or (soup and any(('flipkart.com' in str(tag) for tag in soup.find_all(['link', 'script', 'meta']))))
    is_meesho_platform = 'meesho' in low_url or (soup and any(('meesho.com' in str(tag) for tag in soup.find_all(['link', 'script', 'meta']))))
    if soup and is_amazon_platform:
        print('[Scraper] Running Amazon-specific extractor...')
        site_data = extract_amazon_product(soup, clean_url)
    elif soup and is_flipkart_platform:
        print('[Scraper] Running Flipkart-specific extractor...')
        site_data = extract_flipkart_product(soup, clean_url)
    elif soup and is_meesho_platform:
        print('[Scraper] Running Meesho-specific extractor...')
        site_data = extract_meesho_product(soup, clean_url)

    if site_data.get('title'):
        title = site_data['title']
    if site_data.get('description'):
        description = site_data['description']
    if site_data.get('image_urls'):
        image_urls = list(dict.fromkeys(site_data['image_urls'] + image_urls))
    scraped_price = site_data.get('price')
    compare_at_price = site_data.get('compare_at_price')

    if not title:
        og_title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'twitter:title'})
        title = _clean_product_title((og_title['content'] if og_title else None) or (soup.title.string if soup.title else ''))
        if not title:
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text(strip=True)
    if not description or len(BeautifulSoup(description, 'html.parser').get_text(strip=True)) < 30:
        og_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        description = og_desc['content'] if og_desc else description or ''
    if not description or len(BeautifulSoup(description, 'html.parser').get_text(strip=True)) < 30:
        desc_selectors = ['div[class*=\'description\']', 'div[id*=\'description\']', 'div[class*=\'product-details\']', 'div[id*=\'product-details\']', 'div[class*=\'details\']', 'div[class*=\'body\']', 'article']
        for selector in desc_selectors:
            element = soup.select_one(selector)
            if element:
                txt_len = len(element.get_text(strip=True))
                if txt_len > 30 and txt_len < 15000:
                    description = str(element)
                    break
    if description and (not description.strip().startswith('<')):
        description = f'<p>{description}</p>'
    json_ld_tags = soup.find_all('script', type='application/ld+json')
    for item in _iter_json_ld_items(soup):
        if not _is_product_type(item):
            continue
        else:
            if not title and item.get('name'):
                title = _clean_product_title(item['name'])
            if (not description or len(BeautifulSoup(description, 'html.parser').get_text(strip=True)) < 50) and item.get('description'):
                description = f"<p>{item['description']}</p>"
            ld_images = item.get('image')
            if ld_images:
                if isinstance(ld_images, str):
                    ld_images = [ld_images]
                else:
                    if isinstance(ld_images, dict):
                        ld_images = [ld_images.get('url', '')]
                    else:
                        ld_images = [x.get('url') if isinstance(x, dict) else x for x in ld_images]
                for img_src in ld_images:
                    if isinstance(img_src, str):
                        clean_src = clean_image_url(img_src, clean_url)
                        if clean_src and is_valid_image_url(clean_src):
                            if clean_src not in image_urls:
                                image_urls.append(clean_src)
            if not scraped_price:
                offers = item.get('offers')
                offer_list = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
                for offer in offer_list:
                    if isinstance(offer, dict) and offer.get('price'):
                        scraped_price = str(offer.get('price'))
                        break
    if len(image_urls) < 3:
        for tag in soup.find_all('meta', property='og:image') + soup.find_all('meta', attrs={'name': 'twitter:image'}):
            src = tag.get('content', '').strip()
            if src:
                clean_src = clean_image_url(src, clean_url)
                if clean_src and is_valid_image_url(clean_src) and (clean_src not in image_urls):
                    image_urls.append(clean_src)
    for tag in soup.find_all('meta', property='og:video') + soup.find_all('meta', property='og:video:secure_url') + soup.find_all('meta', property='og:video:url'):
        src = tag.get('content', '').strip()
        if src:
            clean_src = clean_image_url(src, clean_url)
            if clean_src and clean_src not in video_urls:
                video_urls.append(clean_src)
    if len(image_urls) < 4:
        for img in soup.find_all('img'):
            for attr in ['src', 'data-src', 'data-lazy-src', 'data-original', 'data-fallback-src', 'srcset']:
                src_val = img.get(attr, '').strip()
                if not src_val:
                    continue
                else:
                    urls_in_attr = []
                    if ',' in src_val and (not src_val.startswith('data:')):
                        for part in src_val.split(','):
                            parts = part.strip().split()
                            if parts:
                                urls_in_attr.append(parts[0])
                    else:
                        urls_in_attr.append(src_val)
                    for raw_img_url in urls_in_attr:
                        clean_src = clean_image_url(raw_img_url, clean_url)
                        if clean_src and is_valid_image_url(clean_src) and (clean_src not in image_urls):
                            image_urls.append(clean_src)
    for video in soup.find_all('video'):
        vsrc = video.get('src')
        if vsrc:
            clean_vsrc = clean_image_url(vsrc, clean_url)
            if clean_vsrc and clean_vsrc not in video_urls:
                video_urls.append(clean_vsrc)
        for source in video.find_all('source'):
            ssrc = source.get('src')
            if ssrc:
                clean_ssrc = clean_image_url(ssrc, clean_url)
                if clean_ssrc and clean_ssrc not in video_urls:
                    video_urls.append(clean_ssrc)
    for iframe in soup.find_all('iframe'):
        isrc = iframe.get('src', '').strip()
        if isrc:
            if isrc.startswith('//'):
                isrc = 'https:' + isrc
            if any((x in isrc.lower() for x in ['youtube.com', 'youtu.be', 'vimeo.com', 'player.vimeo'])):
                if isrc not in video_urls:
                    video_urls.append(isrc)
    image_urls = list(dict.fromkeys(image_urls))
    video_urls = list(dict.fromkeys(video_urls))
    image_urls = image_urls[:15]
    is_amazon = 'amazon.' in url.lower()
    if is_amazon:
        reviews = scrape_amazon_reviews(soup, clean_url)
    else:
        reviews = scrape_generic_reviews(soup, clean_url)
    price = scraped_price
    if not price:
        try:
            mp = soup.find('meta', property='product:price:amount') or soup.find(attrs={'itemprop': 'price'})
            if mp:
                price = (mp.get('content') or mp.get('value') or mp.get_text() or '').strip()
            if not price and 'resp' in locals() and resp is not None:
                m = re.search('(?:₹|Rs\\.?|\\$)\\s*([\\d,]+(?:\\.\\d{2})?)', resp.text)
                if m:
                    price = m.group(1).replace(',', '')
        except Exception:
            price = None
    return {'title': title.strip() if title else 'Scraped Product', 'description': description.strip(), 'image_urls': image_urls, 'video_urls': video_urls, 'reviews': reviews, 'price': price, 'compare_at_price': compare_at_price}
def create_product(title, description, image_urls, video_urls, price, compare_price, collection_id=None, reviews=None, cod_on=True):
    embed_html = ''
    for vurl in video_urls:
        if vurl.lower().endswith('.mp4') or 'video/mp4' in vurl.lower() or '.mov' in vurl.lower():
            embed_html += f'\n<div class=\"product-video\" style=\"text-align: center; margin: 20px 0;\">\n  <video controls src=\"{vurl}\" style=\"max-width: 100%; height: auto; border-radius: 8px;\" preload=\"metadata\"></video>\n</div>\n'
        else:
            if any((x in vurl.lower() for x in ['youtube.com', 'youtu.be', 'vimeo.com', 'player.vimeo'])):
                embed_src = get_embed_url(vurl)
                embed_html += f'\n<div class=\"product-video-embed\" style=\"text-align: center; margin: 20px 0;\">\n  <iframe width=\"560\" height=\"315\" src=\"{embed_src}\" frameborder=\"0\" allow=\"autoplay; encrypted-media\" allowfullscreen style=\"max-width: 100%; border-radius: 8px;\"></iframe>\n</div>\n'
    if embed_html:
        description = description + '\n' + embed_html
    product = {'product': {'title': title, 'body_html': description, 'status': 'active', 'images': [{'src': url} for url in image_urls], 'variants': [{'price': str(price), 'compare_at_price': str(compare_price), 'taxable': False}]}}
    if not cod_on:
        product['product']['template_suffix'] = ''
        product['product']['tags'] = 'no-cod, disable-cod, No COD, cod-disabled, releasit-disable, releasit_disable, releasit-no-cod, releasit_no_cod, disable_cod, no_cod'
        ensure_no_cod_smart_collection()
    r = requests.post(f'{SHOP_URL}/admin/api/2025-01/products.json', headers=shopify_headers(), json=product)
    r.raise_for_status()
    created = r.json()['product']
    print('Created:', created['title'])
    if not cod_on:
        print('\n[Releasit COD Form] Cash on Delivery is turned OFF for this product.')
        print('Note: To hide the Releasit storefront form on the product page, make sure the \'No COD\' collection is added in the Releasit App Visibility settings.')
    if video_urls:
        print('Linking video URLs to Shopify gallery...')
        add_videos_to_shopify_gallery(created['id'], video_urls)
    if collection_id:
        collect_payload = {'collect': {'product_id': created['id'], 'collection_id': collection_id}}
        requests.post(f'{SHOP_URL}/admin/api/2025-01/collects.json', headers=shopify_headers(), json=collect_payload)
    return created
def check_live_product_page_with_ai(product_url: str) -> bool:
    """\n    Open the live storefront product URL using Playwright, capture a screenshot,\n    and send it to Vision AI to determine if the page rendered successfully.\n    """
    print(f'\n[AI Verification] Opening live product page: {product_url}')
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[AI Verification Error] Playwright not installed. Cannot run live site check. Run: pip install playwright')
        return False
    screenshot_path = 'live_product_page_screenshot.png'
    print('[AI Verification] Loading page in headless browser...')
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1280, 'height': 800})
            page = context.new_page()
            page.goto(product_url, wait_until='load', timeout=30000)
            page.wait_for_timeout(3000)
            page.screenshot(path=screenshot_path)
            print(f'[AI Verification] Captured page screenshot: {screenshot_path}')
            browser.close()
    except Exception as e:
        print(f'[AI Verification Error] Failed to load page or capture screenshot: {e}')
        return False
    try:
        with open(screenshot_path, 'rb') as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        print(f'[AI Verification Error] Failed to read screenshot file: {e}')
        return False
    mime_type = 'image/png'
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Analyze this screenshot of the live Shopify storefront page we just created.\nVerify if the page is completely okay and rendered successfully.\nCheck for the following issues:\n1. 404 Not Found error (page not found, broken link).\n2. Password page / Store locked page (asking for password to enter).\n3. Blank or empty white page (nothing rendered/loaded).\n4. Broken layout, major overlapping elements, or broken design issues.\n5. Missing key product elements like empty titles or loading spinners.\n\nRespond in JSON format with two keys:\n- \"is_ok\": true (if the page rendered successfully and has no issues) or false (if any of the above issues are present).\n- \"reason\": A detailed explanation of why it is not okay, or \'Page rendered correctly\' if it is completely okay.'}, {'type': 'image_url', 'image_url': {'url': f'data:{mime_type};base64,{encoded_image}'}}]}]
    print('[AI Verification] Sending screenshot to Vision AI...')
    try:
        reply = _vision_chat(messages, max_tokens=1024)
        j = _parse_ai_json(reply)
        if isinstance(j, dict):
            is_ok = j.get('is_ok')
            reason = j.get('reason', '')
            if is_ok:
                print(f'[AI Verification] [OK] The live product page is completely okay. (Reason: {reason})')
                return True
            else:
                print('\n========================================================')
                print('[AI Verification] [ALERT] The live product page has issues!')
                print(f'Details: {reason}')
                print(f'Please inspect the screenshot saved at: {os.path.abspath(screenshot_path)}')
                print('========================================================\n')
                return False
        else:
            print(f'[AI Verification] [WARN] Could not parse AI JSON response. Raw output: {reply}')
            return False
    except Exception as e:
        print(f'[AI Verification Error] Vision AI analysis failed: {e}')
        return False
def get_product_visual_description(product_title: str, product_description: str='', product_image_url: str | None=None) -> str:
    """
    Generate a realistic physical description of the product based on its title, description,
    and image URL (using Vision AI if possible).
    """
    if product_image_url and get_working_vision_clients():
        try:
            if product_image_url.startswith('//'):
                product_image_url = 'https:' + product_image_url
            resp = requests.get(product_image_url, headers=SCRAPER_HEADERS, timeout=15)
            if resp.status_code == 200:
                ctype = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0]
                encoded_image = base64.b64encode(resp.content).decode('utf-8')
                messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Analyze this product image. Describe its physical appearance, packaging design, colors, label text/graphics, and material details in detail but concisely so we can generate a similar-looking image in a customer review. Do not mention background, context, or studio elements. Focus only on the product itself. Keep it under 50 words.'}, {'type': 'image_url', 'image_url': {'url': f'data:{ctype};base64,{encoded_image}'}}]}]
                print('[Auto-Reviews] Sending product image to Vision AI for visual description...')
                desc = _vision_chat(messages, max_tokens=150)
                clean_desc = desc.strip().strip('\"').strip('\'') if desc else ''
                if len(clean_desc) >= 25 and (not clean_desc.endswith(',')) and (not clean_desc.endswith(':')) and (not clean_desc.endswith('...')):
                    print(f'[Auto-Reviews] Visual description from Vision AI: {clean_desc}')
                    return clean_desc
        except Exception as e:
            print(f'[Auto-Reviews] [WARN] Failed to analyze product image with Vision AI: {e}')
        if AI_CLIENTS:
            try:
                plain_desc = BeautifulSoup(product_description or '', 'html.parser').get_text(' ', strip=True)[:1000]
                prompt = [{'role': 'system', 'content': 'You are a product visualizer. Write a short, highly realistic physical description of the product\'s appearance based on text details.'}, {'role': 'user', 'content': f'Product Title: {product_title}\nProduct Description: {plain_desc}\n\nWrite a highly realistic, concise 10-15 word physical description of the product itself (e.g., its packaging type, labeling, color, or shape, like \'a small kraft paper pouch of seeds with a green grass label\' or \'a wooden-handled kitchen peeler with a steel blade\'). Focus only on the product itself, no background or action. Do not write full sentences.'}]
                desc = ai_chat(prompt, max_tokens=60)
                clean_desc = desc.strip().strip('\"').strip('\'')
                print(f'[Auto-Reviews] Visual description from Text AI: {clean_desc}')
                return clean_desc
            except Exception as e:
                print(f'[Auto-Reviews] [WARN] Text AI physical description failed: {e}')
        return product_title or 'product'
def auto_submit_reviews(product_url: str, num_reviews: int=3, product_title: str | None=None, product_description: str | None=None, product_image_url: str | None=None) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[Auto-Reviews Error] Playwright is not installed. Run: pip install playwright')
        return False

    print(f'\n[Auto-Reviews] Starting automatic reviews submission for: {product_url}')
    product_desc = product_description or ''
    if not product_image_url:
        try:
            resp = requests.get(product_url, headers=SCRAPER_HEADERS, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                if not product_desc:
                    og_desc = soup.find('meta', property='og:description')
                    if og_desc:
                        product_desc = og_desc.get('content', '')
                    if not product_desc:
                        product_desc = soup.get_text()[:2000]
                og_img = soup.find('meta', property='og:image')
                if og_img:
                    product_image_url = og_img.get('content')
        except Exception as e:
            print(f'[Auto-Reviews] [WARN] Failed to pre-fetch product page context: {e}')

    visual_desc = get_product_visual_description(product_title or 'product', product_desc, product_image_url)
    if visual_desc:
        visual_desc = visual_desc.strip().rstrip('.')
        if visual_desc.lower().startswith('a '):
            visual_desc = 'a ' + visual_desc[2:]
        elif visual_desc.lower().startswith('an '):
            visual_desc = 'an ' + visual_desc[3:]
        elif visual_desc.lower().startswith('the '):
            visual_desc = 'the ' + visual_desc[4:]
        else:
            if len(visual_desc) > 1 and visual_desc[0].isupper() and not visual_desc[1].isupper():
                visual_desc = visual_desc[0].lower() + visual_desc[1:]

    reviews_data = []
    if AI_CLIENTS:
        try:
            print('[Auto-Reviews] Generating names and reviews using AI...')
            prompt = [
                {'role': 'system', 'content': 'You are a review generator. Generate realistic, highly diverse Malayalee (Kerala) customer reviews. Avoid duplicates and repetitive patterns.'},
                {'role': 'user', 'content': f"Generate exactly {num_reviews} customer reviews for a Shopify product named '{product_title}'.\nPhysical description of the actual product: {visual_desc}\n\nEach review must contain:\n1. A realistic Kerala (Malayalee) name. Do not follow any template. Use every type of names in Kerala (Hindu, Christian, and Muslim names across genders, e.g. 'Fathima Farhana', 'Jithin Mathew', 'Sreerag K. S.', 'Athira Rajesh'). Vary the format (some with initials, some first + last name).\n2. A random rating (integer 4 or 5 only).\n3. A review body. Randomise and mix English reviews and Manglish reviews (Malayalam written in English alphabet). Do not reuse the same review body text. Every review body must be unique and contextually relevant to the product.\n\nRespond strictly in JSON format as a list of objects with keys: 'name', 'rating', and 'body'."}
            ]
            reply = ai_chat(prompt, max_tokens=1500)
            parsed = _parse_ai_json(reply)
            if isinstance(parsed, list):
                reviews_data = parsed[:num_reviews]
                print(f'[Auto-Reviews] Generated {len(reviews_data)} reviews via AI.')
        except Exception as e:
            print(f'[Auto-Reviews] Warning: AI generation failed: {e}. Falling back to pre-defined reviews.')

    if not reviews_data:
        import random
        kerala_names = ['Sreerag K. S.', 'Vishnu Prasad', 'Anjali Nair', 'Akhil Krishnan', 'Nimisha Suresh', 'Arya S. Kumar', 'Devika Rajan', 'Gokul Das', 'Reshma Pillai', 'Sarath Chandran', 'Parvathy M.', 'Rahul R.', 'Athira Rajesh', 'Abhijith Nair', 'Sruthi Mohan', 'Anupama V.', 'Gopika S.', 'Karthika S. Nair', 'Adarsh Pillai', 'Amal Dev', 'Keerthana R.', 'Siddharth C. P.', 'Nandana S.', 'Arjun K. Prasad', 'Meera Krishnan', 'Hari Narayanan', 'Sandhya R. Nath', 'Vaisakh M. S.', 'Malavika S.', 'Vivek Chandran', 'Jithin George', 'Amal Joseph', 'Jithin Mathew', 'Riya Mary John', 'Sherin Joseph', 'Merlin Baby', 'Thomas Kurian', 'Basil Eldhose', 'Jerry John', 'Tony Sebastian', 'Febin Paul', 'Lidiya Paul', 'Angel Mary', 'Ansu Kurian', 'Jibin Mathew', 'Sneha George', 'Tinu Thomas', 'Sony Sebastian', 'Albin Benny', 'Jobin Joseph', 'Deepa Thomas']
        random.shuffle(kerala_names)
        manglish_reviews = ['Super product aanu! Njan ithu use cheythu nokki, quality valare nannayittundu.', 'Kidu product, highly recommended! Delivery nalla fast aayirunnu.', 'Quality super aanu, packingum kollam. Worth the money.', 'Nalla product aanu, njan ithu online aayi vangiyathaanu, valare nannayittundu.', 'Superb item! Enikk valare ishtamaayi. Ellarkkum dhairyamaayi vaangam.', 'Valare nalla experience aayirunnu. Product double ok aanu.', 'Item super! Delivery and packaging excellent aayirunnu. Thanks!', 'Enikku ithu valare upayogapradhamayi thonni. Nalla quality und.', 'Nalla item. Enikku valare ishtapettu. Price kuravaanu.', 'Product kollam, highly satisfied. Nalla service aayirunnu.', 'Nallonam use cheyyan pattunnundu. Value for money product.', 'Awesome product. Ente veettukaarkkum valare ishtapettu.', 'Quality parayanilla, highly recommended item!', 'Njan prethikshichathinekkal nallathaanu. Super choice.', 'Valare nalla packing and fast delivery. Thanks seller!', 'Kidu item! Highly recommended. Ellaam nannayittundu.', 'Vangiyappol thottu use cheyyunnundu. Valare nalla performance.', 'Superb quality, price nalla budget-friendly aanu.', 'Good quality product and quick delivery. I am very happy.', 'Nalla packing deep aayirunnu, safe aayi kitti. Item super aanu.']
        english_reviews = ['Really good quality product. Very satisfied with the purchase!', 'Amazing product and super fast shipping. Highly recommend this store.', 'Item arrived in perfect condition. Works exactly as described.', 'Value for money! Best quality in this price range.', 'Outstanding customer support and high-quality build. Will buy again.', 'Excellent product. Exceeded my expectations.', 'Very handy and useful. Five stars from my side!', 'Great packaging and fast delivery. Product is also top notch.', 'Wonderful experience buying this. Quality is superb.', 'Exceeded expectations, definitely buying another one.', 'Simple, elegant and does the job perfectly. 10/10.', 'The customer service was great, and the product is amazing.', 'Very fast shipping. Excellent build quality and design.', 'Highly impressed with the craftsmanship and materials. Highly recommend.', 'Worth every single penny. Very fast shipping too!', 'Exactly as shown in the pictures. The performance is top-notch.', 'Very well packaged and arrived ahead of time. Highly satisfied.', 'Perfect fit and matches the description 100%. Excellent seller.', 'Works perfectly, setup was extremely easy. Good purchase.', 'Highly functional and has a premium feel to it. Will recommend to others.']
        all_reviews = manglish_reviews + english_reviews
        random.shuffle(all_reviews)
        for idx in range(num_reviews):
            name = kerala_names[idx % len(kerala_names)]
            rating = random.choice([4, 5])
            body = all_reviews[idx % len(all_reviews)]
            reviews_data.append({'name': name, 'rating': rating, 'body': body})

    import random
    for item in reviews_data:
        clean_name = re.sub('[^a-zA-Z]', '', item['name'].lower())
        item['email'] = f"{clean_name}{random.randint(10, 99)}@gmail.com"

    print(f'[Auto-Reviews] Initializing Playwright browser to submit {len(reviews_data)} review(s)...')
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for i, r in enumerate(reviews_data, 1):
                name = r['name']
                email = r['email']
                rating = r['rating']
                body = r['body']
                print(f"  [{i}/{len(reviews_data)}] Submitting review by '{name}' ({rating} stars)...")
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                try:
                    page.goto(product_url, wait_until='load', timeout=30000)
                    try:
                        page.wait_for_selector('.jdgm-widget, .jdgm-review-widget, .jdgm-write-rev-btn, button.head-button.tt-write-reviews, .tt-write-reviews, button:has-text("Write a review")', timeout=10000)
                    except Exception:
                        pass
                    
                    is_judgeme = page.locator('.jdgm-widget, .jdgm-review-widget, .jdgm-write-rev-btn').count() > 0
                    if is_judgeme:
                        print('    [Auto-Reviews] Judge.me reviews widget detected. Running multi-step modal flow...')
                        btn_selector = '.jdgm-write-rev-btn, button.jm-button.jm-action-buttons__button'
                        try:
                            page.wait_for_selector(btn_selector, timeout=8000)
                        except Exception:
                            pass
                        write_button = page.locator(btn_selector)
                        if write_button.count() == 0:
                            print("    [Error] 'Write a review' button not found for Judge.me.")
                            context.close()
                            continue
                        
                        modal_visible = False
                        for attempt in range(5):
                            try:
                                write_button.first.click(force=True)
                                page.wait_for_selector('.jdgm-write-review-modal', state='visible', timeout=2000)
                                modal_visible = True
                            except Exception:
                                print(f'    Modal not visible yet, retrying click (attempt {attempt + 1}/5)...')
                                page.wait_for_timeout(1000)
                            else:
                                break
                        
                        if not modal_visible:
                            print('    [Error] Judge.me write review modal did not appear.')
                            context.close()
                            continue
                        
                        try:
                            page.wait_for_selector('.jdgm-write-review-modal__stars', state='visible', timeout=5000)
                        except Exception:
                            pass
                        
                        star_selector = f".jdgm-write-review-modal__stars .jdgm-star[data-val='{rating}'], .jdgm-write-review-modal__stars .jdgm-star"
                        stars = page.locator(star_selector)
                        if stars.count() > 0:
                            stars.nth(rating - 1).click(force=True)
                        else:
                            print('    [Error] Stars not found in Judge.me modal.')
                            context.close()
                            continue
                        
                        body_input = page.locator('textarea#jdgm-review-body-input, textarea[id*="body"]')
                        try:
                            body_input.first.wait_for(state='visible', timeout=5000)
                        except Exception:
                            pass
                        
                        if body_input.count() > 0:
                            body_input.first.fill(body)
                            page.wait_for_timeout(500)
                            next_button = page.locator('button.jdgm-write-review-modal__nav-btn-next')
                            if next_button.count() > 0:
                                next_button.first.click(force=True)
                                page.wait_for_timeout(1000)
                                email_input = page.locator('input#jdgm-email-input')
                                name_input = page.locator('input#jdgm-name-input')
                                try:
                                    email_input.first.wait_for(state='visible', timeout=5000)
                                except Exception:
                                    pass
                                if email_input.count() > 0:
                                    email_input.first.fill(email)
                                if name_input.count() > 0:
                                    name_input.first.fill(name)
                                page.wait_for_timeout(500)
                                if next_button.count() > 0:
                                    next_button.first.click(force=True)
                                    page.wait_for_timeout(1000)
                                    try:
                                        page.wait_for_selector('.jdgm-write-review-modal__page--media, button.jdgm-write-review-modal__nav-btn-next', state='visible', timeout=5000)
                                    except Exception:
                                        pass
                                    if next_button.count() > 0:
                                        next_button.first.click(force=True)
                                        print('    Submitted successfully to Judge.me!')
                                        page.wait_for_timeout(3000)
                                    else:
                                        print('    [Error] Submit button not found in Judge.me modal.')
                                else:
                                    print('    [Error] Next button not found after name/email.')
                            else:
                                print('    [Error] Next button not found after review body.')
                        else:
                            print('    [Error] Review body text area not found in Judge.me modal.')
                            context.close()
                            continue
                    else:
                        print('    [Auto-Reviews] TrustWILL/Standard reviews widget detected. Running single-page flow...')
                        btn_selector = 'button.head-button.tt-write-reviews, .tt-write-reviews, button:has-text("Write a review"), .spr-summary-actions-newreview'
                        try:
                            page.wait_for_selector(btn_selector, timeout=8000)
                        except Exception:
                            pass
                        write_button = page.locator(btn_selector)
                        if write_button.count() > 0:
                            form_visible = False
                            form_selector = 'textarea.big-input.user-input.require, .tt-write-content textarea, textarea[name="body"], #review_body'
                            for attempt in range(5):
                                try:
                                    write_button.first.click(force=True)
                                    page.wait_for_selector(form_selector, state='visible', timeout=2000)
                                    form_visible = True
                                except Exception:
                                    print(f'    Form not visible yet, retrying click (attempt {attempt + 1}/5)...')
                                    page.wait_for_timeout(1000)
                                else:
                                    break
                            if not form_visible:
                                print('    [Error] Review form not visible.')
                                context.close()
                                continue
                            
                            stars_selectors = ['.vstar-star .star-item', '.tt-write-content .stars div', '.tt-write-content [class*="star"] div', '.tt-write-content svg', '.tt-write-content .star-item', '.spr-starrating a', '.jdgm-write-rev__rating a', '[data-rating]']
                            stars_clicked = False
                            for selector in stars_selectors:
                                stars = page.locator(selector)
                                if stars.count() >= rating:
                                    stars.nth(rating - 1).click(force=True)
                                    stars_clicked = True
                                    page.wait_for_timeout(500)
                                    break
                            if not stars_clicked:
                                print('    [Warn] Star rating element not explicitly clicked, continuing with form fill...')
                            
                            body_field = page.locator('textarea.big-input.user-input.require, .tt-write-content textarea, textarea[name="body"], textarea[placeholder*="write" i], #review_body')
                            if body_field.count() > 0:
                                body_field.first.fill(body)
                                name_filled = False
                                email_filled = False
                                small_inputs = page.locator('.tt-write-content input.small-input, .tt-write-content input.user-input')
                                if small_inputs.count() >= 2:
                                    small_inputs.nth(0).fill(name)
                                    small_inputs.nth(1).fill(email)
                                    name_filled = True
                                    email_filled = True
                                if not name_filled:
                                    name_field = page.locator('input[name="author"], input[placeholder*="name" i], #review_author, .tt-write-content input[placeholder*="name" i]')
                                    if name_field.count() > 0:
                                        name_field.first.fill(name)
                                        name_filled = True
                                if not email_filled:
                                    email_field = page.locator('input[type="email"], input[placeholder*="email" i], #review_email, .tt-write-content input[placeholder*="email" i]')
                                    if email_field.count() > 0:
                                        email_field.first.fill(email)
                                        email_filled = True
                                
                                submit_button = page.locator('button.form-submit, .tt-write-content .form-submit, button:has-text("Submit"), input[type="submit"], .spr-button-primary, .jdgm-submit-rev')
                                if submit_button.count() > 0:
                                    submit_button.first.click(force=True)
                                    print('    Submitted successfully!')
                                    page.wait_for_timeout(2000)
                                else:
                                    print('    [Error] Submit button not found.')
                            else:
                                print('    [Error] Review body text area not found.')
                        else:
                            print("    [Error] 'Write a review' button not found on page.")
                except Exception as ex:
                    print(f'    [Error] Failed during submission flow: {ex}')
                finally:
                    context.close()
            browser.close()
        print('[Auto-Reviews] Completed all review submissions.')
        return True
    except Exception as e:
        print(f'[Auto-Reviews Error] Playwright execution failed: {e}')
        return False
def manual_input():
    """Prompt the user to enter all product details manually."""
    title = input('Title: ')
    description = input('Description HTML: ')
    image_urls = []
    while True:
        url = input('Image URL (blank to finish): ').strip()
        if not url:
            break
        else:
            image_urls.append(url)
    video_urls = []
    while True:
        url = input('Video URL (blank to finish): ').strip()
        if not url:
            break
        else:
            video_urls.append(url)
    reviews = []
    add_revs = input('Add custom reviews? (y/n): ').strip().lower()
    if add_revs == 'y':
        while True:
            author = input('Reviewer Name (blank to finish): ').strip()
            if not author:
                break
            else:
                rating = input('Rating (1-5, default 5): ').strip() or '5'
                rev_title = input('Review Title (optional): ').strip()
                body = input('Review Body Content: ').strip()
                rev_images = []
                while True:
                    r_img = input('Review Image URL (blank to finish): ').strip()
                    if not r_img:
                        break
                    else:
                        rev_images.append(r_img)
                reviews.append({'author': author, 'rating': rating, 'title': rev_title, 'body': body, 'images': rev_images})
    return (title, description, image_urls, video_urls, reviews)
def _print_scraped_summary(data: dict) -> None:
    print('\n--- Scraped Details ---')
    print(f"Title         : {data.get('title')}")
    desc_plain = BeautifulSoup(data.get('description', ''), 'html.parser').get_text(' ', strip=True)
    print(f"Description   : {desc_plain[:160]}{('...' if len(desc_plain) > 160 else '')}")
    print(f"Price         : {data.get('price') or 'not found'}")
    print(f"Compare Price : {data.get('compare_at_price') or 'not found'}")
    print(f"Images found  : {len(data.get('image_urls', []))}")
    for i, img in enumerate(data.get('image_urls', []), 1):
        print(f'  [{i}] {img}')
    print(f"Videos found  : {len(data.get('video_urls', []))}")
    print(f"Reviews found : {len(data.get('reviews', []))}")
    print('-----------------------\n')
def url_input():
    """Scrape product details from a public URL, analyze with AI, validate images, then push."""
    product_url = input('Product URL or local HTML file path (e.g. Amazon link): ').strip()
    cod_choice = input('Turn on Cash on Delivery (COD)? (y/n) [y]: ').strip().lower()
    cod_on = cod_choice!= 'n'
    print('Fetching product details...')
    data = scrape_product_from_url(product_url)
    if not data.get('title') and (not data.get('image_urls')):
            print('[Error] Scrape returned almost nothing. Try saving the page as HTML locally, or use a different URL.')
            exit()
    _print_scraped_summary(data)
    if AI_CLIENTS:
        print('--- AI Analysis ---')
        print(analyze_scraped_product_with_ai(data))
        print('-------------------\n')
    print('Validating images (always runs before Shopify upload)...')
    validated = verify_images_with_ai(data.get('title', ''), data.get('image_urls', []))
    if not validated:
        print('[Error] No valid product images after validation. Cannot push to Shopify.')
        exit()
    print(f"Validated images: {len(validated)} of {len(data.get('image_urls', []))}")
    data['image_urls'] = validated
    print('\nWhat do you want to do?')
    print('  1) Rewrite title, description, price & compare price with AI, then push')
    print('  2) Push scraped data as-is (images already validated)')
    print('  3) Cancel')
    mode = input('Choose (1/2/3): ').strip()
    if mode == '3':
        print('Cancelled.')
        exit()
    if mode not in ['1', '2']:
        print('Invalid choice.')
        exit()
    final_title = data['title']
    final_desc = data['description']
    final_price = data.get('price')
    final_compare = data.get('compare_at_price')
    if mode == '1':
        if not AI_CLIENTS:
            print('AI not available — falling back to scraped values.')
        else:
            print('\nRewriting with AI...')
            ai_title, ai_desc, ai_price, ai_compare = generate_title_description_and_pricing(data['title'], data['description'], data.get('price'))
            print(f'\nAI Title         : {ai_title}')
            print(f'AI Price         : {ai_price}')
            print(f'AI Compare Price : {ai_compare}')
            print(f"AI Description   : {BeautifulSoup(ai_desc, 'html.parser').get_text(' ', strip=True)[:200]}...")
            if input('Use AI title? (y/n) [y]: ').strip().lower()!= 'n':
                final_title = ai_title
            if input('Use AI description? (y/n) [y]: ').strip().lower()!= 'n':
                final_desc = ai_desc
            if ai_price and input(f'Use AI price {ai_price}? (y/n) [y]: ').strip().lower()!= 'n':
                    final_price = ai_price
            if ai_compare and input(f'Use AI compare price {ai_compare}? (y/n) [n]: ').strip().lower() == 'y':
                    final_compare = ai_compare
    override = input(f'\nTitle [{final_title}] (Enter to keep): ').strip()
    if override:
        final_title = override
    if not final_price:
        final_price = input('Price (required): ').strip()
    else:
        p = input(f'Price [{final_price}] (Enter to keep): ').strip()
        if p:
            final_price = p
    if final_compare:
        c = input(f'Compare Price [{final_compare}] (Enter to keep, blank to clear): ').strip()
        final_compare = c if c else final_compare
    else:
        final_compare = input('Compare Price (blank if none): ').strip() or None
    if not final_price:
        print('Price is required. Cancelled.')
        exit()
    confirm = input(f"\nPush \'{final_title}\' to Shopify with {len(data['image_urls'])} image(s)? (y/n): ").strip().lower()
    if confirm!= 'y':
        print('Cancelled.')
        exit()
    return (final_title, final_desc, data['image_urls'], data['video_urls'], data.get('reviews', []), final_price, final_compare, cod_on)
def update_product_cod(product_id: str, cod_on: bool) -> bool:
    """Update an existing product on Shopify to turn Cash on Delivery on or off."""
    headers = shopify_headers()
    try:
        r = requests.get(f'{SHOP_URL}/admin/api/2025-01/products/{product_id}.json', headers=headers, timeout=10)
        r.raise_for_status()
        product_data = r.json().get('product', {})
    except Exception as e:
        print(f'[Error] Failed to fetch product details: {e}')
        return False
    current_tags_str = product_data.get('tags', '')
    current_tags = [t.strip() for t in current_tags_str.split(',') if t.strip()]
    cod_tags = ['no-cod', 'disable-cod', 'No COD', 'cod-disabled', 'releasit-disable', 'releasit_disable', 'releasit-no-cod', 'releasit_no_cod', 'disable_cod', 'no_cod']
    if not cod_on:
        for tag in cod_tags:
            if tag not in current_tags:
                current_tags.append(tag)
        template_suffix = ''
        ensure_no_cod_smart_collection()
    else:
        current_tags = [t for t in current_tags if t not in cod_tags]
        template_suffix = ''
    new_tags_str = ', '.join(current_tags)
    update_payload = {'product': {'id': int(product_id), 'tags': new_tags_str, 'template_suffix': template_suffix}}
    try:
        r = requests.put(f'{SHOP_URL}/admin/api/2025-01/products/{product_id}.json', headers=headers, json=update_payload, timeout=10)
        r.raise_for_status()
        print(f"[Shopify] Product COD updated successfully! (COD={('ON' if cod_on else 'OFF')})")
        if not cod_on:
            print('\n[Releasit COD Form] Cash on Delivery is turned OFF for this product.')
            print('Note: To hide the Releasit storefront form on the product page, make sure the \'No COD\' collection is added in the Releasit App Visibility settings.')
    except Exception as e:
        print(f'[Error] Failed to update product COD on Shopify: {e}')
        return False
    else:
        return True
def is_product_automated(headers: dict, target_url: str) -> bool:
    print('[SuperProfile] Checking if product is already automated...')
    session = requests.Session()
    list_url = 'https://prod.api.cosmofeed.com/api/adm/list_auto_dms?page=1&limit=500&submissionType=0'
    try:
        resp = session.get(list_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f'[SuperProfile] Warning: Failed to fetch automations list (status {resp.status_code}).')
            return False
        automations = resp.json().get('data', {}).get('data', [])
        print(f'[SuperProfile] Scanning {len(automations)} automations...')
        for idx, auto in enumerate(automations):
            auto_id = auto['_id']
            detail_url = f'https://prod.api.cosmofeed.com/api/adm/get_auto_dm_details?autoDmId={auto_id}'
            try:
                r = session.get(detail_url, headers=headers, timeout=4)
                if r.status_code == 200:
                    buttons = r.json().get('data', {}).get('messageToSend', {}).get('buttons', [])
                    for btn in buttons:
                        link = btn.get('link', '')
                        if target_url.strip().lower() in link.strip().lower():
                            print(f'[SuperProfile] Match found on automation {auto_id}!')
                            return True
            except Exception:
                continue
    except Exception as e:
        print(f'[SuperProfile] Warning: Exception during automation check: {e}')
    return False
def run_superprofile_automation(product_url: str, product_title: str, enable_follow_gate: bool=True, check_existing: bool=False, override_keyword: str=None):
    """
    Wrapper for SuperProfile comment automation: tries headlessly first, and on failure,
    automatically retries in visible/headful mode to allow manual correction/intervention.
    """
    print('[Auto-DM] Running SuperProfile automation headlessly...')
    try:
        return _run_superprofile_automation_impl(product_url=product_url, product_title=product_title, enable_follow_gate=enable_follow_gate, check_existing=check_existing, override_keyword=override_keyword, headless=True)
    except Exception as e:
        print('\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        print(f'[Auto-DM Warning] Headless automation run failed: {e}')
        print('[Auto-DM Warning] Waiting 3 seconds for browser file locks to release, then re-running in VISIBLE mode...')
        print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n')
        import time
        time.sleep(3)
        try:
            return _run_superprofile_automation_impl(product_url=product_url, product_title=product_title, enable_follow_gate=enable_follow_gate, check_existing=check_existing, override_keyword=override_keyword, headless=False)
        except Exception as retry_err:
            print(f'[Auto-DM Error] Visible automation run retry failed: {retry_err}')
            return False
def _run_superprofile_automation_impl(product_url: str, product_title: str, enable_follow_gate: bool=True, check_existing: bool=False, override_keyword: str=None, headless: bool=True):
    # irreducible cflow, using cdg fallback
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[Auto-DM Error] Playwright is not installed. Run: pip install playwright')
        return False
    from pathlib import Path
    base_dir = Path(__file__).parent
    ig_profile_dir = base_dir / 'ig_profile'
    ig_profile_dir.mkdir(exist_ok=True)
    print('\n============================================================')
    print(f'[Auto-DM] Starting SuperProfile Bio automation (headless={headless})...')
    print(f'[Auto-DM] Product URL  : {product_url}')
    print(f'[Auto-DM] Product Title: {product_title}')
    print(f'[Auto-DM] Profile Dir  : {ig_profile_dir}')
    print(f'[Auto-DM] Follow Gate  : {enable_follow_gate}')
    print('============================================================\n')
    chrome_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    with sync_playwright() as pw:
        pass
    ctx = pw.chromium.launch_persistent_context(user_data_dir=str(ig_profile_dir), headless=headless, args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--start-maximized'], user_agent=chrome_ua, viewport={'width': 1366, 'height': 768})
    ctx.add_init_script('\n            Object.defineProperty(navigator,\'webdriver\',{get:()=>undefined});\n            Object.defineProperty(navigator,\'languages\',{get:()=>[\'en-US\',\'en\']});\n            Object.defineProperty(navigator,\'plugins\',{get:()=>[1,2,3,4,5]});\n            window.chrome={runtime:{}};\n        ')
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on('console', lambda msg: print(f'  [Browser Console] {msg.text}'))
    print('[Auto-DM] Navigating to https://superprofile.bio/creator/auto-dm ...')
    headers_box = {}
    def handle_request(request):
        if 'list_auto_dms' in request.url and (not headers_box):
                headers_box.update(request.headers)
                print('[Auto-DM] Captured API authorization headers.')
    page.on('request', handle_request)
    page.goto('https://superprofile.bio/creator/auto-dm', timeout=45000)
    is_logged_out = False
    try:
        if 'login' in page.url or 'auto-dm' not in page.url or page.locator('text=Welcome to SuperProfile').is_visible() or page.locator('input[placeholder*=\'Name\']').is_visible():
            is_logged_out = True
    except Exception:
        pass
    if is_logged_out:
        print('\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        print('[Auto-DM] Session expired / Logged out! Re-launching browser in VISIBLE mode so you can log in...')
        print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n')
        ctx.close()
        ctx = pw.chromium.launch_persistent_context(user_data_dir=str(ig_profile_dir), headless=False, args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--start-maximized'], user_agent=chrome_ua, viewport={'width': 1366, 'height': 768})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on('request', handle_request)
        page.goto('https://superprofile.bio/creator/auto-dm', timeout=45000)
        print('Waiting for you to log in manually in the visible browser window...')
        try:
            page.locator('#add-auto-dm, button:has-text(\'Add Auto DM\'), a:has-text(\'Add Auto DM\'), text=Add Auto DM').first.wait_for(state='visible', timeout=300000)
            print('[Auto-DM] Successfully logged in and reached the Auto DM dashboard! Continuing...')
        except Exception:
            print('[Auto-DM Error] Login timeout. Please try again.')
            ctx.close()
            return False
        start_time = time.time()
        while not headers_box and time.time() - start_time < 10:
            page.wait_for_timeout(500)
            if check_existing and headers_box:
                    is_automated = is_product_automated(headers_box, product_url)
                    if is_automated:
                        print('\n============================================================')
                        print(f'[Auto-DM] [INFO] Product \'{product_title}\' is already automated on SuperProfile.bio!')
                        print(f'URL: {product_url}')
                        print('============================================================\n')
                        ctx.close()
                        return True
                    else:
                        print('[Auto-DM] Product is not automated. Continuing with setup...')
            def click_element_with_fallback(selectors: list, element_desc: str, next_selectors_to_verify: list=None) -> bool:
                print(f"  [Auto-DM] Searching for '{element_desc}'...")
                modal_selector = '.cf-modal-content, .modal-content, .cf-modal, [class*=\"modal\"]'
                use_modal_scope = False
                try:
                    if page.locator(modal_selector).first.is_visible():
                        use_modal_scope = True
                except Exception:
                    pass

                def get_scoped_locator(sel):
                    if use_modal_scope:
                        return page.locator(modal_selector).first.locator(sel)
                    else:
                        return page.locator(sel)

                def get_scoped_text_locator(text, exact=False):
                    if use_modal_scope:
                        return page.locator(modal_selector).first.get_by_text(text, exact=exact)
                    else:
                        return page.get_by_text(text, exact=exact)

                # 1. Selector Click
                for sel in selectors:
                    try:
                        get_scoped_locator(sel).first.wait_for(state='visible', timeout=5000)
                    except Exception:
                        continue
                    else:
                        break

                for sel in selectors:
                    try:
                        locator = get_scoped_locator(sel).first
                        locator.click(timeout=3000)
                        print(f"  [Auto-DM] Successfully clicked '{element_desc}' using selector: {sel}")
                        return True
                    except Exception:
                        pass

                # 2. JS Page Search Click
                try:
                    clicked = page.evaluate('(desc) => {\n                    const modal = document.querySelector(\'.cf-modal-content, .modal-content, .cf-modal\');\n                    const root = (modal && window.getComputedStyle(modal).display !== \'none\') ? modal : document;\n                    const elements = Array.from(root.querySelectorAll(\'button, a, div, span, input[type=\"button\"], input[type=\"submit\"], [role=\"button\"]\'));\n                    const candidates = elements.filter(el => {\n                        const text = el.innerText || el.textContent || el.value || \'\';\n                        if (!text.toLowerCase().includes(desc.toLowerCase())) return false;\n                        \n                        const rect = el.getBoundingClientRect();\n                        const isVisible = rect.width > 0 && rect.height > 0 && \n                                          window.getComputedStyle(el).display !== \'none\' && \n                                          window.getComputedStyle(el).visibility !== \'hidden\';\n                        return isVisible;\n                    });\n                    \n                    if (candidates.length > 0) {\n                        // Rank candidates to prioritize actual buttons/links over text labels\n                        candidates.sort((a, b) => {\n                            const getScore = (el) => {\n                                const tag = el.tagName.toUpperCase();\n                                if (tag === \'BUTTON\' || tag === \'A\' || el.getAttribute(\'role\') === \'button\') {\n                                    return 100;\n                                }\n                                const cls = el.className || \'\';\n                                if (typeof cls === \'string\' && (cls.toLowerCase().includes(\'btn\') || cls.toLowerCase().includes(\'button\'))) {\n                                    return 50;\n                                }\n                                return 10;\n                            };\n                            return getScore(b) - getScore(a);\n                        });\n                        \n                        const target = candidates[0];\n                        target.focus();\n                        target.click();\n                        return true;\n                    }\n                    return false;\n                }', element_desc)
                    if clicked:
                        print(f"  [Auto-DM] Successfully clicked '{element_desc}' using JS page search")
                        return True
                except Exception as e:
                    print(f"  [Auto-DM Warning] JS search click failed: {e}")

                # 3. Text Search Click
                try:
                    locator = get_scoped_text_locator(element_desc, exact=False).first
                    locator.click(timeout=3000)
                    print(f"  [Auto-DM] Successfully clicked '{element_desc}' using text search")
                    return True
                except Exception:
                    pass

                # 4. Check if next state is already visible
                if next_selectors_to_verify:
                    for next_sel in next_selectors_to_verify:
                        try:
                            if page.locator(modal_selector).first.is_visible():
                                v_loc = page.locator(modal_selector).first.locator(next_sel).first
                            else:
                                v_loc = page.locator(next_sel).first
                            if v_loc.is_visible():
                                print(f"  [Auto-DM] '{element_desc}' appears already completed (next state visible).")
                                return True
                        except Exception:
                            pass

                # 5. Manual Option
                if not headless and next_selectors_to_verify:
                    print(f"\n  [Manual Action Required] Could not automatically click '{element_desc}'.")
                    print("  --> Please click it manually in the visible browser window, or perform the step to make the next screen load.")
                    print("  --> Waiting up to 60s for next screen to load...")
                    for wait_step in range(120):
                        page.wait_for_timeout(500)
                        for next_sel in next_selectors_to_verify:
                            try:
                                if page.locator(modal_selector).first.is_visible():
                                    v_loc = page.locator(modal_selector).first.locator(next_sel).first
                                else:
                                    v_loc = page.locator(next_sel).first
                                if v_loc.is_visible():
                                    print("  [Auto-DM] Next screen detected! Resuming automation...")
                                    page.wait_for_timeout(1000)
                                    return True
                            except Exception:
                                pass

                # Diagnostics on Failure
                try:
                    buttons = page.evaluate('() => {\n                    return Array.from(document.querySelectorAll(\'button, a, [role=\"button\"]\')).map(el => {\n                        return {\n                            tag: el.tagName,\n                            text: el.innerText || el.textContent || \"\",\n                            class: el.className || \"\",\n                            id: el.id || \"\",\n                            visible: el.getBoundingClientRect().width > 0\n                        };\n                    }).filter(b => b.visible && b.text.trim().length > 0);\n                }')
                    print("  [Auto-DM Diagnostics] Visible buttons/links on failure:")
                    for b in buttons[:15]:
                        print(f"    - <{b['tag']}> id='{b['id']}' class='{b['class']}' text='{b['text'].strip()}'")
                    page.screenshot(path='temp_auto_dm_failure.png')
                    print("  [Auto-DM Diagnostics] Saved failure state screenshot to temp_auto_dm_failure.png")
                except Exception as diag_err:
                    print(f"  [Auto-DM Diagnostics] Failed to run diagnostics: {diag_err}")

                raise RuntimeError(f"Could not automatically click '{element_desc}'. Element not found or timed out.")
            print('  [Auto-DM] Clicking Create Automation...')
            try:
                page.locator('button.a-dm-create-automation-btn, button:has-text(\'Create Automation\')').first.click(timeout=10000)
            except Exception:
                try:
                    page.get_by_text('Create Automation', exact=False).first.click(timeout=5000)
                except Exception as e:
                    raise RuntimeError(f'Could not click \'Create Automation\': {e}')
            page.wait_for_timeout(2000)
            print('  [Auto-DM] Waiting for channel selection modal...')
            try:
                page.wait_for_selector('.adm-cap-card--instagram, [class*=\'adm-cap-card\']', timeout=15000)
            except Exception:
                print('  [Auto-DM Warning] Channel card selector timed out. Trying anyway...')
            print('  [Auto-DM] Clicking Instagram card...')
            try:
                page.locator('.adm-cap-card--instagram').first.click(timeout=8000)
            except Exception:
                try:
                    page.get_by_text('Instagram', exact=False).first.click(timeout=5000)
                except Exception as e:
                    raise RuntimeError(f'Could not click \'Instagram card\': {e}')
            page.wait_for_timeout(2000)
            try:
                modal = page.locator('.cf-modal-content, .modal-content, [class*=\'cf-modal\']').first
                if modal.is_visible(timeout=2000):
                    next_in_modal = modal.locator('button:has-text(\'Next\')').first
                    if next_in_modal.is_visible(timeout=2000):
                        print('  [Auto-DM] Clicking Next on channel selection step...')
                        next_in_modal.click(timeout=5000)
                        page.wait_for_timeout(2000)
            except Exception:
                pass
            print('  [Auto-DM] Waiting 15 seconds for automation type options to load...')
            page.wait_for_timeout(15000)
            print('  [Auto-DM] Clicking \'Comments on your Post or Reel\'...')
            comments_clicked = False
            try:
                page.get_by_text('Comments on your Post or Reel', exact=False).first.click(timeout=10000)
                print('  [Auto-DM] Successfully clicked \'Comments on your Post or Reel\'')
                comments_clicked = True
            except Exception as e:
                print(f'  [Auto-DM Warning] Playwright Comments click failed: {e}. Trying JS click...')
            if not comments_clicked:
                clicked = page.evaluate('() => {\n                const els = Array.from(document.querySelectorAll(\'button, div, span, li, p\'));\n                const target = els.find(el => {\n                    const t = (el.innerText || el.textContent || \'\').trim();\n                    return t.toLowerCase().includes(\'comments on your post\') && el.getBoundingClientRect().width > 0;\n                });\n                if (target) { target.click(); return true; }\n                return false;\n            }')
                if clicked:
                    print('  [Auto-DM] Clicked \'Comments on your Post or Reel\' via JS')
                    comments_clicked = True
            if not comments_clicked:
                page.screenshot(path='temp_auto_dm_failure.png')
                raise RuntimeError('Could not click \'Comments on your Post or Reel\'.')
            else:
                print('  [Auto-DM] Waiting for post/reel selection step to load...')
                page.wait_for_timeout(3000)
                print('  [Auto-DM] Clicking \'Specific Post/Reel\'...')
                specific_clicked = False
                try:
                    page.get_by_text('Specific Post/Reel', exact=False).first.click(timeout=10000)
                    print('  [Auto-DM] Clicked \'Specific Post/Reel\'')
                    specific_clicked = True
                except Exception as e:
                    print(f'  [Auto-DM Warning] Playwright Specific Post/Reel click failed: {e}. Trying JS click...')
                if not specific_clicked:
                    clicked = page.evaluate('() => {\n                const els = Array.from(document.querySelectorAll(\'button, div, span, li\'));\n                const target = els.find(el => {\n                    const t = (el.innerText || el.textContent || \'\').trim();\n                    return t.toLowerCase().includes(\'specific post\') && el.getBoundingClientRect().width > 0;\n                });\n                if (target) { target.click(); return true; }\n                return false;\n            }')
                print('  [Auto-DM] Waiting up to 15s for Instagram posts to load...')
                try:
                    page.wait_for_selector('.reel-post-story-card, .post-card, [class*=\'reel-post\'], [class*=\'post-card\']', timeout=15000)
                except Exception:
                    print('  [Auto-DM Warning] Could not confirm thumbnail cards appeared. Trying anyway.')
                page.wait_for_timeout(2000)
                print('  [Auto-DM] Finding an unautomated thumbnail in the top 10...')
                clicked_successfully = False
                def is_next_enabled():
                    return page.evaluate('() => {\n                const modal = document.querySelector(\'.cf-modal-content, .modal-content, [class*=\"cf-modal\"]\');\n                if (!modal) return false;\n                const btn = Array.from(modal.querySelectorAll(\'button\')).find(b => \n                    (b.innerText || b.textContent || \'\').trim().toLowerCase() === \'next\'\n                );\n                if (!btn) return false;\n                return !btn.disabled && !btn.classList.contains(\'disabled\') && !btn.hasAttribute(\'disabled\');\n            }')
                for try_idx in range(10):
                    clicked_this = False
                    for sel in ['.reel-post-story-card', '[class*=\'reel-post-story\']', '.post-card', '[class*=\'post-card\']', '.cf-modal-content img', '.modal-content img']:
                        try:
                            loc = page.locator(sel).nth(try_idx)
                            if loc.is_visible(timeout=2000):
                                loc.click(timeout=3000)
                                page.wait_for_timeout(1000)
                                clicked_this = True
                                break
                        except Exception:
                            continue
                            if clicked_this:
                                if is_next_enabled():
                                    print(f'  [Auto-DM] Successfully selected unautomated thumbnail #{try_idx + 1}!')
                                    clicked_successfully = True
                                    print(f'  [Auto-DM] Thumbnail #{try_idx + 1} appears to be already automated (Next stays disabled). Trying next...')
                                    try:
                                        page.locator(sel).nth(try_idx).click(timeout=2000)
                                        page.wait_for_timeout(500)
                                    except Exception:
                                        pass
                                        if not clicked_successfully:
                                            print('  [Auto-DM Warning] Could not select any unautomated thumbnail in the top 10. Trying first card anyway.')
                                            try:
                                                page.locator('.reel-post-story-card, .post-card').first.click(timeout=3000)
                                            except Exception:
                                                pass
                                            print('  [Auto-DM Warning] Could not click any thumbnail. Attempting to proceed anyway.')
                                        page.wait_for_timeout(1000)
                                        print('  [Auto-DM] Clicking Next to go to Step 2...')
                                        next_clicked = False
                                        for next_sel in ['.cf-modal-content button:has-text(\'Next\'):not([disabled]):not(.disabled)', '.modal-content button:has-text(\'Next\'):not([disabled]):not(.disabled)', 'button.primary-button:has-text(\'Next\'):not([disabled]):not(.disabled)']:
                                            try:
                                                loc = page.locator(next_sel).filter(visible=True).first
                                                if loc.is_visible(timeout=3000):
                                                    loc.click(timeout=5000)
                                                    print(f"  [Auto-DM] Clicked Next using: {next_sel}")
                                                    next_clicked = True
                                                    break
                                            except Exception:
                                                continue
                                                if not next_clicked:
                                                    clicked = page.evaluate('() => {\n                const modal = document.querySelector(\'.cf-modal-content, .modal-content, [class*=\"cf-modal\"]\');\n                if (!modal) return false;\n                const els = Array.from(modal.querySelectorAll(\'button\'));\n                const target = els.find(el => {\n                    const t = (el.innerText || el.textContent || \'\').trim();\n                    return t.toLowerCase() === \'next\' && \n                           el.getBoundingClientRect().width > 0 && \n                           !el.disabled && \n                           !el.classList.contains(\'disabled\') && \n                           !el.hasAttribute(\'disabled\');\n                });\n                if (target) { target.click(); return true; }\n                return false;\n            }')
                                                    if clicked:
                                                        print('  [Auto-DM] Clicked Next via JS')
                                                        next_clicked = True
                                                if not next_clicked:
                                                    page.screenshot(path='temp_auto_dm_failure.png')
                                                    raise RuntimeError('Could not click Next button after thumbnail selection.')
                                                else:
                                                    print('  [Auto-DM] Waiting for comment trigger form on Step 2 to load...')
                                                    try:
                                                        page.wait_for_selector('text=Any comment', timeout=10000)
                                                    except Exception:
                                                        pass
                                                    click_element_with_fallback(['text=any comment', 'text=Any comment', 'text=Any Comment'], 'Any comment', next_selectors_to_verify=['text=Auto-Reply to comments', 'text=auto comment', 'text=Auto comment'])
                                                    print('  [Auto-DM] Setting up Auto-Reply comment responses...')
                                                    try:
                                                        is_reply_checked = page.evaluate('() => {\n                const cb = document.querySelector(\'#add-commment-response input[type=\"checkbox\"]\');\n                return cb ? cb.checked : false;\n            }')
                                                        if not is_reply_checked:
                                                            print('  [Auto-DM] Toggling Auto-Reply comments ON...')
                                                            page.locator('#add-commment-response span.slider').click(timeout=5000)
                                                            page.wait_for_timeout(1000)
                                                        print('  [Auto-DM] Filling default comment responses...')
                                                        page.evaluate('() => {\n                const responses = [\n                    "Hey! Thanks for the comment 🙌 I just sent you the link in DM — check it out!",\n                    "Hii! Saw your comment 😊 Sliding into your DMs with the details now!",\n                    "Thanks for reaching out! I\'ve sent you a message — take a look and let me know if you have questions 💬",\n                    "Hey there! Just DM\'d you the info you were looking for ✨ Let me know if it helps!",\n                    "Got your comment! Sent you a DM with everything you need 🚀"\n                ];\n                for (let i = 1; i <= 5; i++) {\n                    const input = document.getElementById("auto-reply-" + i);\n                    if (input) {\n                        input.value = responses[i - 1];\n                        input.dispatchEvent(new Event(\'input\', { bubbles: true }));\n                        input.dispatchEvent(new Event(\'change\', { bubbles: true }));\n                    }\n                }\n            }')
                                                        page.wait_for_timeout(1000)
                                                    except Exception as toggle_err:
                                                        print(f'  [Auto-DM Warning] Failed to configure Auto-Reply comments automatically: {toggle_err}')
                                                        click_element_with_fallback(['#add-commment-response span.slider', 'text=Auto-Reply to comments on the post'], 'Auto-Reply to comments on the post')
                                                    click_element_with_fallback(['.cf-modal-content button:has-text(\'Next\')', '.modal-content button:has-text(\'Next\')', 'button.primary-button:has-text(\'Next\')', 'button:has-text(\'Next\')', 'text=Next', 'button:has-text(\'next\')'], 'Next', next_selectors_to_verify=['text=delay', 'text=Delay', 'text=Minute', 'text=minute'])
                                                    print('  [Auto-DM] Waiting for Step 3 form to load...')
                                                    try:
                                                        page.wait_for_selector('text=Set a time delay', timeout=10000)
                                                    except Exception:
                                                        pass
                                                    print('  [Auto-DM] Configuring Send Delay to 10s...')
                                                    try:
                                                        page.evaluate('() => {\n            const delayInput = document.getElementById("auto-delay");\n            if (delayInput) {\n                delayInput.value = "10";\n                delayInput.dispatchEvent(new Event("input", { bubbles: true }));\n                delayInput.dispatchEvent(new Event("change", { bubbles: true }));\n            }\n        }')
                                                        print('  [Auto-DM] Send Delay set to 10s.')
                                                    except Exception as delay_err:
                                                        print(f'  [Auto-DM Warning] Failed to configure delay: {delay_err}')
                                                    print(f'  [Auto-DM] Configuring Follow Gate (enable_follow_gate={enable_follow_gate})...')
                                                    try:
                                                        is_follow_checked = page.evaluate('() => {\n                const cb = document.querySelector(\'#auto-ask-follow input[type=\"checkbox\"]\');\n                return cb ? cb.checked : false;\n            }')
                                                        if enable_follow_gate:
                                                            if not is_follow_checked:
                                                                print('  [Auto-DM] Toggling Follow Gate ON...')
                                                                page.locator('#auto-ask-follow span.slider').click(timeout=5000)
                                                                page.wait_for_timeout(1000)
                                                        else:
                                                            if is_follow_checked:
                                                                print('  [Auto-DM] Toggling Follow Gate OFF...')
                                                                page.locator('#auto-ask-follow span.slider').click(timeout=5000)
                                                                page.wait_for_timeout(1000)
                                                    except Exception as follow_err:
                                                        print(f'  [Auto-DM Warning] Failed to configure Follow Gate: {follow_err}')
                                                        if enable_follow_gate:
                                                            click_element_with_fallback(['#auto-ask-follow span.slider', 'text=dm asking to follow you', 'text=DM asking to follow you', 'text=DM asking to follow', 'text=DM to follow'], 'DM asking to follow you', next_selectors_to_verify=['text=Add a button', 'text=Add button'])
                                                    short_name = override_keyword if override_keyword else 'fan_duster'
                                                    whatsapp_url = f'https://wa.me/919895138430?text={short_name}'
                                                    whatsapp_group_url = 'https://chat.whatsapp.com/G5y1uA1hZqyG4c3PZf4m1n'
                                                    print('  [Auto-DM] Configuring redirect buttons sequentially (B1 -> click add -> B2 -> click add -> B3)...')
                                                    print('  [Auto-DM] Filling DM content textareas...')
                                                    page.evaluate('() => {\n            const modal = Array.from(document.querySelectorAll(\'.cf-modal-content, .modal-content, [class*=\"cf-modal\"]\'))\n                .find(el => el.getBoundingClientRect().width > 0);\n            const root = modal || document;\n            const textareas = Array.from(root.querySelectorAll(\'textarea\'));\n            textareas.forEach(ta => {\n                ta.focus();\n                const nativeValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, \'value\').set;\n                if (nativeValueSetter) {\n                    nativeValueSetter.call(ta, \"Hi! Thank you for commenting. Please use the buttons below to order or find details:\");\n                } else {\n                    ta.value = \"Hi! Thank you for commenting. Please use the buttons below to order or find details:\";\n                }\n                ta.dispatchEvent(new Event(\'input\', { bubbles: true }));\n                ta.dispatchEvent(new Event(\'change\', { bubbles: true }));\n            });\n        }')
                                                    page.wait_for_timeout(1000)
                                                    def fill_button_inputs(btn_idx, btn_text, btn_link):
                                                        print(f'  [Auto-DM] Configuring Button #{btn_idx + 1} (\'{btn_text}\' -> {btn_link})...')
                                                        success = page.evaluate('([idx, textVal, linkVal]) => {\n                const modal = Array.from(document.querySelectorAll(\'.cf-modal-content, .modal-content, [class*=\"cf-modal\"]\'))\n                    .find(el => el.getBoundingClientRect().width > 0);\n                const root = modal || document;\n                \n                const fillInput = (el, val) => {\n                    if (!el) return;\n                    el.focus();\n                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, \'value\').set;\n                    if (nativeInputValueSetter) {\n                        nativeInputValueSetter.call(el, val);\n                    } else {\n                        el.value = val;\n                    }\n                    el.dispatchEvent(new Event(\'input\', { bubbles: true }));\n                    el.dispatchEvent(new Event(\'change\', { bubbles: true }));\n                };\n\n                const textLikeInputs = Array.from(root.querySelectorAll(\'input\')).filter(i => {\n                    const rect = i.getBoundingClientRect();\n                    const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(i).display !== \'none\';\n                    if (!isVisible) return false;\n                    const type = (i.getAttribute(\'type\') || \'text\').toLowerCase();\n                    return [\'text\', \'url\'].includes(type) && !i.placeholder.toLowerCase().includes(\'search\');\n                });\n\n                // Button text inputs are at even indexes, links are at odd indexes\n                const textEl = textLikeInputs[idx * 2];\n                const linkEl = textLikeInputs[idx * 2 + 1];\n\n                if (textEl && linkEl) {\n                    fillInput(textEl, textVal);\n                    fillInput(linkEl, linkVal);\n                    return true;\n                }\n                return false;\n            }', [btn_idx, btn_text, btn_link])
                                                        return success
                                                    def click_add_button():
                                                        print('  [Auto-DM] Clicking \'+ Add another button\'...')
                                                        clicked = page.evaluate('() => {\n                const modal = Array.from(document.querySelectorAll(\'.cf-modal-content, .modal-content, [class*=\"cf-modal\"]\'))\n                    .find(el => el.getBoundingClientRect().width > 0);\n                const root = modal || document;\n                const addBtns = Array.from(root.querySelectorAll(\'button, span, div\')).filter(b => {\n                    const t = (b.innerText || b.textContent || \'\').toLowerCase();\n                    return (t.includes(\'add button\') || t.includes(\'another button\') || t.includes(\'+ add\')) && b.getBoundingClientRect().width > 0;\n                });\n                if (addBtns.length > 0) {\n                    addBtns[0].click();\n                    return true;\n                }\n                return false;\n            }')
                                                        return clicked
                                                    fill_button_inputs(0, 'order through whatsapp', whatsapp_url)
                                                    page.wait_for_timeout(1000)
                                                    if click_add_button():
                                                        page.wait_for_timeout(1500)
                                                        fill_button_inputs(1, 'product site', product_url)
                                                        page.wait_for_timeout(1000)
                                                    if click_add_button():
                                                        page.wait_for_timeout(1500)
                                                        fill_button_inputs(2, 'join our whatsapp group', whatsapp_group_url)
                                                        page.wait_for_timeout(1000)
                                                    print('  [Auto-DM] Clicking Next to final launch/confirm step...')
                                                    for next_sel in ['button:has-text(\'Next\')', 'text=Next', '.cf-modal-content button:has-text(\'Next\')', '.modal-content button:has-text(\'Next\')']:
                                                        try:
                                                            loc = page.locator(next_sel).filter(visible=True).first
                                                            if loc.is_visible(timeout=3000):
                                                                loc.click(timeout=5000)
                                                                print(f"  [Auto-DM] Clicked Next using: {next_sel}")
                                                                next_clicked = True
                                                                break
                                                        except Exception:
                                                            continue
                                                        if not next_clicked:
                                                            clicked = page.evaluate('() => {\n                const els = Array.from(document.querySelectorAll(\'button\'));\n                const target = els.find(el => {\n                    const t = (el.innerText || el.textContent || \'\').trim();\n                    return t.toLowerCase() === \'next\' && el.getBoundingClientRect().width > 0;\n                });\n                if (target) { target.click(); return true; }\n                return false;\n            }')
                                                            if clicked:
                                                                print('  [Auto-DM] Clicked Next via JS')
                                                                next_clicked = True
                                                        if not next_clicked:
                                                            page.screenshot(path='temp_auto_dm_failure.png')
                                                            raise RuntimeError('Could not click Next button to go to final step.')
                                                        else:
                                                            print('  [Auto-DM] Waiting for final step to settle...')
                                                            page.wait_for_timeout(4000)
                                                            confirm_screenshot = 'temp_auto_dm_confirm_step.png'
                                                            try:
                                                                page.screenshot(path=confirm_screenshot)
                                                                print(f'  [Auto-DM] Saved screenshot of final step to {confirm_screenshot}')
                                                            except Exception as e:
                                                                print(f'  [Auto-DM Warning] Failed to save screenshot: {e}')
                                                            try:
                                                                visible_buttons = page.evaluate('() => {\n                return Array.from(document.querySelectorAll(\'button, a, [role=\"button\"]\')).map(el => {\n                    return {\n                        tag: el.tagName,\n                        text: (el.innerText || el.textContent || \"\").trim(),\n                        visible: el.getBoundingClientRect().width > 0,\n                        disabled: el.disabled || el.hasAttribute(\'disabled\')\n                    };\n                }).filter(b => b.visible);\n            }')
                                                                print('  [Auto-DM Diagnostics] Final step visible buttons:')
                                                                for b in visible_buttons:
                                                                    print(f"    - <{b['tag']}> text=\'{b['text']}\' disabled={b['disabled']}")
                                                            except Exception as diag_err:
                                                                print(f'  [Auto-DM Diagnostics] Failed to list buttons: {diag_err}')
                                                            print('  [Auto-DM] Clicking Confirm and launch button...')
                                                            launched = False
                                                            for confirm_text in ['Confirm and launch', 'Confirm & launch', 'Launch automation', 'Confirm', 'Launch', 'Save']:
                                                                try:
                                                                    loc = page.get_by_text(confirm_text, exact=False).filter(visible=True).first
                                                                    if loc.is_visible(timeout=3000):
                                                                        loc.click(timeout=5000)
                                                                        print(f"  [Auto-DM] Clicked launch button using text: '{confirm_text}'")
                                                                        launched = True
                                                                        break
                                                                except Exception:
                                                                    continue
                                                                if not launched:
                                                                    launched = page.evaluate('() => {\n                const els = Array.from(document.querySelectorAll(\'button, a, [role=\"button\"]\'));\n                const target = els.find(el => {\n                    const t = (el.innerText || el.textContent || \'\').trim().toLowerCase();\n                    return (t.includes(\'confirm\') || t.includes(\'launch\') || t.includes(\'save\')) && el.getBoundingClientRect().width > 0;\n                });\n                if (target) { target.click(); return true; }\n                return false;\n            }')
                                                                    if launched:
                                                                        print('  [Auto-DM] Clicked launch button via JS fallback')
                                                                if not launched:
                                                                    try:
                                                                        page.locator('.cf-modal-content button.primary-button, .modal-content button.primary-button, button.primary-button').filter(visible=True).first.click(timeout=5000)
                                                                        print('  [Auto-DM] Clicked primary button as last resort for launch')
                                                                        launched = True
                                                                    except Exception:
                                                                        pass
                                                                print('\n[Auto-DM] Waiting 5 seconds for final launch request to process and complete...')
                                                                page.wait_for_timeout(5000)
                                                                post_launch_screenshot = 'temp_auto_dm_post_launch.png'
                                                                try:
                                                                    page.screenshot(path=post_launch_screenshot)
                                                                    print(f'  [Auto-DM] Saved post-launch screenshot to {post_launch_screenshot}')
                                                                except Exception:
                                                                    pass
                                                                print('\n[Auto-DM] Automation script execution complete!')
                                                                page.wait_for_timeout(2000)
                                                                ctx.close()
                print('[Auto-DM] Browser session finished.\n')
                return True
def run_pythonanywhere_automation(product_url: str, product_title: str, product_image_url: str=None, override_keyword: str=None, force_post_idx: int=None):
    """\n    Automate setting up Auto-Reply on Railway FB Bot for the product using backend REST API.\n    """
    import re
    from urllib.parse import urlparse
    import requests
    FB_BOT_URL = 'https://whatsappbot-production-d81c.up.railway.app/fb'
    parsed = urlparse(product_url)
    product_handle = parsed.path.split('/')[(-1)] if '/' in parsed.path else ''
    if not product_handle:
        print(f'[FB Bot Error] Could not extract handle from product URL: {product_url}')
        return False
    else:
        print('\n============================================================')
        print('[FB Bot] Starting FB Bot (Railway) API automation...')
        print(f'[FB Bot] Product URL   : {product_url}')
        print(f'[FB Bot] Product Title : {product_title}')
        print(f'[FB Bot] Product Handle: {product_handle}')
        print('============================================================\n')
        short_name = ''
        if AI_CLIENTS:
            try:
                print('  [FB Bot] Asking AI to generate a clean name identifier...')
                prompt = [{'role': 'user', 'content': f'Generate a short, clean, lowercase, space-separated name (1-3 words max) representing the common name of this product.\nProduct title: \'{product_title}\'\nHandle: \'{product_handle}\'\nRemove brand names, creative/marketing adjectives, uncommon words, and model numbers.\nKeep only the most common terms describing what the product is (e.g. for \'Parteet Creative Magpad Play Toy\', return \'magnetic pad play\').\nReturn ONLY the name and nothing else.'}]
                short_name = ai_chat(prompt, max_tokens=20).strip().lower()
                short_name = re.sub('[^a-z0-9\\s]', '', short_name)
                print(f'  [FB Bot] Generated name: {short_name}')
            except Exception as e:
                print(f'  [FB Bot] AI name generation failed: {e}')
        if not short_name:
            words = re.sub('[^a-zA-Z0-9\\s]', '', product_title).lower().split()
            common = {'led', 'the', 'kids', 'automatic', 'with', 'for', 'lights', 'toy', 'operated', 'set', 'and', 'battery'}
            words = [w for w in words if w not in common] or words
            short_name = ' '.join(words[:3]) if words else 'product'
            print(f'  [FB Bot] Fallback name: {short_name}')
        if override_keyword:
            whatsapp_param = override_keyword
            print(f'  [FB Bot] Using override keyword: {whatsapp_param}')
        else:
            whatsapp_param = short_name.replace(' ', '_')
        whatsapp_url = f'https://wa.me/919895138430?text={whatsapp_param}'
        comment_reply = f'വാട്സാപ്പിൽ പ്രോഡക്റ്റ് ഓർഡർ ചെയ്യാൻ വേണ്ടി ഈ ലിങ്കിൽ ക്ലിക്ക് ചെയ്യുക 👇\n\n{whatsapp_url}\n\nസൈറ്റ് വഴി ഓർഡർ ചെയ്യാൻ 👇🏻\n{product_url}'
        try:
            print(f'[FB Bot] Checking existing automations at {FB_BOT_URL}/debug-token ...')
            debug_resp = requests.get(f'{FB_BOT_URL}/debug-token', timeout=15)
            if debug_resp.status_code == 200:
                automations = debug_resp.json().get('fb_automations', [])
                is_automated = False
                for auto in automations:
                    reply_text_check = auto.get('reply', '')
                    if product_handle in reply_text_check:
                        is_automated = True
                        break
                if is_automated:
                    print('\n============================================================')
                    print(f'[FB Bot] [INFO] Product \'{product_title}\' is already automated on FB Bot!')
                    print(f'URL: {product_url}')
                    print('============================================================\n')
                    return True
            else:
                print(f'[FB Bot Warning] Could not check existing automations (Status {debug_resp.status_code})')
        except Exception as e:
            print(f'[FB Bot Warning] Check automations failed: {e}')
        print(f'[FB Bot] Fetching posts from {FB_BOT_URL}/ui/fetch-posts ...')
        posts = []
        try:
            resp = requests.get(f'{FB_BOT_URL}/ui/fetch-posts', timeout=15)
            if resp.status_code == 200:
                posts = resp.json().get('posts', [])
                print(f'  [FB Bot] Fetched {len(posts)} posts.')
            else:
                print(f'  [FB Bot Error] Failed to fetch posts (Status {resp.status_code})')
        except Exception as e:
            print(f'  [FB Bot Error] Failed to connect to fetch-posts API: {e}')
            return False
        match_idx = 0
        if force_post_idx is not None:
            match_idx = force_post_idx
            print(f'  [FB Bot] Forced post card index: {match_idx}')
        else:
            if posts:
                match_idx = 0
        post_id = ''
        post_thumb = ''
        if posts:
            if 0 <= match_idx < len(posts):
                    post_id = posts[match_idx].get('id', '')
                    post_thumb = posts[match_idx].get('thumbnail', '')
        payload = {'name': short_name, 'reply': comment_reply, 'action': 'comment', 'dm_message': '', 'scope': 'specific', 'post_ids': [post_id] if post_id else [], 'thumbnail': post_thumb, 'keyword_type': 'any', 'keywords': [], 'active': True}
        print(f'[FB Bot] Submitting new automation rule to {FB_BOT_URL}/ui/automations ...')
        try:
            save_resp = requests.post(f'{FB_BOT_URL}/ui/automations', json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
            if save_resp.status_code == 200:
                res_data = save_resp.json()
                if res_data.get('ok'):
                    print('[FB Bot] [OK] Facebook automation created successfully!')
                    return True
                else:
                    print(f'[FB Bot] [Error] Server rejected automation: {res_data}')
            else:
                print(f'[FB Bot] [Error] Failed to submit automation (Status {save_resp.status_code})')
        except Exception as e:
            print(f'[FB Bot] [Exception] Error submitting automation: {e}')
        return False
def ai_match_reel_to_product(reels: list, product_title: str, product_description: str='') -> str | None:
    """
    Use AI to find the best-matching Instagram reel for a given Shopify product.
    Analyses reel captions (and thumbnails if available) against the product title/description.
    Returns the matched reel URL, or None if no confident match is found.
    """
    if not reels:
        return None
    try:
        reel_lines = []
        for idx, reel in enumerate(reels, 1):
            caption_preview = (reel.get('caption') or '(no caption)')[:200]
            reel_lines.append(f"  [{idx}] Caption: {caption_preview}\n       URL: {reel['url']}")
        reels_text = '\n'.join(reel_lines)
        prompt = f"You are a product-to-video matching expert for a dropshipping/e-commerce Instagram store.\n\nYour task: Given a Shopify product and a list of Instagram reels (with their captions), \nidentify which reel BEST matches the product. Be precise — only match if the reel caption \nclearly matches the product. If no reel matches, respond with: NO_MATCH\n\nProduct Title: {product_title}\nProduct Description (first 300 chars): {(product_description or '')[:300]}\n\nInstagram Reels:\n{reels_text}\n\nInstructions:\n- Respond with ONLY the reel URL of the best match (e.g., https://www.instagram.com/radikikk/reel/XXX)\n- OR respond with exactly: NO_MATCH\n- Do NOT include any explanation, just the URL or NO_MATCH.\n"
        reply = ai_chat([{'role': 'user', 'content': prompt}], max_tokens=120).strip()
        if reply == 'NO_MATCH' or 'no_match' in reply.lower():
            return None
        reel_urls = {r['url'] for r in reels}
        reply_clean = reply.rstrip('/')
        for url in reel_urls:
            if url.rstrip('/') == reply_clean or reply_clean in url:
                return url
        for url in reel_urls:
            m_reply = re.search('/reel/([\\w-]+)', reply_clean)
            m_url = re.search('/reel/([\\w-]+)', url)
            if m_reply and m_url and (m_reply.group(1) == m_url.group(1)):
                return url
        print(f"[Option10] AI returned '{reply}' but it did not match any scraped reel URL.")
    except Exception as e:
        print(f'[Option10] AI matching failed: {e}')
    return None
def run_option_10_pipeline():
    """\n    Option 10: Fully-automated pipeline\n    1. Fetch latest 5 Shopify products\n    2. Scrape latest Instagram reels from @radikikk\n    3. AI-match each product to its IG reel\n    4. If no IG video found: wait 30s, retry once\n    5. For each matched reel: check & automate SuperProfile + PythonAnywhere if not done\n    6. Run greatyt.py to upload to YouTube Shorts\n    """
    import sys
    import subprocess
    from pathlib import Path
    print('\n======================================================================')
    print('[Option 10] Fully-Automated Product Pipeline')
    print('  -> Fetch 5 latest Shopify products')
    print('  -> Scrape Instagram reels & AI-match to products')
    print('  -> Auto-run SuperProfile + PythonAnywhere automations')
    print('  -> Launch GreatYT for YouTube Shorts upload')
    print('======================================================================\n')
    follow_gate_choice = input('Enable follow gate for SuperProfile Auto-DM for all products? (y/n) [y]: ').strip().lower()
    enable_follow_gate = follow_gate_choice!= 'n'
    print('\n[Option 10] Step 1: Fetching latest 5 products from Shopify...')
    products = get_latest_products(5)
    if not products:
        print('[Option 10] No products found on Shopify. Aborting.')
        return None
    else:
        print(f'[Option 10] Found {len(products)} product(s):')
        for idx, p in enumerate(products, 1):
            print(f"  {idx}) {p['title']} (ID: {p['id']})")
        domain = get_storefront_domain()
        print('\n[Option 10] Step 2: Scraping latest Instagram reels from @radikikk...')
        def _scrape_reels_now():
            """Run Instagram reel scraping in a fresh subprocess to avoid Playwright event-loop conflicts."""
            try:
                import importlib.util
                import json as _json
                greatyt_path = Path(__file__).parent / 'greatyt.py'
                runner = f'import sys, json\nsys.path.insert(0, {repr(str(greatyt_path.parent))})\nimport importlib.util\nspec = importlib.util.spec_from_file_location(\'greatyt\', {repr(str(greatyt_path))})\nmod = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(mod)\nfrom playwright.sync_api import sync_playwright\nwith sync_playwright() as pw:\n    reels = mod.scrape_instagram_videos(pw, username=\'radikikk\', max_count=15)\nprint(\'REELS_JSON:\' + json.dumps(reels, ensure_ascii=False))\n'
                result = subprocess.run([sys.executable, '-c', runner], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, cwd=str(Path(__file__).parent))
                for line in result.stdout.splitlines():
                    if line.startswith('REELS_JSON:'):
                        reels = _json.loads(line[len('REELS_JSON:'):])
                        return reels
                if result.returncode!= 0 or result.stderr:
                    print(f'  [Option 10] Scraper subprocess stderr: {result.stderr[:300]}')
                return []
            except subprocess.TimeoutExpired:
                print('  [Option 10] Instagram scraping timed out (180s).')
                return []
            except Exception as e:
                print(f'  [Option 10] Error in scrape subprocess: {e}')
                return []
        reels = _scrape_reels_now()
        print(f'[Option 10] Scraped {len(reels)} reel(s) from Instagram.')
        uploaded_cache_file = Path(__file__).parent / 'uploaded_shorts.json'
        uploaded_cache = {}
        if uploaded_cache_file.exists():
            try:
                with open(uploaded_cache_file, 'r', encoding='utf-8') as f:
                    uploaded_cache = json.load(f)
            except Exception:
                pass
        print(f'[Option 10] YouTube upload cache has {len(uploaded_cache)} entries.')
        print('\n[Option 10] Step 3: AI-matching products to Instagram reels...')
        print('------------------------------------------------------------')
        products_needing_yt_upload = []
        for prod_idx, prod in enumerate(products, 1):
            title = prod['title']
            handle = prod['handle']
            product_id = prod['id']
            body_html = prod.get('body_html', '')
            product_image_url = prod.get('image_url')
            product_url = f'https://{domain}/products/{handle}'
            print(f'\n[Option 10] --- Product {prod_idx}/{len(products)}: \'{title}\' ---')
            print(f'  Shopify URL : {product_url}')
            print(f"  Product Img : {product_image_url or 'N/A'}")
            matched_reel_url = ai_match_reel_to_product(reels, title, body_html)
            if matched_reel_url is None:
                print(f'  [Option 10] No matching Instagram reel found for \'{title}\'.')
                print('  [Option 10] Waiting 30 seconds and re-scraping Instagram...')
                time.sleep(30)
                print('  [Option 10] Re-scraping Instagram reels (retry)...')
                reels_retry = _scrape_reels_now()
                if reels_retry:
                    existing_urls = {r['url'] for r in reels}
                    for r in reels_retry:
                        if r['url'] not in existing_urls:
                            reels.append(r)
                            existing_urls.add(r['url'])
                    print(f'  [Option 10] After retry: {len(reels)} total reel(s).')
                    matched_reel_url = ai_match_reel_to_product(reels, title, body_html)
                if matched_reel_url is None:
                    print(f'  [Option 10] Still no matching reel found for \'{title}\'. Skipping IG video check for this product.')
                else:
                    print(f'  [Option 10] Reel found on retry: {matched_reel_url}')
            else:
                print(f'  [Option 10] Matched reel: {matched_reel_url}')
            if matched_reel_url:
                norm_url = matched_reel_url.rstrip('/')
                if norm_url in uploaded_cache or matched_reel_url in uploaded_cache:
                    yt_info = uploaded_cache.get(norm_url) or uploaded_cache.get(matched_reel_url, {})
                    yt_url = yt_info.get('youtube_url', 'N/A')
                    print(f'  [Option 10] [ALREADY ON YT] IG reel already on YouTube: {yt_url}')
                else:
                    print('  [Option 10] [NEW] IG reel NOT yet uploaded to YouTube -- flagged for greatyt upload.')
                    products_needing_yt_upload.append(matched_reel_url)
            else:
                print('  [Option 10] [WARNING] No IG reel matched -- skipping YouTube status check.')
            print(f'\n  [Option 10] Checking SuperProfile automation for \'{title}\'...')
            try:
                run_superprofile_automation(product_url, title, enable_follow_gate=enable_follow_gate, check_existing=True)
            except Exception as e:
                print(f'  [Option 10] SuperProfile automation error: {e}')
            print(f'\n  [Option 10] Checking PythonAnywhere automation for \'{title}\'...')
            try:
                run_pythonanywhere_automation(product_url, title, product_image_url=product_image_url)
            except Exception as e:
                print(f'  [Option 10] PythonAnywhere automation error: {e}')
            print(f'  [Option 10] [DONE] Finished processing product: \'{title}\'')
            print('------------------------------------------------------------')
        print('\n[Option 10] Step 6: Running GreatYT (Instagram -> YouTube Shorts) automation...')
        if products_needing_yt_upload:
            print(f'  [Option 10] {len(products_needing_yt_upload)} product(s) have IG reels not yet on YouTube.')
        else:
            print('  [Option 10] All matched reels appear to already be on YouTube.')
        print('  [Option 10] Launching greatyt.py now...')
        script_path = str(Path(__file__).parent / 'greatyt.py')
        try:
            subprocess.run([sys.executable, script_path], check=True)
        except Exception as e:
            print(f'[Option 10] Error running greatyt.py: {e}')
        print('\n[Option 10] Pipeline complete!')

def run_option_11_whatsapp_bot():
    """
    Fetches latest 5 Shopify products from radikikk.shop,
    lets user select one, generates a keyword trigger with a random tracking code,
    builds a fixed Malayalam order-form WhatsApp reply, and saves the rule to the
    live WhatsApp bot on Railway via POST /api/keywords/save-rule.
    """
    import random
    import string
    import re as _re
    import json as _json

    WA_BOT_URL = 'https://radikikktok.shop'
    STORE_DOMAIN = 'radikikk.shop'
    print('\n=== [Option 11] WhatsApp Bot Keyword Automation ===')
    print(f'Store: https://{STORE_DOMAIN}')
    print(f'WhatsApp Bot: {WA_BOT_URL}')
    print('\nFetching latest 5 products from Shopify...')
    products = get_latest_products(5)
    if not products:
        print('[Error] No products found. Check Shopify credentials.')
        return None

    print('\nLatest 5 products:')
    for idx, prod in enumerate(products, 1):
        price = prod.get('price', '?')
        print(f"  {idx}) {prod['title']}  |  Price: ₹{price}  |  Handle: {prod['handle']}")

    prod_choice = input(f'\nChoose a product (1-{len(products)}): ').strip()
    if not prod_choice.isdigit() or not 1 <= int(prod_choice) <= len(products):
        print('[Error] Invalid selection.')
        return None

    chosen = products[int(prod_choice) - 1]
    title = chosen['title']
    if ' ' not in title and '-' in title:
        title = title.replace('-', ' ')
    handle = chosen['handle']
    price = chosen.get('price', '0')
    product_url = f'https://{STORE_DOMAIN}/products/{handle}'
    price_input = input(f'Price shown: ₹{price}  Press ENTER to use or type a new price: ').strip()
    if price_input:
        price = price_input

    tracking_code = ''.join(random.choices(string.digits, k=4))
    kw_slug = ''
    if AI_CLIENTS:
        try:
            print('  Asking AI to generate a clean, common identifier from product title...')
            prompt = [{'role': 'user', 'content': "Generate a short, clean, lowercase, underscore-separated identifier (1-3 words max) representing the common name of this product: '{}'.\nRemove brand names, creative/marketing adjectives, uncommon words, and model names. Keep only the most common search terms describing what the product actually is.\nCRITICAL: Never start with generic terms like 'multi', 'multi_functional', or 'super' unless it is part of the core product noun. Ensure it ends with the core identifying noun (e.g. 'duster', 'comb').\nE.g. for 'Parteet Creative Magpad Play Toy', return 'magnetic_pad_play' or 'magnetic_pad'.\nE.g. for 'Downthegreat Electric Head Lice Comb', return 'head_lice_comb'.\nReturn ONLY the identifier and nothing else.".format(title)}]
            ai_slug = ai_chat(prompt, max_tokens=20).strip().lower()
            ai_slug = _re.sub('[^a-z0-9_]', '', ai_slug.replace(' ', '_'))
            generic_prefixes = ['multi_', 'super_', 'multifunctional_', 'multipurpose_', 'multi_functional_', 'multi_purpose_']
            for prefix in generic_prefixes:
                if ai_slug.startswith(prefix) and len(ai_slug) > len(prefix):
                    ai_slug = ai_slug[len(prefix):]
            if ai_slug in ['multi', 'super', 'multifunctional', 'multipurpose', 'multi_functional', 'multi_purpose']:
                ai_slug = ''
            if ai_slug and len(ai_slug) > 2:
                kw_slug = ai_slug
                print(f'  [AI] Generated common identifier: {kw_slug}')
        except Exception as e:
            print(f'  [AI] Generation failed: {e}')

    if not kw_slug:
        raw_words = title.strip().split()
        clean_words = []
        for w in raw_words:
            cleaned = _re.sub('[^a-z0-9]', '', w.lower())
            if cleaned:
                clean_words.append(cleaned)
                if len(clean_words) == 4:
                    break
        kw_slug = '_'.join(clean_words)
        print(f'  [Fallback] Generated identifier: {kw_slug}')

    trigger_keyword = f'{kw_slug}_{tracking_code}'
    short_name = ''
    if AI_CLIENTS:
        try:
            print('  Asking AI to generate a clean, Title-Cased display name...')
            prompt = [{'role': 'user', 'content': "Generate a short, clean, Title-Cased display name (2-4 words max) for this product title: '{}'.\nCRITICAL INSTRUCTIONS:\n1. The display name MUST end with the core identifying noun describing what the product actually is (e.g. 'Ceiling Fan Cleaner', 'Lice Comb', 'Fruit Peeler').\n2. Never end with or contain only generic adjectives/prefixes like 'Multi', 'Multi-purpose', 'Multi-functional', or 'Super'.\n3. Make sure it is a complete, grammatically correct, meaningful noun phrase.\n4. E.g. for 'Multi-functional Microfiber Duster with Extension Pole', return 'Ceiling Fan Cleaner Duster' or 'Microfiber Duster'.\nReturn ONLY the display name and nothing else.".format(title)}]
            ai_name = ai_chat(prompt, max_tokens=30).strip()
            if ai_name:
                generic_prefixes = ['Multi-purpose ', 'Multi-functional ', 'Multipurpose ', 'Multifunctional ', 'Super ', 'Multi-Purpose ', 'Multi-Functional ']
                for prefix in generic_prefixes:
                    if ai_name.startswith(prefix) and len(ai_name) > len(prefix):
                        ai_name = ai_name[len(prefix):]
                if ai_name.lower() in ['multi', 'super', 'multifunctional', 'multipurpose', 'multi-purpose', 'multi-functional']:
                    ai_name = ''
            if ai_name and len(ai_name) > 3:
                short_name = ai_name
                print(f'  [AI] Generated display name: {short_name}')
        except Exception as e:
            print(f'  [AI] Display name generation failed: {e}')

    if not short_name:
        words = title.strip().split()
        short_words = words[:4]
        stop_words = {'on', 'and', 'with', 'the', 'of', 'in', 'as', 'its', 'or', 'are', 'for', 'from', 'an', 'your', 'to', 'a', 'by', 'about', 'is', 'at'}
        while short_words:
            last_w = _re.sub('[^a-z0-9]', '', short_words[-1].lower())
            if last_w in stop_words:
                short_words.pop()
            else:
                break
        short_name = ' '.join(short_words) if short_words else ' '.join(words[:3])
        print(f'  [Fallback] Generated display name: {short_name}')

    reply_text = f'{product_url}\n\n"*{short_name}*"\n\n💰 വില : ₹{price} (Shipping ഉൾപ്പെടെ) 🤗\n\n📝 ഓർഡർ ചെയ്യാൻ വേണ്ടി ഈ ഫോം ഫിൽ ചെയ്ത് അയക്കുക:\n\n👤 Name:\n🏠 Address:\n📮 Pin code:\n📞 Phone number:\n\n🚚 PAN India Shipping Available\n\n📩 Order ചെയ്യാൻ ഇപ്പോഴ് തന്നെ Message അയക്കൂ!'
    print('\n============================================================')
    print(f'Trigger keyword : {trigger_keyword}')
    print(f'Product URL     : {product_url}')
    print(f'Price           : ₹{price}')
    print('Reply preview   :')
    print('------------------------------------------------------------')
    try:
        print(reply_text)
    except UnicodeEncodeError:
        print(reply_text.encode('ascii', 'replace').decode())
    print('============================================================')

    confirm = input('\nSave this rule to WhatsApp bot? (y/n) [y]: ').strip().lower()
    if confirm == 'n':
        print('Aborted.')
        return None

    print(f'\nSaving rule to WhatsApp bot at {WA_BOT_URL}/api/keywords/save-rule ...')
    try:
        resp = requests.post(f'{WA_BOT_URL}/api/keywords/save-rule', json={'key': trigger_keyword, 'rule': reply_text}, headers={'Content-Type': 'application/json'}, timeout=15)
        data = resp.json()
        if resp.status_code == 200 and data.get('success'):
            print(f"\n[OK] Rule saved! Keyword trigger: '{trigger_keyword}'")
            print(f"     When anyone messages '{trigger_keyword}' on WhatsApp, they get the product reply.")
        else:
            print(f'[Error] Failed to save rule: {data}')
    except Exception as e:
        print(f'[Exception] Could not reach WhatsApp bot: {e}')
        print('\nManual fallback — copy and save this JSON rule yourself:')
        print(_json.dumps({'key': trigger_keyword, 'rule': reply_text}, ensure_ascii=False, indent=2))

    print('\n============================================================')
    print('=== YouTube Bot Comment Automation ===')
    print('============================================================')
    try:
        YT_BOT_URL = 'https://radikikktok.shop/yt'
        print(f'Fetching latest YouTube videos from {YT_BOT_URL}/api/videos ...')
        resp = requests.get(f'{YT_BOT_URL}/api/videos', timeout=15)
        if resp.status_code != 200:
            print(f'[Error] Failed to fetch videos from YouTube bot (status {resp.status_code}).')
        else:
            videos = resp.json()
            if not videos:
                print('No YouTube videos found.')
            else:
                print('Fetching current settings from YouTube bot...')
                status_resp = requests.get(f'{YT_BOT_URL}/api/status', timeout=10)
                if status_resp.status_code != 200:
                    print(f'[Error] Failed to get YouTube bot status (status {status_resp.status_code}).')
                else:
                    status_data = status_resp.json()
                    automated_ids = status_data.get('automated_video_ids', [])
                    video_configs = status_data.get('video_configs', {})
                    comment_reply = '📩 For Orders & Enquiries Contact us on WhatsApp: +91 9895138430 💬✨ 🌐 Visit our website: www.radikikk.shop 🛍️'
                    updated = False
                    print('\nChecking automation status for the latest 3 YouTube videos...')
                    for vid in videos[:3]:
                        vid_id = vid['id']
                        vid_title = vid['title']
                        cfg = video_configs.get(vid_id, {})
                        is_automated = vid_id in automated_ids and cfg.get('any_comment_enabled')
                        if not is_automated:
                            print(f"  --> [ACTIVATING] Automating video: '{vid_title}' (ID: {vid_id})")
                            if vid_id not in automated_ids:
                                automated_ids.append(vid_id)
                            cfg['any_comment_enabled'] = True
                            cfg['any_comment_reply'] = comment_reply
                            cfg['default_reply'] = ''
                            if 'rules' not in cfg:
                                cfg['rules'] = []
                            video_configs[vid_id] = cfg
                            updated = True
                        else:
                            print(f"  --> [ALREADY ACTIVE] Video is already automated: '{vid_title}' (ID: {vid_id})")
                    if updated:
                        print('\nSaving rules to YouTube bot...')
                        save_resp = requests.post(f'{YT_BOT_URL}/api/settings', json={'automated_video_ids': automated_ids, 'video_configs': video_configs}, headers={'Content-Type': 'application/json'}, timeout=15)
                        save_data = save_resp.json()
                        if save_resp.status_code == 200 and save_data.get('success'):
                            print('[OK] YouTube Bot rules updated successfully!')
                        else:
                            print(f'[Error] Failed to save YouTube bot rules: {save_data}')
                    else:
                        print('\n[OK] All 3 latest YouTube videos are already automated. No changes needed.')
                    
                    local_settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yt-bot', 'settings.json')
                    if os.path.exists(local_settings_path):
                        try:
                            with open(local_settings_path, 'r', encoding='utf-8') as lf:
                                local_settings = _json.load(lf)
                            local_automated = local_settings.get('automated_video_ids', [])
                            local_configs = local_settings.get('video_configs', {})
                            local_updated = False
                            for vid in videos[:3]:
                                vid_id = vid['id']
                                if vid_id not in local_automated:
                                    local_automated.append(vid_id)
                                    local_updated = True
                                cfg = local_configs.get(vid_id, {})
                                if not cfg.get('any_comment_enabled') or cfg.get('any_comment_reply') != comment_reply:
                                    cfg['any_comment_enabled'] = True
                                    cfg['any_comment_reply'] = comment_reply
                                    cfg['default_reply'] = ''
                                    if 'rules' not in cfg:
                                        cfg['rules'] = []
                                    local_configs[vid_id] = cfg
                                    local_updated = True
                            if local_updated:
                                local_settings['automated_video_ids'] = local_automated
                                local_settings['video_configs'] = local_configs
                                with open(local_settings_path, 'w', encoding='utf-8') as lf:
                                    _json.dump(local_settings, lf, indent=2)
                                print(f'[Local Sync] Successfully updated local settings.json at {local_settings_path}')
                        except Exception as le:
                            print(f'[Local Sync] Failed to update local settings.json: {le}')
    except Exception as e:
        print(f'[Exception] Error during YouTube bot automation: {e}')

    print('\n============================================================')
    print('=== FB Bot Comment Automation ===')
    print('============================================================')
    print('Automating FB Bot on Railway...')
    try:
        run_pythonanywhere_automation(product_url=product_url, product_title=title, product_image_url=chosen.get('image_url'), override_keyword=trigger_keyword, force_post_idx=0)
    except Exception as pe:
        print(f'[Exception] Error during FB bot automation: {pe}')

    print('\n============================================================')
    print('=== SuperProfile Comment Automation ===')
    print('============================================================')
    print('Automating SuperProfile (requires browser)...')
    try:
        run_superprofile_automation(product_url=product_url, product_title=title, enable_follow_gate=True, check_existing=True, override_keyword=trigger_keyword)
    except Exception as se:
        print(f'[Exception] Error during SuperProfile automation: {se}')
if __name__ == '__main__':
    print('=== Shopify Product Creator ===')
    print(f'Store: {SHOP_URL}')
    print('\n1. Enter product details manually')
    print('2. Import from a product URL (Amazon or other public site / local HTML)')
    print('3. Auto-submit mock reviews to a storefront product page URL')
    print('4. Toggle Cash on Delivery (COD) for an existing product')
    print('5. Import from URL and set up SuperProfile Auto-DM')
    print('6. Check if an existing Shopify product is automated on SuperProfile, if not set up Auto-DM')
    print('7. Check if an existing Shopify product is automated on FB Bot (Railway), if not set up Auto-Reply')
    print('8. Check and automate a Shopify product on both SuperProfile and FB Bot (Railway) (fetches 30 products)')
    print('9. Check and automate on both SuperProfile and FB Bot (Railway), then run greatyt automation')
    print('10. [AUTO] Fetch latest 5 products, AI-check IG videos, automate + upload to YouTube Shorts')
    print('11. [WHATSAPP BOT] Fetch latest 5 products, select one, add WhatsApp keyword rule (radikikk.shop)')
    choice = input('Choose option (1-11): ').strip()
    reviews = []
    cod_on = True
    if choice == '1':
        title, description, image_urls, video_urls, reviews = manual_input()
        price = input('Price: ').strip()
        compare_price = input('Compare Price: ').strip()
    elif choice in ['2', '5']:
        title, description, image_urls, video_urls, reviews, price, compare_price, cod_on = url_input()
    elif choice == '3':
        num_revs = input('How many reviews to add? [3]: ').strip()
        num_revs = int(num_revs) if num_revs.isdigit() else 3
        print('\nFetching latest 10 products from Shopify...')
        products = get_latest_products(10)
        if not products:
            print('No products found on the store.')
            exit()
        print('\nLatest 10 uploaded products:')
        for idx, prod in enumerate(products, 1):
            print(f"  {idx}) {prod['title']} (ID: {prod['id']})")
        prod_choice = input(f'\nChoose a product to add reviews to (1-{len(products)}): ').strip()
        if prod_choice.isdigit():
            if not 1 <= int(prod_choice) <= len(products):
                print('Invalid selection.')
                exit()
        chosen_prod = products[int(prod_choice) - 1]
        domain = get_storefront_domain()
        product_url = f"https://{domain}/products/{chosen_prod['handle']}"
        auto_submit_reviews(product_url, num_revs, product_title=chosen_prod['title'], product_description=chosen_prod.get('body_html'), product_image_url=chosen_prod.get('image_url'))
        exit()
    elif choice == '4':
        print('\nFetching latest 10 products from Shopify...')
        products = get_latest_products(10)
        if not products:
            print('No products found on the store.')
            exit()
        print('\nLatest 10 uploaded products:')
        for idx, prod in enumerate(products, 1):
            print(f"  {idx}) {prod['title']} (ID: {prod['id']})")
        prod_choice = input(f'\nChoose a product to toggle COD (1-{len(products)}): ').strip()
        if prod_choice.isdigit():
            if not 1 <= int(prod_choice) <= len(products):
                print('Invalid selection.')
                exit()
        chosen_prod = products[int(prod_choice) - 1]
        cod_choice = input('Turn on Cash on Delivery (COD) for this product? (y/n) [y]: ').strip().lower()
        cod_on = cod_choice != 'n'
        update_product_cod(chosen_prod['id'], cod_on)
        exit()
    elif choice == '6':
        print('\nFetching latest 5 products from Shopify...')
        products = get_latest_products(5)
        if not products:
            print('No products found on the store.')
            exit()
        print('\nLatest 5 uploaded products:')
        for idx, prod in enumerate(products, 1):
            print(f"  {idx}) {prod['title']} (ID: {prod['id']})")
        prod_choice = input('\nChoose a product to check and automate (1-5): ').strip()
        if prod_choice.isdigit():
            if not 1 <= int(prod_choice) <= len(products):
                print('Invalid selection.')
                exit()
        chosen_prod = products[int(prod_choice) - 1]
        domain = get_storefront_domain()
        product_url = f"https://{domain}/products/{chosen_prod['handle']}"
        kw_override = input('Enter WhatsApp trigger keyword (e.g. fruit_peeler_7957) or press ENTER to auto-generate: ').strip()
        follow_gate_choice = input('Do you want to enable the follow gate (ask to follow before sending DM)? (y/n) [y]: ').strip().lower()
        enable_follow_gate = follow_gate_choice != 'n'
        run_superprofile_automation(product_url, chosen_prod['title'], enable_follow_gate=enable_follow_gate, check_existing=True, override_keyword=kw_override if kw_override else None)
        exit()
    elif choice == '7':
        print('\nFetching latest 5 products from Shopify...')
        products = get_latest_products(5)
        if not products:
            print('No products found on the store.')
            exit()
        print('\nLatest 5 uploaded products:')
        for idx, prod in enumerate(products, 1):
            print(f"  {idx}) {prod['title']} (ID: {prod['id']})")
        prod_choice = input('\nChoose a product to check and automate (1-5): ').strip()
        if prod_choice.isdigit():
            if not 1 <= int(prod_choice) <= len(products):
                print('Invalid selection.')
                exit()
        chosen_prod = products[int(prod_choice) - 1]
        domain = get_storefront_domain()
        product_url = f"https://{domain}/products/{chosen_prod['handle']}"
        run_pythonanywhere_automation(product_url, chosen_prod['title'], product_image_url=chosen_prod.get('image_url'))
        exit()
    elif choice == '8':
        print('\nFetching latest 30 products from Shopify...')
        products = get_latest_products(30)
        if not products:
            print('No products found on the store.')
            exit()
        print('\nLatest 30 uploaded products:')
        for idx, prod in enumerate(products, 1):
            print(f"  {idx}) {prod['title']} (ID: {prod['id']})")
        prod_choice = input(f'\nChoose a product to check and automate (1-{len(products)}): ').strip()
        if prod_choice.isdigit():
            if not 1 <= int(prod_choice) <= len(products):
                print('Invalid selection.')
                exit()
        chosen_prod = products[int(prod_choice) - 1]
        domain = get_storefront_domain()
        product_url = f"https://{domain}/products/{chosen_prod['handle']}"
        follow_gate_choice = input('Do you want to enable the follow gate (ask to follow before sending DM) for SuperProfile? (y/n) [y]: ').strip().lower()
        enable_follow_gate = follow_gate_choice != 'n'
        print(f"\n[Option 8] Running SuperProfile automation check for '{chosen_prod['title']}'...")
        run_superprofile_automation(product_url, chosen_prod['title'], enable_follow_gate=enable_follow_gate, check_existing=True)
        print(f"\n[Option 8] Running FB Bot automation check for '{chosen_prod['title']}'...")
        run_pythonanywhere_automation(product_url, chosen_prod['title'], product_image_url=chosen_prod.get('image_url'))
        exit()
    elif choice == '9':
        print('\nFetching latest 30 products from Shopify...')
        products = get_latest_products(30)
        if not products:
            print('No products found on the store.')
            exit()
        print('\nLatest 30 uploaded products:')
        for idx, prod in enumerate(products, 1):
            print(f"  {idx}) {prod['title']} (ID: {prod['id']})")
        prod_choice = input(f'\nChoose a product to check and automate (1-{len(products)}): ').strip()
        if prod_choice.isdigit():
            if not 1 <= int(prod_choice) <= len(products):
                print('Invalid selection.')
                exit()
        chosen_prod = products[int(prod_choice) - 1]
        domain = get_storefront_domain()
        product_url = f"https://{domain}/products/{chosen_prod['handle']}"
        follow_gate_choice = input('Do you want to enable the follow gate (ask to follow before sending DM) for SuperProfile? (y/n) [y]: ').strip().lower()
        enable_follow_gate = follow_gate_choice != 'n'
        print(f"\n[Option 9] Running SuperProfile automation check for '{chosen_prod['title']}'...")
        run_superprofile_automation(product_url, chosen_prod['title'], enable_follow_gate=enable_follow_gate, check_existing=True)
        print(f"\n[Option 9] Running FB Bot automation check for '{chosen_prod['title']}'...")
        run_pythonanywhere_automation(product_url, chosen_prod['title'], product_image_url=chosen_prod.get('image_url'))
        print('\n[Option 9] Running GreatYT Instagram to YouTube Shorts Automation...')
        import subprocess
        import sys
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'greatyt.py')
        try:
            subprocess.run([sys.executable, script_path], check=True)
        except Exception as e:
            print(f'Error running greatyt.py: {e}')
        exit()
    elif choice == '10':
        run_option_10_pipeline()
        exit()
    elif choice == '11':
        run_option_11_whatsapp_bot()
        exit()
    else:
        print('Invalid choice. Exiting.')
        exit()

    # The rest is for choice == '1', '2', or '5' (Shopify creation flow)
    collection_input = input('Collection ID or Collection Name (blank if none): ').strip()
    collection_id = None
    if collection_input:
        print('Resolving collection...')
        collection_id = get_or_create_collection_id(collection_input)
    if image_urls:
        print('\nValidating images before Shopify upload...')
        validated = verify_images_with_ai(title, image_urls)
        if not validated:
            print('[Error] No valid product images. Aborting.')
            exit()
        if len(validated) != len(image_urls):
            print(f'Using {len(validated)} validated image(s) (removed {len(image_urls) - len(validated)} invalid).')
        image_urls = validated
    if os.getenv('DRY_RUN') == '1':
        print('DRY_RUN=1 set — skipping actual product creation (test mode).')
        print(f'Would create product: title={title}, images={len(image_urls)}, price={price}, compare={compare_price}')
        exit()
    created_prod = create_product(title=title, description=description, image_urls=image_urls, video_urls=video_urls, price=price, compare_price=compare_price, collection_id=collection_id, reviews=reviews, cod_on=cod_on)
    if created_prod and 'handle' in created_prod:
        domain = get_storefront_domain()
        product_url = f"https://{domain}/products/{created_prod['handle']}"
        check_live_product_page_with_ai(product_url)
        auto_rev = input('\nDo you want to add reviews to this product automatically? (y/n) [n]: ').strip().lower()
        if auto_rev == 'y':
            num_revs = input('How many reviews? [3]: ').strip()
            num_revs = int(num_revs) if num_revs.isdigit() else 3
            first_img = image_urls[0] if image_urls else None
            auto_submit_reviews(product_url, num_revs, product_title=title, product_description=description, product_image_url=first_img)
        if choice == '5':
            follow_gate_choice = input('Do you want to enable the follow gate (ask to follow before sending DM)? (y/n) [y]: ').strip().lower()
            enable_follow_gate = follow_gate_choice != 'n'
            run_superprofile_automation(product_url, title, enable_follow_gate=enable_follow_gate)