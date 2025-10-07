# Google Calendar Setup Guide

To enable Google Calendar integration in your motivation dashboard, you have two options:

## Option A: Service Account (Recommended for Headless Servers)
## Option B: OAuth (For Interactive Use)

Choose the method that fits your setup:

## Setup Steps (Both Methods)

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Name your project (e.g., "E-Ink Dashboard")
4. Click "Create"

### 2. Enable Google Calendar API

1. In your project dashboard, go to "APIs & Services" → "Library"
2. Search for "Google Calendar API"
3. Click on it and press "Enable"

---

## Option A: Service Account Setup (Headless Servers)

### 3A. Create Service Account

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "Service Account"
3. Name it (e.g., "eink-dashboard-service")
4. Click "Create and Continue"
5. Skip role assignment (click "Continue")
6. Click "Done"

### 4A. Generate Service Account Key

1. Click on your newly created service account
2. Go to "Keys" tab
3. Click "Add Key" → "Create new key"
4. Choose "JSON" format
5. Click "Create"
6. **Save the downloaded file as `service_account.json` in your project root**

### 5A. Share Calendar with Service Account

1. Open Google Calendar in your browser
2. Go to your calendar settings (gear icon → Settings)
3. Click on your calendar → "Share with specific people"
4. Add the service account email (found in `service_account.json` as `client_email`)
5. Give it "See all event details" permission
6. Click "Send"

---

## Option B: OAuth Setup (Interactive Use)

### 3B. Create OAuth Credentials

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

## Troubleshooting

### Service Account Issues
- **"service_account.json not found"**: Make sure the file is in your project root
- **"Access denied"**: Verify you've shared your calendar with the service account email
- **"Invalid credentials"**: Check that the service account key is valid and not expired

### OAuth Issues
- **"credentials.json not found"**: Make sure the file is in your project root
- **"Access blocked"**: Check that your email is in the test users list
- **"Invalid credentials"**: Delete `token.json` and re-authenticate
- **"Headless environment detected"**: Use service account method instead

### General Issues
- **API quota exceeded**: You have a daily limit; the app caches data to minimize API calls
- **No events showing**: Check that your calendar has events and the service account has access

## Security Notes

- Keep `service_account.json` and `credentials.json` secure
- Add them to `.gitignore` if using version control
- The app only requests read-only access to your calendar
- You can revoke access anytime in your Google Account settings

## Permissions

The app requests these permissions:
- `https://www.googleapis.com/auth/calendar.readonly` - Read your calendar events

That's it! Your motivation dashboard will now show your upcoming calendar events alongside the Japanese word of the day! 🌸
