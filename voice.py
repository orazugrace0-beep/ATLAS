"""
voice.py — speech in, speech out. Both run entirely on your machine.

- Speech-to-text: faster-whisper, running a small local Whisper model.
  This is NOT a cloud API call — the model downloads once (a few hundred
  MB, depending on size) and then runs offline forever after.
- Text-to-speech: pyttsx3, which drives Windows' built-in SAPI voices.
  Fully offline, no internet needed, no audio ever sent anywhere.

Setup (Windows):
    pip install faster-whisper pyttsx3 sounddevice numpy

First run will download the Whisper model (~150MB for "base", the
default below). Pick a bigger model (e.g. "small" or "medium") if you
want better accuracy and have the disk/CPU/GPU to spare; smaller is
faster on modest hardware.
"""

import queue
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

import pyttsx3

WHISPER_MODEL_SIZE = "base"  # tiny / base / small / medium / large-v3
SAMPLE_RATE = 16000


class VoiceIO:
    def __init__(self):
        # device="cpu" works everywhere; if you have an NVIDIA GPU with CUDA
        # set up, change to device="cuda" for much faster transcription.
        self._whisper = None  # lazy-loaded on first use so startup is instant
        self._tts_engine = None

    def _get_whisper(self) -> WhisperModel:
        if self._whisper is None:
            print(f"(loading local Whisper model '{WHISPER_MODEL_SIZE}', first time may take a minute...)")
            self._whisper = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        return self._whisper

    def _get_tts(self):
        if self._tts_engine is None:
            self._tts_engine = pyttsx3.init()
            self._tts_engine.setProperty("rate", 175)
        return self._tts_engine

    def listen(self, max_seconds: int = 8) -> str:
        """Record from the default microphone until silence or max_seconds,
        then transcribe locally. Returns the transcribed text."""
        print(f"Listening... (speak now, up to {max_seconds}s)")
        recording = sd.rec(
            int(max_seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16"
        )
        sd.wait()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(recording.tobytes())

        model = self._get_whisper()
        segments, _info = model.transcribe(wav_path, language="en")
        text = " ".join(seg.text.strip() for seg in segments).strip()

        Path(wav_path).unlink(missing_ok=True)
        return text

    def speak(self, text: str):
        """Speak text out loud using offline Windows TTS voices."""
        engine = self._get_tts()
        engine.say(text)
        engine.runAndWait()


def transcribe_array(audio_int16: np.ndarray, sample_rate: int = SAMPLE_RATE, model_size: str = WHISPER_MODEL_SIZE) -> str:
    """Pure function: transcribe an in-memory int16 numpy array of audio
    samples. Split out from VoiceIO.listen so it can be unit tested without
    needing a real microphone."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(wav_path, language="en")
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        Path(wav_path).unlink(missing_ok=True)
