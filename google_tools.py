"""
google_tools.py — lets Jarvis actually DO things: read/create calendar
events, read/send email.

Privacy note: this is the one part of the system that is NOT local by
definition — Gmail and Google Calendar live on Google's servers, so using
them means talking to Google's API. What this module does keep private:
  - Your OAuth token is stored only in `auth/token.json` on YOUR disk.
    It is never sent anywhere except directly to Google's own servers
    (as required to authenticate), and never to Anthropic or anywhere else.
  - Scopes are kept as narrow as possible (see SCOPES below) — this app
    can read/create calendar events and read/send email, nothing more
    (it cannot delete your account, read your contacts, etc.)

One-time setup required (can't be skipped — Google requires it):
  1. Go to https://console.cloud.google.com/apis/credentials
  2. Create a project (or use an existing one)
  3. Enable "Google Calendar API" and "Gmail API" for that project
  4. Create an OAuth Client ID (type: Desktop app)
  5. Download the JSON, save it as `auth/credentials.json` in this folder
  6. Run jarvis.py once with calendar/email features and a browser window
     will pop up asking you to log in and approve access. After that,
     it's saved locally and you won't be asked again until the token expires.
"""

import os
import datetime as dt
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

AUTH_DIR = Path(__file__).parent / "auth"
TOKEN_PATH = AUTH_DIR / "token.json"
CREDENTIALS_PATH = AUTH_DIR / "credentials.json"

# Narrowest scopes that still do what we need:
# - calendar.events: create/read/update events, but NOT delete your whole calendar
# - gmail.readonly: read email
# - gmail.send: send email (does NOT allow reading+deleting at will)
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GoogleNotConfigured(Exception):
    """Raised when credentials.json hasn't been set up yet."""
    pass


def get_credentials() -> Credentials:
    AUTH_DIR.mkdir(exist_ok=True)
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
        return creds

    if not CREDENTIALS_PATH.exists():
        raise GoogleNotConfigured(
            f"Missing {CREDENTIALS_PATH}. See the setup instructions at the "
            "top of google_tools.py — you need to create a Google Cloud "
            "OAuth Desktop client and download credentials.json first."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)  # opens a browser window for one-time login
    TOKEN_PATH.write_text(creds.to_json())
    return creds


class CalendarTool:
    def __init__(self):
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = get_credentials()
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def list_upcoming_events(self, max_results: int = 10) -> list[dict]:
        service = self._get_service()
        now = dt.datetime.utcnow().isoformat() + "Z"
        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = result.get("items", [])
        return [
            {
                "summary": e.get("summary", "(no title)"),
                "start": e["start"].get("dateTime", e["start"].get("date")),
                "id": e["id"],
            }
            for e in events
        ]

    def create_event(self, summary: str, start_iso: str, end_iso: str, description: str = "") -> dict:
        """start_iso / end_iso example: '2026-07-01T14:00:00-04:00' (include timezone offset)."""
        service = self._get_service()
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso},
            "end": {"dateTime": end_iso},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        return {"id": created["id"], "link": created.get("htmlLink")}


class EmailTool:
    def __init__(self):
        self._service = None

    def _get_service(self):
        if self._service is None:
            creds = get_credentials()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def list_recent(self, max_results: int = 5, query: str = "") -> list[dict]:
        """query supports Gmail search syntax, e.g. 'is:unread', 'from:boss@company.com'."""
        service = self._get_service()
        result = (
            service.users()
            .messages()
            .list(userId="me", maxResults=max_results, q=query)
            .execute()
        )
        messages = result.get("messages", [])
        out = []
        for m in messages:
            msg = service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            out.append({
                "id": m["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", "(unknown)"),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })
        return out

    def send(self, to: str, subject: str, body: str) -> dict:
        import base64
        from email.mime.text import MIMEText

        service = self._get_service()
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"id": sent["id"]}
