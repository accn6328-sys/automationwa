import os
import sys
import time
import json
import requests
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Ensure console supports UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Cache file path for uploaded shorts using persistent volume if available
persistent_dir = os.getenv("PERSISTENT_DIR")
if not persistent_dir and os.path.exists("/data"):
    persistent_dir = "/data"

if persistent_dir:
    UPLOAD_CACHE_FILE = Path(persistent_dir) / "uploaded_shorts.json"
else:
    UPLOAD_CACHE_FILE = BASE_DIR / "uploaded_shorts.json"

# YouTube paths
TOKEN_FILE = BASE_DIR / "yt-bot" / "token.json"
CLIENT_SECRETS_FILE = BASE_DIR / "yt-bot" / "client_secrets.json"

def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}", flush=True)

# ─── YouTube Authentication & Client Helper ──────────────────────────────────
def initialize_google_files():
    # Seed YouTube token from environment if missing
    if not TOKEN_FILE.exists():
        yt_token_env = os.environ.get("YOUTUBE_TOKEN_JSON")
        if yt_token_env:
            try:
                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(yt_token_env)
                log("Seeded token.json from YOUTUBE_TOKEN_JSON env.")
            except Exception as e:
                log(f"Failed to seed token.json: {e}", "WARN")

    # Seed YouTube client secrets from environment if missing
    if not CLIENT_SECRETS_FILE.exists():
        client_secrets_env = os.environ.get("GOOGLE_CLIENT_SECRET_JSON")
        if client_secrets_env:
            try:
                CLIENT_SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(CLIENT_SECRETS_FILE, "w", encoding="utf-8") as f:
                    f.write(client_secrets_env)
                log("Seeded client_secrets.json from GOOGLE_CLIENT_SECRET_JSON env.")
            except Exception as e:
                log(f"Failed to seed client_secrets.json: {e}", "WARN")

def get_youtube_client():
    initialize_google_files()
    if not TOKEN_FILE.exists():
        log("No token.json found. YouTube upload will be skipped.", "WARN")
        return None

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))
    except Exception as e:
        log(f"Failed to load credentials: {e}", "WARN")
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            log("Refreshed Google OAuth token silently.")
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except Exception as e:
            log(f"Token refresh failed: {e}", "WARN")
            return None

    if not creds or not creds.valid:
        log("Google credentials are not valid.", "WARN")
        return None

    return build("youtube", "v3", credentials=creds)

