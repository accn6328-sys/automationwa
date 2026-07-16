import sys, os, re, time, socket, subprocess, base64
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

# ── Gemini API key pool ───────────────────────────────────────────────────────
_GEMINI_KEYS = [k for k in [
    os.getenv("GEMINI_API_KEY"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("gemini_pro_key"),
] if k]
_gemini_idx = [0]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Find available port ──────────────────────────────────────────────────────
def find_available_port(start_port: int = 9222) -> int:
    port = start_port
    while port < 65535:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', port)) != 0:
            s.close()
            return port
        s.close()
        port += 1
    return start_port

# ── Launch native Chrome ──────────────────────────────────────────────────────
def launch_chrome_native(profile_path: Path, start_url: str, port: int) -> bool:
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.isfile(chrome_path):
        chrome_path = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    if not os.path.isfile(chrome_path):
        return False

    print(f"  Starting Chrome natively on port {port} to load {start_url}...", flush=True)
    cmd = f'start "" "{chrome_path}" --remote-debugging-port={port} --user-data-dir="{profile_path.resolve()}" --no-first-run --no-default-browser-check "{start_url}"'
    subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


    # Wait for debug port to be available
    for _ in range(15):
        s = socket.socket()
        s.settimeout(1)
        if s.connect_ex(('127.0.0.1', port)) == 0:
            s.close()
            time.sleep(2)  # brief settle time
            return True
        s.close()
        time.sleep(1)
    return False

# ── Upload Screenshot & Type Prompt ──────────────────────────────────────────
def upload_and_send_prompt(page, screenshot_path: Path, prompt_text: str):
    print("  Checking if prompt input box is visible...", flush=True)
    selectors = [
        "#prompt-textarea",
        "div[contenteditable='true']",
        "textarea",
        "div[role='textbox']",
        "[data-placeholder]"
    ]
    
    target = None
    for attempt in range(2):
        for _ in range(15):
            try:
                u = page.url
                if "chatgpt.com" not in u and "chat.openai.com" not in u:
                    print(f"  Waiting for redirection... current: {u[:60]}", flush=True)
            except: pass
            
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible(timeout=200):
                        target = loc
                        break
                except: pass
            if target: break
            time.sleep(1)
        
        if target:
            break
            
        if attempt == 0:
            print("\n  ⚠️ Could not find the ChatGPT input box.", flush=True)
            print("  Please check the Chrome window: you might need to log in or solve a Cloudflare Turnstile.", flush=True)
            input("  Once the input box is visible in the Chrome window, press Enter here to retry...")
            print("  Retrying to locate input box...", flush=True)

    if not target:
        print("  ❌ Still could not find the prompt text box.", flush=True)
        return False

    # 1. Upload the screenshot
    print("  Uploading product page screenshot...", flush=True)
    uploaded = False
    try:
        # Find ChatGPT's file input selector
        file_input = page.locator('input[type="file"]').first
        if file_input.count() > 0:
            file_input.set_input_files(str(screenshot_path))
            uploaded = True
            print("  Screenshot uploaded via file input.", flush=True)
    except Exception as e:
        print(f"  File input upload failed: {e}. Trying drag-and-drop fallback...", flush=True)

    if not uploaded:
        # Fallback: Drag and drop emulation
        try:
            target.set_input_files(str(screenshot_path))
            uploaded = True
            print("  Screenshot uploaded via target set_input_files.", flush=True)
        except Exception as e:
            print(f"  Drag-and-drop fallback failed: {e}", flush=True)

    if not uploaded:
        print("  ❌ Failed to upload screenshot. Proceeding with text prompt only...", flush=True)
    else:
        # Give it a few seconds to process and upload the file preview
        time.sleep(4)

    # 2. Type text prompt
    print("  Focusing input box...", flush=True)
    try:
        target.click(timeout=3000)
    except:
        try: target.focus()
        except: pass
    time.sleep(1.0)

    print("  Typing prompt via native keyboard input...", flush=True)
    try:
        page.keyboard.type(prompt_text, delay=5)
        print("  Finished typing prompt.", flush=True)
        time.sleep(1)
        page.keyboard.press("Enter")
        print("  Prompt submitted.", flush=True)
        return True
    except Exception as e:
        print(f"  Native typing failed: {e}. Trying evaluation fallback...", flush=True)

    # Fallback evaluation typing
    filled = False
    try:
        target.evaluate("""(el, text) => {
            el.focus();
            if (el.isContentEditable) {
                el.innerText = '';
                document.execCommand('insertText', false, text);
            } else {
                el.value = text;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }""", prompt_text)
        filled = True
        print("  Prompt set via JS evaluation.", flush=True)
    except Exception as ex:
        print(f"  JS evaluation failed: {ex}", flush=True)

    if filled:
        time.sleep(1)
        page.keyboard.press("Enter")
        print("  Prompt submitted.", flush=True)
        return True

    print("  ❌ Failed to fill prompt field.", flush=True)
    return False

# ── Wait for stop button to hide ──────────────────────────────────────────────
def wait_for_generation(page, timeout=180):
    print(f"  Waiting {timeout} seconds (3 minutes) for image generation to complete...", flush=True)
    for elapsed in range(0, timeout, 10):
        time.sleep(10)
        print(f"  Elapsed: {elapsed}s / {timeout}s...", flush=True)
    print("  Done waiting. Moving to image detection.", flush=True)

# ── Robust image downloading ──────────────────────────────────────────────────
def download_image(page, img_url: str, fpath: Path) -> bool:
    try:
        base64_data = page.evaluate("""async (url) => {
            const resp = await fetch(url);
            const blob = await resp.blob();
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onloadend = () => resolve(reader.result);
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            });
        }""", img_url)

        if base64_data and "," in base64_data:
            import base64
            _, encoded = base64_data.split(",", 1)
            data = base64.b64decode(encoded)
            fpath.write_bytes(data)
            return True
    except Exception as e:
        print(f"  Page context fetch failed: {e}", flush=True)

    try:
        import requests
        r = requests.get(img_url, timeout=30, headers=HEADERS)
        if r.status_code == 200:
            fpath.write_bytes(r.content)
            return True
    except Exception as e:
        print(f"  Requests fallback failed: {e}", flush=True)

    return False

# ── Find image on page ────────────────────────────────────────────────────────
def locate_and_download_image(page, output_dir: Path, filename_prefix: str):
    print("  Locating generated image on page...", flush=True)
    time.sleep(5) # stabilization

    # Always take a final chat state screenshot for debugging
    final_ss = output_dir / "_debug_chatgpt_final.png"
    try:
        page.screenshot(path=str(final_ss))
        print(f"  Saved chat state screenshot: {final_ss}", flush=True)
    except Exception as e:
        print(f"  Warning: could not take final screenshot: {e}", flush=True)

    img_url = None
    for attempt in range(5):
        # Scan all images on the page from newest to oldest
        img_url = page.evaluate("""() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            // Check from bottom of page (newest message) to top
            for (let i = imgs.length - 1; i >= 0; i--) {
                const img = imgs[i];
                try {
                    const w = img.naturalWidth;
                    const h = img.naturalHeight;
                    const src = img.src || '';
                    
                    // 1. Must be loaded and have content
                    if (w > 150 && h > 150 && src) {
                        // 2. Ignore avatars and profiles
                        if (!src.includes('avatar') && !src.includes('profile')) {
                            // 3. Aspect ratio check: Reel Cover is 9:16 tall/portrait,
                            // while Amazon product screenshot is wide/landscape.
                            if (h > w) {
                                return src;
                            }
                        }
                    }
                } catch (e) {}
            }
            return null;
        }""")

        if img_url:
            break
        print(f"  Image not found yet (attempt {attempt+1}/5). Waiting 10s...", flush=True)
        time.sleep(10)

    if not img_url:
        print("  [ERROR] Could not locate the generated image on the page.", flush=True)
        return False

    fpath = Path(__file__).parent / "cover.jpg"
    
    print("  Downloading image...", flush=True)
    if download_image(page, img_url, fpath):
        # Convert to true JPEG
        try:
            from PIL import Image
            img = Image.open(fpath)
            # Convert to RGB (required for JPG) and save
            img.convert("RGB").save(fpath, "JPEG")
            print("  Converted image to true JPEG format.", flush=True)
        except Exception as e:
            print(f"  Warning: could not convert to true JPEG: {e}", flush=True)
            
        print(f"\n[OK] Saved: {fpath} ({fpath.stat().st_size // 1024} KB)", flush=True)
        try:
            os.startfile(str(fpath))
        except: pass
        return True
    else:
        print("  [ERROR] Failed to download the image file.", flush=True)
        return False


# ── Gemini Caption Generator ──────────────────────────────────────────────────
def generate_caption(screenshot_path: Path, product_url: str = "") -> str:
    """Use Gemini Vision to generate an Instagram reel caption from the product screenshot."""
    if not _GEMINI_KEYS:
        print("  [Caption] No Gemini API key found in .env — skipping caption.", flush=True)
        return ""

    print("\n[Caption] Generating Instagram caption with Gemini AI...", flush=True)

    # Encode screenshot as base64
    try:
        img_bytes = screenshot_path.read_bytes()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        mime = "image/png"
    except Exception as e:
        print(f"  [Caption] Could not read screenshot: {e}", flush=True)
        return ""

    prompt = (
        "You are a social media marketing expert. Look at this product page screenshot and write "
        "a compelling Instagram Reel caption to promote this product.\n\n"
        "Caption format rules:\n"
        "1. Start with 1-2 relevant emojis and a punchy one-line hook about the product's main benefit.\n"
        "2. Write 2-3 short body sentences describing the product's key features, who it is for, "
        "and why it is useful. Use simple, conversational English.\n"
        "3. End with a short call-to-action line like: comment \"[one relevant keyword]\" to get the link. 👇\n"
        "4. Add a blank line then 6-8 relevant small letters hashtags on a single line.\n"
        "5. Use emojis naturally throughout.\n"
        "6. Output ONLY the caption text, nothing else — no intro, no explanation."
        
    )

    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime, "data": img_b64}},
                {"text": prompt}
            ]
        }]
    }

    models = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
    base_api = "https://generativelanguage.googleapis.com/v1beta/models"
    total = len(_GEMINI_KEYS)

    for model in models:
        for attempt in range(1, 5):
            key = _GEMINI_KEYS[_gemini_idx[0] % total]
            api_url = f"{base_api}/{model}:generateContent?key={key}"
            try:
                r = requests.post(api_url, json=payload, timeout=90)
                if r.status_code == 429:
                    _gemini_idx[0] += 1
                    time.sleep(2 ** min(attempt, 4))
                    continue
                if r.status_code in (500, 503, 529):
                    time.sleep(5 * attempt)
                    continue
                if r.status_code == 404:
                    break  # try next model
                r.raise_for_status()
                caption = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                print("  [Caption] Generated successfully!", flush=True)
                return caption
            except Exception as e:
                print(f"  [Caption] Attempt {attempt} failed: {e}", flush=True)
                time.sleep(3)
        print(f"  [Caption] {model} failed, trying next model...", flush=True)

    # Fallback to Gemma 4 26B
    print("  [Caption] Trying Gemma 4 26B as fallback...", flush=True)
    gemma_model = "gemma-4-26b-a4b-it"
    for attempt in range(1, 5):
        key = _GEMINI_KEYS[_gemini_idx[0] % total]
        api_url = f"{base_api}/{gemma_model}:generateContent?key={key}"
        try:
            r = requests.post(api_url, json=payload, timeout=90)
            if r.status_code == 429:
                _gemini_idx[0] += 1
                time.sleep(2 ** min(attempt, 4))
                continue
            if r.status_code in (500, 503, 529):
                time.sleep(5 * attempt)
                continue
            r.raise_for_status()
            caption = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            print("  [Caption] Generated successfully via Gemma 4 26B!", flush=True)
            return caption
        except Exception as e:
            print(f"  [Caption] Gemma 4 Attempt {attempt} failed: {e}", flush=True)
            time.sleep(3)

    print("  [Caption] All Gemini and Gemma models failed — no caption generated.", flush=True)
    return ""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=== Instagram Reel Cover Generator (Any E-Commerce URL) ===\n", flush=True)

    # 1. Get any e-commerce URL from Command Line or Input
    url = ""
    if len(sys.argv) > 1:
        url = sys.argv[1].strip()

    if not url:
        url = input("Product URL (Amazon, Flipkart, Meesho, Myntra, Ajio, Nykaa, or any e-commerce site): ").strip()

    if not url:
        print("Error: A product URL is required.", flush=True); return

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    import urllib.parse as _uparse
    _parsed = _uparse.urlparse(url)
    _netloc = _parsed.netloc.lower().replace("www.", "")

    output_dir = Path(__file__).parent / "reel_covers"
    output_dir.mkdir(exist_ok=True)
    screenshot_path = output_dir / "temp_product_screenshot.png"

    # 2. Launch Chrome Directly on the homepage first to establish session and cookies (bypasses WAF blocks)
    homepage_url = f"{_parsed.scheme}://{_parsed.netloc}/"
    print(f"\n[1/3] Launching Chrome on homepage: {homepage_url}", flush=True)
    profile_path = Path(__file__).parent / "chatgpt_profile_lr"

    # Check if a debugging session is already running on port 9224 (e.g. started by the user helper script)
    port = 9224
    s = socket.socket()
    s.settimeout(1)
    port_active = (s.connect_ex(('127.0.0.1', port)) == 0)
    s.close()

    if port_active:
        print(f"  [Info] Connected to existing Chrome debugging session on port {port}.", flush=True)
        launched = True
    else:
        port = find_available_port(9222)
        launched = launch_chrome_native(profile_path, homepage_url, port)
        
    if not launched:
        print("  [ERROR] Could not launch Chrome natively. Please make sure Google Chrome is installed.", flush=True)
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: Install playwright: pip install playwright && playwright install chromium", flush=True)
        return

    # 3. Connect Playwright and navigate to the product page
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception as e:
            print(f"  [ERROR] Failed to connect to Chrome debugging port: {e}", flush=True)
            return

        ctx = browser.contexts[0]

        # Wait for the homepage tab to load — match by netloc so any site works
        page = None
        print(f"  Waiting for homepage tab ({_netloc}) to load...", flush=True)
        for _ in range(15):
            for p in ctx.pages:
                try:
                    u = p.url
                    if _netloc in u.lower():
                        page = p
                        break
                except: pass
            if page: break
            time.sleep(1)

        if not page:
            print("  Homepage tab not found. Opening a new tab...", flush=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(homepage_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"  Warning on page.goto(homepage): {e}", flush=True)

        print("  Waiting 5 seconds to establish session/cookies...", flush=True)
        time.sleep(5)

        print(f"  Navigating to product URL: {url}", flush=True)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"  Warning on page.goto(product): {e}", flush=True)

        print("  Waiting 12 seconds for product images to load...", flush=True)
        time.sleep(12)

        # Take screenshot of product page above the fold
        try:
            page.screenshot(path=str(screenshot_path), timeout=60000)
            print(f"  Screenshot saved: {screenshot_path}", flush=True)
        except Exception as e:
            print(f"  [WARN] Screenshot timed out, trying clip screenshot: {e}", flush=True)
            try:
                page.screenshot(path=str(screenshot_path), clip={"x": 0, "y": 0, "width": 1280, "height": 800}, timeout=60000)
                print(f"  Screenshot saved (clip): {screenshot_path}", flush=True)
            except Exception as e2:
                print(f"  [ERROR] Failed to screenshot product page: {e2}", flush=True)
                browser.close()
                return

        # 4. Navigate to ChatGPT
        print("\n[2/3] Connecting to ChatGPT...", flush=True)
        try:
            page.goto("https://chatgpt.com")
        except Exception as e:
            print(f"  Warning on page.goto(ChatGPT): {e}", flush=True)

        # Wait for tab to stabilize
        time.sleep(3)

        # Check if user is logged out (look for "Log in" or "Sign up" buttons)
        is_logged_out = False
        try:
            login_btn = page.locator("button:has-text('Log in'), a:has-text('Log in'), [data-testid*='login']").first
            if login_btn.count() > 0 and login_btn.is_visible(timeout=2000):
                is_logged_out = True
        except:
            pass
            
        if not is_logged_out:
            try:
                if page.locator("#prompt-textarea").count() == 0 and page.locator("text=Log in").first.is_visible(timeout=1000):
                    is_logged_out = True
            except:
                pass

        if is_logged_out:
            print("\n" + "!"*75, flush=True)
            print("  [WARNING] LOGIN REQUIRED: You are currently logged out of ChatGPT.", flush=True)
            print("  Please LOG IN in the Chrome window that just opened.", flush=True)
            print("!"*75 + "\n", flush=True)
            input("  Once you have completed logging in and see the ChatGPT chat input box, press Enter here...")
            time.sleep(3)

        # 5. Upload Screenshot and Send Prompt
        print("\n[3/3] Uploading screenshot and requesting image generation...", flush=True)
        prompt_text = "make a reel cover for this product for a product review in 9:16 ratio in very high quality"

        # Extract a meaningful filename prefix from the URL (works for any e-commerce site)
        fn_prefix = "reel_cover"
        try:
            import urllib.parse as _up
            _path = _up.urlparse(url).path.strip("/")
            # Try Amazon ASIN first
            _asin = re.search(r"/dp/([A-Z0-9]{10})", url)
            if _asin:
                fn_prefix = f"product_{_asin.group(1)}"
            else:
                # Use last meaningful path segment for other sites
                _slug = [s for s in _path.split("/") if s and len(s) > 2]
                if _slug:
                    fn_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", _slug[-1])[:40]
        except Exception:
            pass

        if upload_and_send_prompt(page, screenshot_path, prompt_text):
            wait_for_generation(page)
            cover_saved = locate_and_download_image(page, output_dir, fn_prefix)

            # Generate and save caption after cover image is ready
            if cover_saved:
                caption = generate_caption(screenshot_path, product_url=url)
                if caption:
                    caption_path = Path(__file__).parent / "caption.txt"
                    try:
                        caption_path.write_text(caption, encoding="utf-8")
                        print(f"\n[Caption] Saved to: {caption_path}", flush=True)
                        print("\n" + "=" * 55, flush=True)
                        print("📝 INSTAGRAM CAPTION:", flush=True)
                        print("=" * 55, flush=True)
                        print(caption, flush=True)
                        print("=" * 55, flush=True)
                        try:
                            os.startfile(str(caption_path))
                        except Exception:
                            pass
                    except Exception as e:
                        print(f"  [Caption] Could not save caption.txt: {e}", flush=True)

        
        print("\n  Done. Chrome stays open.", flush=True)

if __name__ == "__main__":
    main()
