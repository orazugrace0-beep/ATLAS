"""
brain.py — the decision-maker for WHERE a message gets thought about.

Privacy model:
  - By default, EVERYTHING is processed locally by Ollama. Nothing leaves
    your machine. This is the private path and it's what runs unless you
    say otherwise.
  - You can explicitly "outsource" a single message to a cloud API when
    you want sharper reasoning than the local model can give you. This is
    opt-in per message, not automatic — your data never leaves your
    machine unless you ask for it to, by saying something like:
        "outsource: explain the tax implications of..."
        "outsource claude: write me a detailed essay on..."
        "outsource gemini: summarize this..."
        "outsource openai: ..."
    or by using --outsource on a one-off CLI call.

Why a local model + optional outsourcing, instead of one or the other:
  - On capable hardware (16GB+ RAM, modern multi-core CPU or a GPU), an
    7-8B local model is genuinely good at conversation, memory, scheduling,
    and simple reasoning. On modest hardware (8GB RAM, older dual-core
    laptop CPU, no GPU — like this build is configured for), an 8B model
    is technically runnable but painfully slow: tens of seconds per reply.
    A 3B model is the right tradeoff there — it fits comfortably in RAM
    alongside Ollama's overhead, Whisper, and Windows itself, and replies
    in a few seconds instead of a minute. It's less sharp than an 8B or
    a cloud model, especially on multi-step reasoning — that's exactly
    what outsourcing exists for.
  - Rather than quietly degrade your experience or quietly leak data,
    this system makes the local/cloud boundary explicit and lets you
    cross it on purpose, per message.

Multi-provider outsourcing:
  - You can outsource to any provider you have an API key for. Say
    "outsource <provider>: <message>" to pick one explicitly, or just
    "outsource: <message>" to use your configured default.
  - Adding a new provider is just adding one entry to PROVIDERS below
    and a matching _think_<name>() method — nothing else in the file
    needs to change.
"""

import os
import re
from dataclasses import dataclass

import ollama

LOCAL_MODEL = "llama3.2:3b"  # sized for 8GB RAM / no GPU. Bump to "llama3.1:8b" only if you upgrade RAM/get a GPU.

# Tuned for a dual-core/4-thread CPU with 8GB RAM and no GPU. These keep
# replies from ballooning in time or memory on modest hardware:
#   num_thread: match logical core count (i5-6300U = 2 cores/4 threads)
#   num_ctx: shorter context = faster + less RAM. 2048 is enough for a
#            personal assistant's recent conversation + a few memories.
#   num_predict: hard cap on reply length so a rambling generation can't
#                run for minutes on slow hardware.
LOCAL_OPTIONS = {
    "num_thread": 4,
    "num_ctx": 2048,
    "num_predict": 400,
}

# Memory extraction is a background task that runs after EVERY message, on
# a tiny input/output. On slow CPU hardware, every second here is a second
# tacked onto every single turn — so give it a much smaller budget than a
# real conversational reply needs.
EXTRACTION_OPTIONS = {
    "num_thread": 4,
    "num_ctx": 512,
    "num_predict": 120,
    "temperature": 0.1,  # we want consistent, literal JSON, not creative phrasing
}

# ---------------------------------------------------------------------------
# Provider registry
#
# To add a new provider: add one entry here (env var name + model name),
# then add a matching `_think_<name>(self, system_prompt, messages)` method
# on Brain. Everything else — trigger parsing, client caching, error
# messages, the outsource dispatch — works automatically off this table.
# ---------------------------------------------------------------------------
PROVIDERS = {
    "claude": {
        "env_var": "ANTHROPIC_API_KEY",
        "model": "claude-sonnet-4-6",
        "signup_url": "https://console.anthropic.com/settings/keys",
    },
    "gemini": {
        "env_var": "GEMINI_API_KEY",
        "model": "gemini-3.5-flash",
        "signup_url": "https://aistudio.google.com/apikey",
    },
    "openai": {
        "env_var": "OPENAI_API_KEY",
        "model": "gpt-5.2",
        "signup_url": "https://platform.openai.com/api-keys",
    },
}

# Used when the user just says "outsource: ..." with no provider named.
# Change this to whichever provider you use most.
DEFAULT_PROVIDER = os.environ.get("JARVIS_DEFAULT_PROVIDER", "claude")

# Matches "outsource: ...", "outsource claude: ...", "ask gemini: ...",
# "use openai: ...", etc. The provider name group is optional.
OUTSOURCE_TRIGGERS = re.compile(
    r"^\s*(?:outsource|ask|use)\s+(?P<provider>" + "|".join(PROVIDERS) + r")\s*[:,-]\s*"
    r"|^\s*(?:outsource|ask claude|use claude)\s*[:,-]?\s*",
    re.IGNORECASE,
)


