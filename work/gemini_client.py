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

# Initialize client if key is available, else defer to function call
api_key = os.environ.get("GEMINI_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)

def generate(contents, model: str = "gemini-2.5-flash-lite") -> str:
    """
    Generate content using the google-genai SDK.
    Supports text prompts, or a list of contents (mixing text and types.Part/images).
    """
    global client
    if not client:
        current_key = os.environ.get("GEMINI_API_KEY")
        if not current_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set in environment or .env.")
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

    for attempt in range(1, 4):
        try:
            response = client.models.generate_content(
                model=model,
                contents=processed_contents
            )
            return response.text or ""
        except APIError as e:
            # Check for quota-exceeded (RESOURCE_EXHAUSTED / 429) errors
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
            
            # Exponential backoff for transient/network errors (5xx, etc.)
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
