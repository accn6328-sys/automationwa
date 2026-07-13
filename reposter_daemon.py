import os
import sys
import time
import json
import base64
import requests
import subprocess
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

# Cache file path for uploaded shorts
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

def upload_youtube_short(youtube, video_path: Path, title: str, description: str, tags: list):
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
            "categoryId": "22"  # People & Blogs
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

# ─── Audio and Frame Extraction Helpers ──────────────────────────────────────
def extract_audio(video_path: Path, audio_path: Path) -> bool:
    try:
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
            str(audio_path)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception as e:
        log(f"Failed to extract audio using ffmpeg: {e}", "WARN")
        return False

def extract_keyframe(video_path: Path, timestamp_sec: float, output_path: Path) -> bool:
    try:
        cmd = [
            "ffmpeg", "-y", "-ss", str(timestamp_sec),
            "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2",
            str(output_path)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception as e:
        log(f"Failed to extract keyframe: {e}", "WARN")
        return False

def get_video_duration(video_path: Path) -> float:
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception:
        return 15.0

# ─── AI Whisper Audio Transcription (Groq) ──────────────────────────────────
def transcribe_audio_groq(audio_path: Path) -> str:
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        log("Missing GROQ_API_KEY env. Skipping audio transcription.", "WARN")
        return ""

    log("Transcribing audio via Groq Whisper...")
    try:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {groq_key}"}
        with open(audio_path, "rb") as f:
            files = {"file": (audio_path.name, f, "audio/mp3")}
            data = {"model": "whisper-large-v3"}
            resp = requests.post(url, headers=headers, files=files, data=data, timeout=30)
            if resp.status_code == 200:
                text = resp.json().get("text", "")
                log("Audio transcribed successfully!")
                return text
            else:
                log(f"Groq Whisper returned status {resp.status_code}: {resp.text}", "WARN")
    except Exception as e:
        log(f"Failed to call Groq Whisper: {e}", "WARN")
    return ""

# ─── AI Vision Frame Analysis (Gemini) ─────────────────────────────────────
def run_video_analysis_gemini(video_path: Path, duration: float, original_caption: str) -> str:
    log("Extracting keyframes for visual context...")
    t1 = max(0.5, duration * 0.25)
    t2 = max(1.0, duration * 0.60)

    f1_path = DOWNLOADS_DIR / "frame_t1.jpg"
    f2_path = DOWNLOADS_DIR / "frame_t2.jpg"

    ok1 = extract_keyframe(video_path, t1, f1_path)
    ok2 = extract_keyframe(video_path, t2, f2_path)

    base64_frames = []
    for fp in [f1_path, f2_path]:
        if fp.exists():
            try:
                with open(fp, "rb") as f:
                    base64_frames.append(base64.b64encode(f.read()).decode("utf-8"))
                fp.unlink()
            except Exception:
                pass

    if not base64_frames:
        log("No keyframe frames could be extracted.", "WARN")
        return "No keyframe images available. Analysis will default to text caption only."

    gemini_keys = []
    for k in ["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "gemini_pro_key"]:
        val = os.getenv(k)
        if val and val.strip():
            gemini_keys.append((val.strip(), k))

    clients = []
    for key, key_name in gemini_keys:
        clients.append({
            "key": key,
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "model": "gemini-2.5-flash",
            "label": f"Gemini 2.5 Flash ({key_name})"
        })

    for cfg in clients:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=cfg["key"], base_url=cfg["url"])

            content = [
                {
                    "type": "text",
                    "text": (
                        "Analyze these video keyframes. Describe the video topic, product/category shown, "
                        "what is happening in the scene, key objects visible, and overall intent.\n"
                        f"Original Instagram caption: {original_caption}"
                    )
                }
            ]
            for b64 in base64_frames:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })

            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "user", "content": content}],
                max_tokens=500,
                timeout=25
            )
            ans = resp.choices[0].message.content
            if ans:
                log(f"Vision analysis succeeded using {cfg['label']}")
                return ans.strip()
        except Exception as e:
            log(f"Vision client '{cfg['label']}' failed: {e}", "WARN")

    return "Vision AI analysis unavailable."

# ─── Metadata Synthesis (Gemini/Llama) ──────────────────────────────────────
def generate_shorts_metadata(original_caption: str, video_analysis: str, transcript: str) -> dict:
    log("Synthesizing final Shorts metadata using AI...")

    groq_keys = []
    for k in ["GROQ_API_KEY", "GROQ_API_KEY_ALT", "GROQ_API_KEY_ALT2"]:
        val = os.getenv(k)
        if val and val.strip():
            groq_keys.append((val.strip(), k))

    clients = []
    for key, key_name in groq_keys:
        clients.append({
            "key": key,
            "url": "https://api.groq.com/openai/v1",
            "model": "llama-3.3-70b-versatile",
            "label": f"Groq Llama 70B ({key_name})"
        })

    prompt = f"""
You are an expert social media manager.
Analyze the video details and validate the caption relevance.

Original Instagram Caption:
{original_caption}

Video Audio Transcript:
{transcript}

AI Video Scene Analysis:
{video_analysis}

Tasks:
1. Caption Validation:
   - Determine if the original caption is relevant, misleading, or incomplete compared to the actual video content.
2. Generate YouTube Shorts Metadata:
   - Title: Catchy, engaging, optimized for YouTube Shorts, maximum 100 characters. Append "#shorts" at the end of the title.
   - Description: The final caption / description content (with the hashtags and details).
   - Tags: Generate a list of comma-separated tags. Always include "shopping" first, then add 5-8 relevant tags based on the video context (e.g., gadgets, shorts, product review, viral products).

Response format:
Respond ONLY with a valid JSON object. Do not include markdown wraps (like ```json) or outer text.
The JSON object must have exactly these keys:
- "caption_status": "relevant" / "misleading" / "incomplete" / "missing"
- "validation_reason": "Brief explanation of relevance check"
- "title": "Optimized YouTube Shorts Title #shorts"
- "description": "YouTube Shorts Description content"
- "tags": ["shopping", "tag2", "tag3", ...]
"""

    for cfg in clients:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=cfg["key"], base_url=cfg["url"])

            resp = client.chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                timeout=20
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
    log("AI metadata synthesis failed. Using default metadata.", "WARN")
    return {
        "caption_status": "relevant",
        "validation_reason": "AI fallback.",
        "title": "Amazing Product Review! 😍✨ #shorts",
        "description": f"{original_caption}\n\n#shorts",
        "tags": ["shopping", "shorts", "viralproducts", "gadgets"]
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

        # Step 3: Extract Audio & Visuals
        audio_path = DOWNLOADS_DIR / f"{ig_id}.mp3"
        duration = get_video_duration(video_path)

        transcript = ""
        if extract_audio(video_path, audio_path):
            transcript = transcribe_audio_groq(audio_path)
            # Cleanup audio
            try:
                audio_path.unlink()
            except Exception:
                pass

        video_analysis = run_video_analysis_gemini(video_path, duration, caption)

        # Step 4: Generate Metadata
        metadata = generate_shorts_metadata(caption, video_analysis, transcript)
        title = metadata.get("title", "YouTube Shorts Upload")
        description = metadata.get("description", "")
        tags = metadata.get("tags", ["shorts", "shopping"])

        # Step 5: Upload to YouTube Shorts
        log(f"Uploading to YouTube Shorts with title: {title}")
        video_id = upload_youtube_short(youtube, video_path, title, description, tags)

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
