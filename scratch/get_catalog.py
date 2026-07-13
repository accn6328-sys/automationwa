import os
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")

token = os.getenv("PAGE_ACCESS_TOKEN")
phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

if not token or not phone_id:
    print("Credentials missing.")
    exit(1)

headers = {
    "Authorization": f"Bearer {token}"
}

# Try commerce settings
url = f"https://graph.facebook.com/v19.0/{phone_id}/whatsapp_commerce_settings"
try:
    r = requests.get(url, headers=headers)
    print("Commerce Settings:", r.json())
except Exception as e:
    print("Error checking settings:", e)
