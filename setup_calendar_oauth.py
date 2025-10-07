#!/usr/bin/env python3
"""
setup_calendar_oauth.py
Helper script to set up OAuth authentication for Google Calendar on a headless server.
This script will generate a URL that you can visit on another computer to authorize access.
"""

import os
import sys
from pathlib import Path

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print("ERROR: Google Calendar API dependencies not installed.")
    print("Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

# Configuration
GOOGLE_CREDENTIALS_FILE = "credentials.json"
GOOGLE_TOKEN_FILE = "token.json"
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def setup_oauth():
    """Set up OAuth authentication and save token."""
    
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
        print(f"ERROR: {GOOGLE_CREDENTIALS_FILE} not found!")
        print("Please download your OAuth credentials from Google Cloud Console:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. APIs & Services > Credentials")
        print("3. Create OAuth client ID (Desktop application)")
        print("4. Download as credentials.json")
        return False
    
    print("Setting up OAuth authentication...")
    
    # Create flow
    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES)
    
    # For headless setup, we'll generate a URL
    print("\n" + "="*60)
    print("OAUTH SETUP FOR HEADLESS SERVER")
    print("="*60)
    print("Since this is a headless server, we need to authorize on another computer.")
    print("\nStep 1: Visit this URL in a browser (on any computer):")
    print("-" * 60)
    
    # Get the authorization URL
    auth_url, _ = flow.authorization_url(prompt='consent')
    print(auth_url)
    print("-" * 60)
    
    print("\nStep 2: After authorizing, you'll get a code. Paste it here:")
    print("(The code will be in the URL after 'code=')")
    
    try:
        auth_code = input("\nAuthorization code: ").strip()
        
        # Exchange code for token
        flow.fetch_token(code=auth_code)
        creds = flow.credentials
        
        # Save token
        with open(GOOGLE_TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        
        print(f"\n✅ Success! Token saved to {GOOGLE_TOKEN_FILE}")
        
        # Test the connection
        print("Testing calendar access...")
        service = build('calendar', 'v3', credentials=creds)
        
        # List calendars
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        
        print(f"Found {len(calendars)} calendars:")
        for cal in calendars:
            access_role = cal.get('accessRole', 'unknown')
            summary = cal.get('summary', 'Unnamed')
            primary = " (PRIMARY)" if cal.get('primary', False) else ""
            print(f"  - {summary}{primary} [{access_role}]")
        
        # Test events
        from datetime import datetime, timedelta
        now = datetime.utcnow().isoformat() + 'Z'
        tomorrow = (datetime.utcnow() + timedelta(days=2)).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=tomorrow,
            maxResults=5,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        print(f"\nFound {len(events)} upcoming events:")
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No title')
            print(f"  - {start}: {summary}")
        
        print("\n🎉 Calendar setup complete! Your motivation dashboard should now work.")
        return True
        
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        return False
    except Exception as e:
        print(f"\n❌ Error during setup: {e}")
        return False

if __name__ == "__main__":
    setup_oauth()
