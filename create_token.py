#!/usr/bin/env python3
"""
create_token.py
Simple script to create a token.json file from an authorization code.
"""

import os
import sys

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("ERROR: Google Calendar API dependencies not installed.")
    sys.exit(1)

GOOGLE_CREDENTIALS_FILE = "credentials.json"
GOOGLE_TOKEN_FILE = "token.json"
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def create_token_from_code(auth_code):
    """Create token from authorization code."""
    
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"ERROR: {GOOGLE_CREDENTIALS_FILE} not found!")
        return False
    
    try:
        # Create flow with proper redirect URI for desktop apps
        flow = InstalledAppFlow.from_client_secrets_file(
            GOOGLE_CREDENTIALS_FILE, 
            GOOGLE_SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        
        # Exchange code for token
        flow.fetch_token(code=auth_code)
        creds = flow.credentials
        
        # Save token
        with open(GOOGLE_TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        
        print(f"✅ Success! Token saved to {GOOGLE_TOKEN_FILE}")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python create_token.py <authorization_code>")
        print("\nTo get the authorization code:")
        print("1. Visit the OAuth URL (without @ symbol)")
        print("2. Authorize the app")
        print("3. Copy the 'code=' part from the redirect URL")
        sys.exit(1)
    
    auth_code = sys.argv[1].strip()
    create_token_from_code(auth_code)
