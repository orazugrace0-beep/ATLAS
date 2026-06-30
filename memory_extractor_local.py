"""
memory_extractor_local.py — decides what's worth remembering, using the
LOCAL model (via the Brain class), so this step never leaves your machine
either. This mirrors memory_extractor.py from the cloud-only version, but
swaps the Claude Haiku call for a local Ollama call.
"""

import json

EXTRACTION_PROMPT = """You are a memory-extraction module for a personal assistant.
Given the latest user message and the assistant's reply, decide if there is any
durable fact, preference, or detail about the user worth remembering for future
conversations (e.g. their name, job, ongoing projects, preferences, recurring
people/places, commitments, things they corrected the assistant about).

Ignore one-off small talk, the weather, or anything not worth recalling weeks later.

Respond ONLY with valid JSON, no other text, in this exact format:
{"memories": ["short factual statement 1", "short factual statement 2"]}

If nothing is worth remembering, respond with:
{"memories": []}

Keep each memory short (under 20 words), written as a standalone fact like
"User's name is Sam" or "User prefers terse, no-fluff responses", not a summary
of the conversation."""


def _parse_json_response(raw: str) -> list[str]:
    raw = raw.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # local models sometimes add stray text before/after the JSON object;
    # grab the substring between the first { and last } as a fallback
    try:
        return json.loads(raw).get("memories", [])
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1]).get("memories", [])
            except json.JSONDecodeError:
                return []
        return []


def extract_memories_local(brain, user_message: str, assistant_reply: str) -> list[str]:
    from brain import EXTRACTION_OPTIONS
    try:
        text = brain.think_local(
            system_prompt=EXTRACTION_PROMPT,
            messages=[{
                "role": "user",
                "content": f"User said: {user_message}\n\nAssistant replied: {assistant_reply}",
            }],
            options=EXTRACTION_OPTIONS,
        )
        return _parse_json_response(text)
    except Exception:
        # Extraction is a nice-to-have; never let it break the main conversation
        return []
