# Jarvis v2 — private, local-first, voice-enabled, with calendar/email

This version runs its thinking on YOUR machine by default (via Ollama),
only talks to Claude's API when you explicitly ask it to ("outsource: ..."),
adds voice in/out, and can read/send email and manage your calendar.

## Honest privacy summary (read this first)

| Component | Where it runs | Leaves your machine? |
|---|---|---|
| Conversation (default) | Local, via Ollama | No |
| Memory storage & search | Local file on disk | No |
| Speech-to-text | Local, via faster-whisper | No |
| Text-to-speech | Local, via Windows SAPI | No |
| Outsourced messages (only when you say "outsource:") | Claude API | Yes, that one message |
| Calendar / Email | Google's servers | Yes, by necessity — Gmail/Calendar live there |

Calendar and email **cannot** be fully private because they're not stored
on your machine in the first place — Google hosts them. What this build
does keep private: your OAuth login token lives only in `auth/token.json`
on your disk, and is never sent to Anthropic or anywhere except Google's
own auth servers.

---

## Setup — Part 1: the local brain (Ollama)

**This build is tuned for modest hardware** — specifically an older
dual-core laptop CPU (e.g. Intel i5-6300U), 8GB RAM, no dedicated GPU.
If that's not your situation, see the note at the bottom of this section.

1. Download Ollama for Windows: https://ollama.com/download/windows
2. Install it, then open a terminal (PowerShell or Command Prompt) and pull the model this build is configured for:
   ```
   ollama pull llama3.2:3b
   ```
   This downloads ~2GB and fits comfortably alongside everything else
   running on an 8GB machine. Don't pull `llama3.1:8b` on this hardware —
   it technically runs, but at roughly 2-4 tokens/second on a 2-core CPU,
   meaning a short reply can take 30-90+ seconds. The 3B model replies in
   a few seconds and is the right fit here.
