"""
jarvis_gui.py — a real desktop window for Jarvis, instead of a black
command-line box. Same brain, same memory, same calendar/email tools as
jarvis.py — this file only adds a window on top of that already-tested
core logic (process_message), it doesn't reimplement any of it.

Run with:
    python jarvis_gui.py

Design notes (why it looks the way it does):
  - Dark background + a single cyan accent color, monospace-leaning font:
    a deliberate "HUD" feel that fits a personal AI assistant, without
    relying on tkinter's ugly default gray theme.
  - All slow work (talking to Ollama, transcribing speech) runs on a
    background thread. The window itself never freezes while Jarvis is
    "thinking" — you'll see a status line change instead of the whole
    app locking up, which matters on this hardware since replies take a
    few real seconds, not milliseconds.
"""

import threading
import tkinter as tk
from tkinter import scrolledtext

from memory_store import MemoryStore
from memory_extractor_local import extract_memories_local  # noqa: F401 (used inside jarvis.process_message)
from brain import Brain
from google_tools import CalendarTool, EmailTool
from jarvis import process_message

# ---- Visual identity -------------------------------------------------
BG = "#0d1117"            # near-black charcoal, easier on the eyes than pure black
PANEL = "#161b22"          # slightly lighter panel for the input bar
TEXT = "#e6edf3"           # soft off-white, not harsh pure white
ACCENT = "#4fd1c5"         # cyan — Jarvis's "voice" color and the signature accent
ACCENT_DIM = "#2a3b3a"     # muted version for borders/idle states
USER_COLOR = "#8b949e"     # muted gray for the user's own messages
ERROR_COLOR = "#f87171"    # soft red, only for real errors
FONT_FAMILY = "Consolas"   # ships on every Windows install, gives a "system/HUD" feel
FONT_BODY = (FONT_FAMILY, 11)
FONT_LABEL = (FONT_FAMILY, 9)
FONT_TITLE = (FONT_FAMILY, 13, "bold")


class JarvisGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Jarvis")
        self.root.geometry("520x640")
        self.root.configure(bg=BG)
        self.root.minsize(420, 480)

        # Core state — identical objects jarvis.py's text/voice loops use
        self.brain = Brain()
        self.memory = MemoryStore()
        self.calendar = CalendarTool()
        self.email = EmailTool()
        self.conversation_history: list[dict] = []

        # Voice is loaded lazily (only if the mic button is ever pressed),
        # so the window opens instantly even before Whisper is touched.
        self._voice = None
        self._listening = False

        self._build_layout()
        self._append_system("Jarvis is online — local model, fully private.")

    # ---- Layout --------------------------------------------------
    def _build_layout(self):
        header = tk.Frame(self.root, bg=BG, height=44)
        header.pack(fill="x", side="top")
        tk.Label(
            header, text="● JARVIS", font=FONT_TITLE, fg=ACCENT, bg=BG, anchor="w"
        ).pack(side="left", padx=14, pady=8)
        self.status_label = tk.Label(
            header, text="ready", font=FONT_LABEL, fg=USER_COLOR, bg=BG, anchor="e"
        )
        self.status_label.pack(side="right", padx=14)

        # Scrolling chat transcript
        self.chat_area = scrolledtext.ScrolledText(
            self.root,
            wrap="word",
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            font=FONT_BODY,
            borderwidth=0,
            highlightthickness=0,
            padx=14,
            pady=10,
            state="disabled",
        )
        self.chat_area.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # Tag styles for different speakers
        self.chat_area.tag_configure("user", foreground=USER_COLOR, font=FONT_BODY)
        self.chat_area.tag_configure("jarvis", foreground=ACCENT, font=FONT_BODY)
        self.chat_area.tag_configure("system", foreground=USER_COLOR, font=FONT_LABEL)
        self.chat_area.tag_configure("error", foreground=ERROR_COLOR, font=FONT_BODY)
        self.chat_area.tag_configure("label_user", foreground=USER_COLOR, font=(FONT_FAMILY, 9, "bold"))
        self.chat_area.tag_configure("label_jarvis", foreground=ACCENT, font=(FONT_FAMILY, 9, "bold"))

        # Bottom input bar: text entry + mic button + send button
        input_bar = tk.Frame(self.root, bg=PANEL)
        input_bar.pack(fill="x", side="bottom", padx=10, pady=10)

        self.entry = tk.Entry(
            input_bar,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            font=FONT_BODY,
            relief="flat",
            highlightthickness=1,
            highlightbackground=ACCENT_DIM,
            highlightcolor=ACCENT,
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.entry.bind("<Return>", self._on_send)
        self.entry.focus_set()

        self.mic_button = tk.Button(
            input_bar,
            text="🎤",
            font=(FONT_FAMILY, 13),
            bg=PANEL,
            fg=ACCENT,
            activebackground=ACCENT_DIM,
            relief="flat",
            width=3,
            command=self._on_mic_click,
            cursor="hand2",
        )
        self.mic_button.pack(side="left", padx=(0, 8))

        self.send_button = tk.Button(
            input_bar,
            text="Send",
            font=FONT_BODY,
            bg=ACCENT_DIM,
            fg=ACCENT,
            activebackground=ACCENT,
            activeforeground=BG,
            relief="flat",
            command=self._on_send,
            cursor="hand2",
        )
        self.send_button.pack(side="left")

    # ---- Chat transcript helpers -----------------------------------
    def _append(self, label: str, text: str, label_tag: str, text_tag: str):
        self.chat_area.configure(state="normal")
        self.chat_area.insert("end", f"{label}\n", label_tag)
        self.chat_area.insert("end", f"{text}\n\n", text_tag)
        self.chat_area.configure(state="disabled")
        self.chat_area.see("end")

    def _append_user(self, text: str):
        self._append("YOU", text, "label_user", "user")

    def _append_jarvis(self, text: str):
        self._append("JARVIS", text, "label_jarvis", "jarvis")

    def _append_system(self, text: str):
        self.chat_area.configure(state="normal")
        self.chat_area.insert("end", f"{text}\n\n", "system")
        self.chat_area.configure(state="disabled")
        self.chat_area.see("end")

    def _append_error(self, text: str):
        self._append("ERROR", text, "label_user", "error")

    def _set_status(self, text: str):
        self.status_label.configure(text=text)

    # ---- Sending a typed message -----------------------------------
    def _on_send(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append_user(text)
        self._handle_special_or_dispatch(text)

    def _handle_special_or_dispatch(self, text: str):
        lowered = text.lower()
        if lowered in ("exit", "quit"):
            self.root.destroy()
            return
        if lowered == "memories":
            mems = self.memory.all()
            if not mems:
                self._append_system("(no memories saved yet)")
            else:
                lines = "\n".join(f"[{m['kind']}] {m['text']}" for m in mems)
                self._append_system(lines)
            return
        self._dispatch_to_brain(text)

    def _dispatch_to_brain(self, text: str):
        """Run the (potentially slow) brain call on a background thread so
        the window stays responsive, then hand the result back to the main
        thread via root.after — the only thread-safe way to touch tkinter
        widgets from outside the main thread."""
        self._set_status("thinking…")
        self._set_inputs_enabled(False)

        def worker():
            try:
                reply = process_message(
                    text, self.brain, self.memory, self.conversation_history,
                    self.calendar, self.email,
                )
            except Exception as e:
                self.root.after(0, self._on_error, str(e))
                return
            self.root.after(0, self._on_reply, reply)

        threading.Thread(target=worker, daemon=True).start()

    def _on_reply(self, reply: str):
        self._append_jarvis(reply)
        self._set_status("ready")
        self._set_inputs_enabled(True)

    def _on_error(self, message: str):
        self._append_error(
            f"Something went wrong talking to the local model: {message}\n"
            f"(Is Ollama running? Try opening Command Prompt and typing 'ollama list' to check.)"
        )
        self._set_status("error")
        self._set_inputs_enabled(True)

    def _set_inputs_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        self.send_button.configure(state=state)
        self.mic_button.configure(state=state)

    # ---- Voice (mic button) ----------------------------------------
    def _get_voice(self):
        if self._voice is None:
            from voice import VoiceIO
            self._voice = VoiceIO()
        return self._voice

    def _on_mic_click(self):
        if self._listening:
            return  # already mid-recording, ignore extra clicks
        self._listening = True
        self.mic_button.configure(fg=ERROR_COLOR)
        self._set_status("listening…")
        self._set_inputs_enabled(False)
        self.mic_button.configure(state="disabled")

        def worker():
            try:
                voice = self._get_voice()
                self.root.after(0, lambda: self._set_status("listening… (speak now)"))
                transcribed = voice.listen()
            except Exception as e:
                self.root.after(0, self._on_voice_error, str(e))
                return
            self.root.after(0, self._on_voice_transcribed, transcribed, voice)

        threading.Thread(target=worker, daemon=True).start()

    def _on_voice_transcribed(self, transcribed: str, voice):
        self._listening = False
        self.mic_button.configure(fg=ACCENT, state="normal")
        self._set_inputs_enabled(True)

        if not transcribed:
            self._set_status("ready")
            self._append_system("(didn't catch anything — try again)")
            return

        self._append_user(transcribed)
        self._set_status("thinking…")
        self._set_inputs_enabled(False)

        def worker():
            try:
                reply = process_message(
                    transcribed, self.brain, self.memory, self.conversation_history,
                    self.calendar, self.email,
                )
            except Exception as e:
                self.root.after(0, self._on_error, str(e))
                return
            self.root.after(0, self._on_voice_reply, reply, voice)

        threading.Thread(target=worker, daemon=True).start()

    def _on_voice_reply(self, reply: str, voice):
        self._append_jarvis(reply)
        self._set_status("speaking…")
        self._set_inputs_enabled(True)

        def speak_worker():
            try:
                voice.speak(reply)
            finally:
                self.root.after(0, lambda: self._set_status("ready"))

        threading.Thread(target=speak_worker, daemon=True).start()

    def _on_voice_error(self, message: str):
        self._listening = False
        self.mic_button.configure(fg=ACCENT, state="normal")
        self._set_inputs_enabled(True)
        self._set_status("error")
        self._append_error(
            f"Voice input failed: {message}\n"
            f"(Check your microphone is connected and Windows has granted mic permission to this app.)"
        )


def main():
    root = tk.Tk()
    JarvisGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
