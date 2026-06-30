"""
jarvis.py — your private personal assistant. Local by default, voice-enabled,
can read/send email and manage your calendar, and can outsource specific
messages to a cloud provider (Claude, Gemini, OpenAI, or any other you've
configured) when you ask for it.

Run modes:
    python jarvis.py            text chat, local model
    python jarvis.py --voice    voice in/out, local model

Special commands (typed or spoken):
    "memories"                       show everything it remembers about you
    "outsource: <message>"           send just this message to your default provider
    "outsource claude: <message>"    send to Claude specifically
    "outsource gemini: <message>"    send to Gemini specifically
    "outsource openai: <message>"    send to OpenAI specifically
    "check my calendar" / "emails"   trigger calendar/email tools
    "exit"                           quit
"""

import argparse
import sys

from memory_store import MemoryStore
from memory_extractor_local import extract_memories_local
from brain import Brain, strip_outsource_trigger
from google_tools import CalendarTool, EmailTool, GoogleNotConfigured

SYSTEM_PROMPT = """You are Jarvis, a helpful, sharp, slightly witty personal assistant
running locally and privately on the user's own machine. Be concise and direct.
You have long-term memory of the user across sessions — when relevant memories
are provided below, use them naturally, without explicitly saying "according to
my memory." If no memories are relevant, just have a normal conversation."""

CALENDAR_TRIGGERS = ("check my calendar", "what's on my calendar", "upcoming events", "my schedule")
EMAIL_TRIGGERS = ("check my email", "check email", "any new emails", "my inbox")


def build_system_prompt(relevant_memories: list[dict]) -> str:
    if not relevant_memories:
        return SYSTEM_PROMPT
    memory_lines = "\n".join(f"- {m['text']}" for m in relevant_memories)
    return f"{SYSTEM_PROMPT}\n\nThings you remember about this user:\n{memory_lines}"


def handle_calendar_check(calendar: CalendarTool) -> str:
    try:
        events = calendar.list_upcoming_events(max_results=5)
    except GoogleNotConfigured as e:
        return f"Calendar isn't set up yet. {e}"
    if not events:
        return "Nothing upcoming on your calendar."
    lines = [f"- {e['summary']} at {e['start']}" for e in events]
    return "Here's what's coming up:\n" + "\n".join(lines)


def handle_email_check(email: EmailTool) -> str:
    try:
        messages = email.list_recent(max_results=5, query="is:unread")
    except GoogleNotConfigured as e:
        return f"Email isn't set up yet. {e}"
    if not messages:
        return "No unread emails."
    lines = [f"- From {m['from']}: {m['subject']}" for m in messages]
    return "Unread emails:\n" + "\n".join(lines)


def process_message(
    user_input: str,
    brain: Brain,
    memory: MemoryStore,
    conversation_history: list[dict],
    calendar: CalendarTool,
    email: EmailTool,
) -> str:
    """Core turn logic, separated from I/O so it can be tested without a
    live terminal/voice loop."""
    lowered = user_input.lower()

    # Tool shortcuts bypass the model entirely for speed and reliability —
    # local 8B models are good conversationalists but not reliable tool-callers,
    # so intent detection happens here in plain Python instead.
    if any(trigger in lowered for trigger in CALENDAR_TRIGGERS):
        return handle_calendar_check(calendar)
    if any(trigger in lowered for trigger in EMAIL_TRIGGERS):
        return handle_email_check(email)

    clean_message, force_outsource, provider = strip_outsource_trigger(user_input)

    relevant = memory.search(clean_message, top_k=5)
    system_prompt = build_system_prompt(relevant)

    conversation_history.append({"role": "user", "content": clean_message})
    response = brain.respond(
        system_prompt, conversation_history, force_outsource=force_outsource, provider=provider
    )
    conversation_history.append({"role": "assistant", "content": response.text})

    if len(conversation_history) > 20:
        del conversation_history[: len(conversation_history) - 20]

    # Memory extraction also runs locally — no API call, no cost, fully private
    new_facts = extract_memories_local(brain, clean_message, response.text)
    for fact in new_facts:
        memory.add(fact, kind="fact")

    prefix = f"[outsourced to {response.model}] " if response.used_outsourcing else ""
    return prefix + response.text


def run_text_loop():
    brain = Brain()
    memory = MemoryStore()
    calendar = CalendarTool()
    email = EmailTool()
    conversation_history: list[dict] = []

    print("Jarvis is online (local model, fully private). Type 'exit' to quit.")
    print("Say 'outsource: <message>' (or 'outsource gemini: ...' / 'outsource openai: ...') to use a cloud provider.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye.")
            break
        if user_input.lower() == "memories":
            for m in memory.all():
                print(f"  [{m['kind']}] {m['text']}")
            continue

        reply = process_message(user_input, brain, memory, conversation_history, calendar, email)
        print(f"\nJarvis: {reply}\n")


def run_voice_loop():
    from voice import VoiceIO

    brain = Brain()
    memory = MemoryStore()
    calendar = CalendarTool()
    email = EmailTool()
    voice = VoiceIO()
    conversation_history: list[dict] = []

    print("Jarvis is online (voice mode, local model, fully private).")
    print("Say 'exit' or 'goodbye' to quit.\n")

    while True:
        user_input = voice.listen()
        if not user_input:
            continue
        print(f"You said: {user_input}")
        if user_input.lower().strip(".") in ("exit", "quit", "goodbye"):
            voice.speak("Goodbye.")
            break

        reply = process_message(user_input, brain, memory, conversation_history, calendar, email)
        print(f"Jarvis: {reply}\n")
        voice.speak(reply)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", action="store_true", help="Use voice in/out instead of text")
    args = parser.parse_args()

    if args.voice:
        run_voice_loop()
    else:
        run_text_loop()
