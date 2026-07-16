import os
import time
import base64
from google import genai
from google.genai import types
from google.genai.errors import APIError
from dotenv import load_dotenv

load_dotenv()

class GeminiQuotaError(Exception):
    """Raised when the Gemini API quota/rate limit is exceeded."""
    pass

def find_working_key() -> str:
    candidates = [
        ("GEMINI_API_KEY_3", os.environ.get("GEMINI_API_KEY_3")),
        ("GEMINI_API_KEY_4", os.environ.get("GEMINI_API_KEY_4")),
        ("GEMINI_API_KEY_2", os.environ.get("GEMINI_API_KEY_2")),
        ("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY")),
        ("gemini_pro_key", os.environ.get("gemini_pro_key")),
    ]
    # Filter out empty keys
    candidates = [(name, val) for name, val in candidates if val]
    if not candidates:
        return ""
    
    # Try each key to see if it works for gemini-3.5-flash
    import requests
    for name, val in candidates:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={val}"
        payload = {"contents": [{"parts": [{"text": "Hello"}]}]}
        try:
            r = requests.post(url, json=payload, timeout=4)
            if r.status_code == 200:
                print(f"  [GenAI Client] Selected working key: {name}")
                return val
        except Exception:
            continue
            
    # Fallback to the first available key
    print(f"  [GenAI Client] No key passed check. Falling back to: {candidates[0][0]}")
    return candidates[0][1]

# Initialize client using the found working key
api_key = find_working_key()
client = None
if api_key:
    client = genai.Client(api_key=api_key)

def generate(contents, model: str = "gemini-3.5-flash", use_search_grounding: bool = False) -> tuple[str, list[str]]:
    """
    Generate content using the google-genai SDK.
    Supports text prompts, or a list of contents (mixing text and types.Part/images).
    Returns a tuple (text, grounding_urls) for backward compatibility.
    """
    global client
    if not client:
        current_key = find_working_key()
        if not current_key:
            raise ValueError("No valid Gemini API keys found in environment or .env.")
        client = genai.Client(api_key=current_key)

    # Bridge old dictionary-based part representation to new types.Part objects
    processed_contents = []
    if isinstance(contents, list):
        for part in contents:
            if isinstance(part, dict) and "inline_data" in part:
                mime_type = part["inline_data"]["mime_type"]
                b64_data = part["inline_data"]["data"]
                img_bytes = base64.b64decode(b64_data)
                processed_contents.append(
                    types.Part.from_bytes(
                        data=img_bytes,
                        mime_type=mime_type
                    )
                )
            elif isinstance(part, dict) and "text" in part:
                processed_contents.append(part["text"])
            else:
                processed_contents.append(part)
    else:
        processed_contents = contents

    # Configure tools/grounding if requested
    config = None
    if use_search_grounding:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=model,
                contents=processed_contents,
                config=config
            )
            text = response.text or ""
            
            grounding_urls = []
            if use_search_grounding and response.candidates and response.candidates[0].grounding_metadata:
                gm = response.candidates[0].grounding_metadata
                chunks = getattr(gm, "grounding_chunks", []) or []
                if not chunks and isinstance(gm, dict):
                    chunks = gm.get("groundingChunks", []) or gm.get("grounding_chunks", [])
                
                for chunk in chunks:
                    web = getattr(chunk, "web", None)
                    if web:
                        uri = getattr(web, "uri", "")
                        if uri:
                            grounding_urls.append(uri)
                    elif isinstance(chunk, dict) and "web" in chunk:
                        uri = chunk["web"].get("uri", "")
                        if uri:
                            grounding_urls.append(uri)
            
            return text, grounding_urls

        except APIError as e:
            status_code = getattr(e, "code", None)
            err_msg = str(e).lower()
            is_quota = (
                status_code == 429 or 
                "quota" in err_msg or 
                "exhausted" in err_msg or 
                "resource_exhausted" in err_msg
            )
            if is_quota:
                raise GeminiQuotaError(f"Gemini API daily/rate limit quota exceeded: {e}") from e
            
            if attempt < 3:
                wait_time = 2 ** attempt
                print(f"  [Gemini SDK] Transient API error {status_code or ''}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise e
        except Exception as e:
            if attempt < 3:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
            else:
                raise e

    raise RuntimeError("Gemini generation failed after retries.")
