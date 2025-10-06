# Google Calendar Setup Guide

To enable Google Calendar integration in your motivation dashboard, follow these steps:

## 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Name your project (e.g., "E-Ink Dashboard")
4. Click "Create"

## 2. Enable Google Calendar API

1. In your project dashboard, go to "APIs & Services" → "Library"
2. Search for "Google Calendar API"
3. Click on it and press "Enable"

## 3. Create OAuth Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. If prompted, configure the OAuth consent screen:
   - Choose "External" user type
   - Fill in required fields (App name, User support email, Developer email)
   - Add your email to test users
   - Save and continue through all steps
4. For Application type, choose "Desktop application"
5. Name it (e.g., "E-Ink Dashboard Client")
6. Click "Create"
7. Download the `credentials.json` file
8. **Place `credentials.json` in your project root directory**

## 4. First-Time Authentication

When you first run the motivation dashboard:

1. The script will open a web browser
2. Sign in with your Google account
3. Grant permission for the app to read your calendar
4. The script will create a `token.json` file for future use

## 5. Security Notes

- Keep `credentials.json` and `token.json` secure
- Add them to `.gitignore` if using version control
- The app only requests read-only access to your calendar
- You can revoke access anytime in your Google Account settings

## 6. Troubleshooting

- **"credentials.json not found"**: Make sure the file is in your project root
- **"Access blocked"**: Check that your email is in the test users list
- **"Invalid credentials"**: Delete `token.json` and re-authenticate
- **API quota exceeded**: You have a daily limit; the app caches data to minimize API calls

## 7. Permissions

The app requests these permissions:
- `https://www.googleapis.com/auth/calendar.readonly` - Read your calendar events

That's it! Your motivation dashboard will now show your upcoming calendar events alongside the Japanese word of the day! 🌸
