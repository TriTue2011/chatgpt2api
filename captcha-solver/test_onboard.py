"""Test ChatGPT onboard via local API — run inside container."""
import requests, os, sys

API_KEY = os.environ.get("CAPTCHA_SOLVER_API_KEY", "change-me")
BASE = "http://localhost:8010"

# Fetch credentials from saved accounts
r = requests.get(
    f"{BASE}/v1/accounts/saved/smarthomebenbap%40gmail.com",
    headers={"Authorization": f"Bearer {API_KEY}"},
)
if r.status_code != 200:
    print(f"ERROR: {r.status_code} {r.text}")
    sys.exit(1)
acct = r.json()

# Trigger onboard
print("Triggering ChatGPT onboard...")
r = requests.post(
    f"{BASE}/v1/chatgpt/onboard",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    json={
        "profile": "chatgpt-smarthomebenbap",
        "email": acct["email"],
        "password": acct["password"],
        "totp_secret": acct.get("totp_secret", ""),
    },
)
print(r.json())