def upload_youtube_short(youtube, video_path: Path, title: str, description: str, tags: list, category_id: str = "22"):
    from googleapiclient.http import MediaFileUpload

    title_str = title.strip()
    if not title_str.lower().endswith("#shorts"):
        if len(title_str) > 90:
            title_str = title_str[:90].strip()
        title_str = f"{title_str} #shorts"
    else:
        title_str = title_str[:100]

    body = {
        "snippet": {
            "title": title_str,
            "description": description,
            "tags": tags,
            "categoryId": category_id
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=1024 * 1024,
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    log("Starting upload request to YouTube Shorts...")
    response = None
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                log(f"Upload progress: {int(status.progress() * 100)}%")
        except Exception as e:
            log(f"Upload chunk failed: {e}, retrying in 5 seconds...", "WARN")
            time.sleep(5)

    video_id = response.get("id")
    log("YouTube Shorts upload completed successfully!")
    return video_id

# ─── Upload Cache Helpers ───────────────────────────────────────────────────
def load_uploaded_cache() -> dict:
    if not UPLOAD_CACHE_FILE.exists():
        return {}
    try:
        with open(UPLOAD_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_uploaded_cache(cache: dict):
    try:
        with open(UPLOAD_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log(f"Failed to save upload cache: {e}", "WARN")

# ─── AI Metadata Generation via LLM ─────────────────────────────────────────
def generate_shorts_metadata(original_caption: str) -> dict:
    log("Analyzing Instagram caption via AI to generate short title and tags...")

    # Load API keys from environment
    groq_keys = []
    for k in ["GROQ_API_KEY", "GROQ_API_KEY_ALT", "GROQ_API_KEY_ALT2"]:
        val = os.getenv(k)
        if val and val.strip():
            groq_keys.append((val.strip(), k))

    gemini_keys = []
    for k in ["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "gemini_pro_key"]:
        val = os.getenv(k)
        if val and val.strip():
            gemini_keys.append((val.strip(), k))

    clients = []
    # Try Groq Llama first (usually faster and cheaper)
    for key, key_name in groq_keys:
        clients.append({
            "key": key,
            "url": "https://api.groq.com/openai/v1",
            "model": "llama-3.3-70b-versatile",
            "label": f"Groq Llama 70B ({key_name})"
        })
    # Fallback to Gemini OpenAI compatibility layer
    for key, key_name in gemini_keys:
        clients.append({
            "key": key,
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "model": "gemini-2.5-flash",
            "label": f"Gemini 2.5 Flash ({key_name})"
        })

    prompt = f"""
You are an expert social media manager.
Analyze the following Instagram caption and generate optimized metadata for a YouTube Shorts video.

Instagram Caption:
{original_caption}

Tasks:
1. Generate Title:
   - Create a catchy, engaging title of EXACTLY 3 or 4 words that describes the product.
   - Do NOT include hashtags or symbols in these 3-4 words.
   - Append "#shorts" at the very end of the title.
2. Select Category ID:
   - Choose the best matching YouTube Video Category ID from the list below:
     "22" -> People & Blogs / General Shopping / Products
     "28" -> Science & Technology / Gadgets / Electronics
     "26" -> Howto & Style / Cleaning / Home Decor / Fashion
     "24" -> Entertainment
     "17" -> Sports
     "19" -> Travel & Events
3. Generate Tags:
   - List 5 to 8 comma-separated relevant tags.
   - The first tag MUST always be "shopping".
   - The remaining tags should be derived from the product context (e.g. gadgets, home decor, cleaning).

Response format:
Respond ONLY with a valid JSON object. Do not include markdown wraps (like ```json) or outer text.
The JSON object must have exactly these keys:
- "title": "Catchy Product Title #shorts"
- "category_id": "22"
- "tags": ["shopping", "tag2", "tag3", ...]
"""

    for cfg in clients:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=cfg["key"], base_url=cfg["url"])

            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=250,
                timeout=15
            )
            reply = resp.choices[0].message.content.strip()
            
            # Simple JSON parse attempt
            match = re.search(r"\{.*\}", reply, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                log(f"Metadata generated successfully using {cfg['label']}")
                return data
        except Exception as e:
            log(f"Text client '{cfg['label']}' failed: {e}", "WARN")

    # Fallback
    log("AI metadata generation failed. Using default metadata.", "WARN")
    return {
        "title": "Amazing New Find! 😍✨ #shorts",
        "category_id": "22",
        "tags": ["shopping", "shorts", "viralproducts"]
    }

# ─── Main Job Run ────────────────────────────────────────────────────────────
def run_reposter_job():
    access_token = os.getenv("PAGE_ACCESS_TOKEN")
    ig_user_id = os.getenv("IG_USER_ID")

    if not access_token or not ig_user_id:
        log("Missing PAGE_ACCESS_TOKEN or IG_USER_ID environment variables. Job skipped.", "WARN")
        return

    # Initialize Google client
    youtube = get_youtube_client()
    if not youtube:
        log("YouTube client initialization failed. Job skipped.", "WARN")
        return

    upload_cache = load_uploaded_cache()

    log(f"Checking for new Instagram Reels...")
    try:
        url = f"https://graph.facebook.com/v19.0/{ig_user_id}/media"
        params = {
            "fields": "id,caption,media_type,media_url,timestamp,permalink",
            "access_token": access_token
        }
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            log(f"Instagram Graph API returned error {resp.status_code}: {resp.text}", "WARN")
            return

        media_items = resp.json().get("data", [])
        reels = [item for item in media_items if item.get("media_type") == "VIDEO"]

        if not reels:
            log("No Instagram Reels found.")
            return

        # Initialize empty cache with existing Reels to prevent history flood
        if not upload_cache:
            log("Cache is empty. Initializing cache with existing Instagram Reels to prevent duplicate history uploads...")
            for r in reels:
                upload_cache[r.get("id")] = {
                    "youtube_url": "skipped_initialization",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            save_uploaded_cache(upload_cache)
            log(f"Cache successfully initialized with {len(reels)} existing Reels. Only future uploads will be processed.")
            return

        # Auto-pick the first reel not yet on YouTube
        selected = None
        for r in reels:
            ig_id = r.get("id")
            if ig_id not in upload_cache:
                selected = r
                break

        if not selected:
            log("All latest Instagram Reels are already processed.")
            return

        ig_id = selected["id"]
        media_url = selected.get("media_url")
        caption = selected.get("caption", "")

        log(f"Processing new Instagram Reel ID: {ig_id}")
        log(f"Original Caption: {caption[:100]}...")

        # Step 2: Download Reel Video File
        video_path = DOWNLOADS_DIR / f"{ig_id}.mp4"
        log("Downloading video file...")
        with requests.get(media_url, stream=True) as stream:
            stream.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in stream.iter_content(chunk_size=8192):
                    f.write(chunk)
        log("Video downloaded successfully!")

        # Step 3: Generate AI Metadata (Title, Tags, Category)
        metadata = generate_shorts_metadata(caption)
        title = metadata.get("title", "YouTube Shorts Upload")
        category_id = metadata.get("category_id", "22")
        tags = metadata.get("tags", ["shorts", "shopping"])

        # Description is set directly to the full original Instagram caption
        description = caption

        # Step 4: Upload to YouTube Shorts
        log(f"Uploading to YouTube Shorts with title: {title}")
        video_id = upload_youtube_short(youtube, video_path, title, description, tags, category_id)

        if video_id:
            yt_url = f"https://www.youtube.com/shorts/{video_id}"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Update cache
            upload_cache[ig_id] = {
                "youtube_url": yt_url,
                "video_id": video_id,
                "timestamp": now_str,
                "instagram_url": selected.get("permalink", ""),
                "metadata": metadata
            }
            save_uploaded_cache(upload_cache)
            log(f"Successfully repasted Reel to YouTube: {yt_url}")
        else:
            log("YouTube upload failed.", "WARN")

        # Cleanup video file
        try:
            video_path.unlink()
        except Exception:
            pass

    except Exception as e:
        log(f"Error executing reposter job: {e}", "WARN")

if __name__ == "__main__":
    log("🚀 Instagram-to-YouTube Auto-Reposter Daemon started.")
    # Run first check immediately on start
    run_reposter_job()

    # Enter the 15-minute polling loop
    while True:
        log("Sleeping for 15 minutes before next polling check...")
        time.sleep(900)
        run_reposter_job()