3. Leave Ollama running in the background (it runs as a local service after install — you don't need to keep a terminal open).

**If you ever upgrade hardware** (16GB+ RAM and/or a dedicated GPU with
6GB+ VRAM), pull `llama3.1:8b` instead and change `LOCAL_MODEL` at the top
of `brain.py` to match — you'll get meaningfully better conversation
quality at the cost of speed.

## Setup — Part 2: Python environment

```
python -m venv venv
venv\Scripts\activate
pip install ollama anthropic google-genai faster-whisper pyttsx3 sounddevice numpy google-auth-oauthlib google-api-python-client google-auth-httplib2
```

## Setup — Part 3: outsourcing to Claude (optional but recommended)

1. Get an API key from https://console.anthropic.com
2. Set it as an environment variable (PowerShell):
   ```
   setx ANTHROPIC_API_KEY "sk-ant-your-key-here"
   ```
   Close and reopen your terminal afterward for it to take effect.

You only get charged for messages you explicitly prefix with `outsource:`,
`ask claude:`, or `use claude:`. Everything else is free and local.

### Optional backup: Gemini, in case Claude is ever down

If Claude's API has an outage, is rate-limiting you, or times out at the
exact moment you outsource a message, this automatically retries with
Gemini instead of just failing — but **only** for genuine availability
problems (connection errors, rate limits, server errors). If something is
actually wrong with your request or API key, that error surfaces to you
directly instead of being silently hidden behind a fallback — you'll
always be told plainly which provider actually answered (look for
`[outsourced to claude-sonnet-4-6]` vs `[outsourced to gemini-3.5-flash]`
at the start of the reply).

This is entirely optional — skip it if you don't want a backup. Without a
`GEMINI_API_KEY` set, an outsourced message just fails normally if Claude
is unavailable, exactly like before.

To set it up:
1. Go to https://aistudio.google.com/apikey, sign in, click **Create API key**.
2. Set it as an environment variable (PowerShell):
   ```
   setx GEMINI_API_KEY "your-key-here"
   ```
   Close and reopen your terminal afterward for it to take effect.

## Setup — Part 4: Google Calendar & Gmail

This requires a one-time Google Cloud setup — there's no way around this,
Google requires every app to register:

1. Go to https://console.cloud.google.com/apis/credentials
2. Create a project (top left dropdown → New Project — name it anything, e.g. "jarvis")
3. Go to "Enable APIs and Services," search for and enable:
   - Google Calendar API
   - Gmail API
4. Go to "OAuth consent screen," choose "External," fill in just the required
   fields (app name, your email). You can leave it in "Testing" mode — you
   don't need to publish it since only you will use it.
5. Go back to "Credentials" → "Create Credentials" → "OAuth client ID" →
   Application type: **Desktop app**. Name it anything, create it.
6. Click the download icon next to your new client ID, save the file as
   `credentials.json` inside the `auth/` folder of this project.
7. The first time you ask Jarvis about your calendar or email, a browser
   window will pop open asking you to log in and approve access. After
   that, it's saved locally in `auth/token.json` and won't ask again.

## Running it

Text mode (command line):
```
python jarvis.py
```

Voice mode (command line):
```
python jarvis.py --voice
```

**Desktop window (recommended)** — a real chat window with a mic button,
instead of typing into a black command-line box:
```
python jarvis_gui.py
```
Type a message and hit Enter or click **Send**, or click the 🎤 button to
speak instead — it'll transcribe what you say, think about it, reply in
the window, and read the reply back out loud automatically. The window
never freezes while Jarvis is thinking: a status line in the top-right
corner shows "thinking…" / "listening…" / "speaking…" so you always know
what's happening, since replies take a few real seconds on this hardware,
not milliseconds.

The GUI uses the exact same brain, memory, and calendar/email code as the
command-line version above — it's just a window wrapped around the same
already-tested logic, nothing is reimplemented or behaves differently.

First run of voice mode will download the Whisper "base" model (~150MB,
one-time). After that it works fully offline.

## Things you can say

- Normal conversation — handled entirely locally.
- `"check my calendar"` / `"check my email"` — triggers the Google tools directly (fast, no model guesswork involved).
- `"outsource: <anything>"` — sends just that message to Claude API for sharper reasoning, then comes back to local mode for the next message.
- `"memories"` — see everything it's learned about you so far.
- `"exit"` — quit (or say "goodbye" in voice mode).

## Realistic expectations (tuned for your specs: i5-6300U, 8GB RAM, no GPU)

- **Local model quality:** Llama 3.2 3B is a genuinely useful conversational
  model for everyday chat, simple Q&A, and basic memory — but it is
  noticeably less sharp than an 8B model or Claude, especially on multi-step
  reasoning, nuanced writing, or anything requiring careful structured output.
  That's exactly what outsourcing is for — use `"outsource: ..."` on anything
  that needs real horsepower, and it'll go to Claude instead.
- **Speed:** expect replies in roughly 3-8 seconds on this hardware, not
  instant. The code caps output length (`num_predict: 400` in `brain.py`)
  specifically so a rambling generation can't run for a minute-plus — if you
  want longer replies and don't mind the wait, raise that number.
- **Memory extraction reliability:** smaller models are less reliable at
  clean JSON output than larger ones. `memory_extractor_local.py` has a
  defensive parser that handles a local model chatting around the JSON
  instead of just returning it, and falls back to "nothing worth
  remembering" rather than crashing if it really can't parse anything. If
  you notice it's missing things it should remember, that's the 3B model's
  ceiling showing — not a bug to chase.
- **Voice recognition quality:** Whisper "base" (the default in `voice.py`)
  is sized for this CPU specifically — "small" or "medium" would be more
  accurate but meaningfully slower to transcribe on a 2-core chip, adding
  noticeable lag before Jarvis even starts thinking. Stick with "base"
  unless you're willing to trade speed for accuracy.
- **Running voice + Ollama simultaneously:** both want CPU time. Don't be
  surprised if voice transcription briefly pauses, or feels a bit slower,
  while Ollama is mid-reply — they're sharing the same 2 cores. This isn't
  a malfunction, just a hardware ceiling.
- **Tool-calling is rule-based, not model-decided.** Calendar/email triggers
  are detected by simple phrase matching in `jarvis.py`, not by asking the
  local model to decide. This is intentional even on capable hardware, but
  doubly so here — small models are the least reliable at structured tool
  calling, so keeping this deterministic avoids it accidentally claiming to
  check your email when it didn't, or vice versa. Feel free to add more
  trigger phrases to `CALENDAR_TRIGGERS` / `EMAIL_TRIGGERS` in `jarvis.py`
  as you find ones it misses.
- **What I tested vs. what I couldn't:** every piece of pure logic in this
  project (memory search/scoring, outsource-trigger parsing, the JSON
  parsing for memory extraction, calendar/email data shaping, WAV audio
  encoding format, the CPU-tuned Ollama options actually being passed
  through, the desktop window's message/voice flows including its
  background-threading behavior and error handling, and the Claude→Gemini
  fallback decision logic including the critical case of NOT falling back
  on auth/bad-request errors) was actually run and verified during
  development, using mocked API responses and a virtual display since this
  was built in a non-Windows environment without real API keys. What I
  could *not* test directly: a real live outage or rate-limit from
  Anthropic's actual API (those don't happen on command), real Ollama
  inference speed on your exact CPU, real microphone capture, real Whisper
  transcription, real Google OAuth, and how the window visually renders on
  actual Windows — those need your actual hardware, model weights, API
  quota, Google account, and Windows' rendering engine, which don't exist
  in the environment this was built in. If something in those specific
  paths misbehaves on first run, it's most likely a setup/config issue
  (model not pulled, mic permissions, OAuth consent screen, missing key)
  rather than a logic bug.
