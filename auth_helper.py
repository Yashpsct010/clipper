"""
Local YouTube OAuth Helper:
Run this script on your local computer to authenticate with Google and generate token.json.
Once token.json is created, you can upload it to your Hugging Face Space.

Usage:
1. Place your client_secrets.json in this directory.
2. Run: python auth_helper.py
3. A browser window will open. Sign in with the Google Account of your YouTube channel.
4. token.json will be saved automatically.
"""

import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = Path("client_secrets.json")
TOKEN_FILE = Path("data/token.json")

def main():
    if not CLIENT_SECRETS_FILE.exists():
        alt_secrets = Path("data/client_secrets.json")
        if alt_secrets.exists():
            secrets_path = alt_secrets
        else:
            print("ERROR: client_secrets.json not found!")
            print("Please download client_secrets.json from Google Cloud Console and place it here.")
            return
    else:
        secrets_path = CLIENT_SECRETS_FILE

    print(f"Starting OAuth flow using {secrets_path}...")
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as token_out:
        token_out.write(creds.to_json())

    # Also save a copy in root directory for easy access
    with open("token.json", "w", encoding="utf-8") as token_out:
        token_out.write(creds.to_json())

    print("\nSUCCESS! token.json has been created successfully.")
    print("You can now upload token.json directly to your Hugging Face Space Settings!")

if __name__ == "__main__":
    main()