@dataclass
class BrainResponse:
    text: str
    used_outsourcing: bool
    model: str
    provider: str = ""


def strip_outsource_trigger(user_message: str) -> tuple[str, bool, str]:
    """If the message starts with an outsource trigger phrase, strip it
    and report that outsourcing was requested, plus which provider (if
    any) was named. Falls back to DEFAULT_PROVIDER when none is named."""
    match = OUTSOURCE_TRIGGERS.match(user_message)
    if match:
        provider = (match.group("provider") or DEFAULT_PROVIDER).lower()
        return user_message[match.end():].strip(), True, provider
    return user_message, False, ""


class Brain:
    def __init__(self, ollama_host: str = "http://localhost:11434"):
        self.ollama_client = ollama.Client(host=ollama_host)
        self._clients: dict[str, object] = {}  # provider name -> lazy-loaded SDK client

    def _get_api_key(self, provider: str) -> str:
        cfg = PROVIDERS[provider]
        api_key = os.environ.get(cfg["env_var"])
        if not api_key:
            raise RuntimeError(
                f"Outsourcing to {provider} requested but {cfg['env_var']} is not set. "
                f"Set it with: setx {cfg['env_var']} \"your-key-here\" (Windows) "
                f"then restart your terminal. Get a key at {cfg['signup_url']}"
            )
        return api_key

    def _get_client(self, provider: str):
        if provider not in self._clients:
            api_key = self._get_api_key(provider)
            if provider == "claude":
                from anthropic import Anthropic
                self._clients[provider] = Anthropic(api_key=api_key)
            elif provider == "gemini":
                from google import genai
                self._clients[provider] = genai.Client(api_key=api_key)
            elif provider == "openai":
                from openai import OpenAI
                self._clients[provider] = OpenAI(api_key=api_key)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        return self._clients[provider]

    def think_local(self, system_prompt: str, messages: list[dict], options: dict | None = None) -> str:
        """Run inference entirely on your machine via Ollama. Nothing leaves it."""
        response = self.ollama_client.chat(
            model=LOCAL_MODEL,
            messages=[{"role": "system", "content": system_prompt}] + messages,
            options=options if options is not None else LOCAL_OPTIONS,
        )
        return response["message"]["content"]

    def think_outsourced(self, system_prompt: str, messages: list[dict], provider: str) -> tuple[str, str]:
        """Send this specific exchange to the requested cloud provider.
        Only called when the user explicitly asked for it. Returns
        (text, model_used)."""
        if provider not in PROVIDERS:
            known = ", ".join(PROVIDERS)
            raise RuntimeError(f"Unknown provider '{provider}'. Known providers: {known}")

        method = getattr(self, f"_think_{provider}", None)
        if method is None:
            raise RuntimeError(f"Provider '{provider}' is registered but has no _think_{provider} method.")

        text = method(system_prompt, messages)
        return text, PROVIDERS[provider]["model"]

    def _think_claude(self, system_prompt: str, messages: list[dict]) -> str:
        client = self._get_client("claude")
        response = client.messages.create(
            model=PROVIDERS["claude"]["model"],
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text

    def _think_gemini(self, system_prompt: str, messages: list[dict]) -> str:
        from google.genai import types

        client = self._get_client("gemini")
        # Gemini's SDK takes a flat list of turns rather than the
        # {"role": ..., "content": ...} dicts used elsewhere in this
        # project, so translate here, keeping the rest of the app's
        # message format unchanged.
        gemini_contents = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages
        ]
        response = client.models.generate_content(
            model=PROVIDERS["gemini"]["model"],
            contents=gemini_contents,
            config=types.GenerateContentConfig(system_instruction=system_prompt, max_output_tokens=1024),
        )
        return response.text

    def _think_openai(self, system_prompt: str, messages: list[dict]) -> str:
        client = self._get_client("openai")
        # OpenAI's chat format takes a single flat list with the system
        # prompt as its own message, rather than a separate `system` kwarg.
        openai_messages = [{"role": "system", "content": system_prompt}] + messages
        response = client.chat.completions.create(
            model=PROVIDERS["openai"]["model"],
            messages=openai_messages,
            max_tokens=1024,
        )
        return response.choices[0].message.content

    def respond(
        self,
        system_prompt: str,
        messages: list[dict],
        force_outsource: bool = False,
        provider: str = "",
    ) -> BrainResponse:
        if force_outsource:
            text, model_used = self.think_outsourced(system_prompt, messages, provider)
            return BrainResponse(text=text, used_outsourcing=True, model=model_used, provider=provider)
        text = self.think_local(system_prompt, messages)
        return BrainResponse(text=text, used_outsourcing=False, model=LOCAL_MODEL)
