"""
ai_modules/speech.py  — Fixed Vosk speech recognition

Fixes vs original:
  1. Model loaded inside start() not __init__  →  no crash at import time
  2. socketio.emit uses  namespace="/"  explicitly  →  avoids silent no-op
  3. Queue drained on stop()  →  no blocked thread after call ends
  4. Language switch locks the recognizer  →  no race condition
  5. Models stored as class-level cache  →  loaded only once across calls
"""

import queue
import json
import threading
import sounddevice as sd
from vosk import Model, KaldiRecognizer


class VoskSpeechRecognizer:

    # ── class-level model cache so we load each model only once ──
    _model_cache: dict[str, Model] = {}

    MODEL_PATHS = {
        "en": "models/vosk-model-en-in-0.5",
        "hi": "models/vosk-model-small-hi-0.22",
    }

    def __init__(self, socketio):
        self.socketio     = socketio
        self.q            = queue.Queue()
        self.current_lang = "en"
        self.recognizer   = None
        self.running      = False
        self.stream       = None
        self.last_text    = ""
        self._lock        = threading.Lock()

    # ─────────────── private helpers ───────────────

    def _get_model(self, lang: str) -> Model:
        if lang not in self._model_cache:
            path = self.MODEL_PATHS.get(lang, self.MODEL_PATHS["en"])
            print(f"⏳  Loading Vosk model for '{lang}' from {path} …")
            self._model_cache[lang] = Model(path)
            print(f"✅  Vosk model '{lang}' ready")
        return self._model_cache[lang]

    def _make_recognizer(self, lang: str) -> KaldiRecognizer:
        model = self._get_model(lang)
        return KaldiRecognizer(model, 16000)

    # ─────────────── public API ───────────────

    def set_language(self, lang: str):
        with self._lock:
            if lang not in self.MODEL_PATHS:
                print(f"⚠️  Unknown language '{lang}', defaulting to 'en'")
                lang = "en"
            self.current_lang = lang
            self.recognizer   = self._make_recognizer(lang)
        print(f"🌐  Language → {lang}")

    def start(self):
        if self.running:
            print("Speech already running")
            return

        # lazy-load the default model on first start
        with self._lock:
            if self.recognizer is None:
                self.recognizer = self._make_recognizer(self.current_lang)

        print("🎤  Speech recognition started")
        self.running = True

        self.stream = sd.RawInputStream(
            samplerate = 16000,
            blocksize  = 8000,
            dtype      = "int16",
            channels   = 1,
            callback   = self._audio_callback,
        )
        self.stream.start()

        threading.Thread(target=self._process_loop, daemon=True).start()

    def stop(self):
        if not self.running:
            return

        print("🛑  Speech recognition stopped")
        self.running = False

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        # drain the queue so the worker thread can exit
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    # ─────────────── internal ───────────────

    def _audio_callback(self, indata, frames, time, status):
        if status:
            print("Audio status:", status)
        if self.running:
            self.q.put(bytes(indata))

    def _process_loop(self):
        while self.running:
            try:
                data = self.q.get(timeout=1)
            except queue.Empty:
                continue

            with self._lock:
                rec = self.recognizer
                lang = self.current_lang

            if rec is None:
                continue

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text   = result.get("text", "").strip()

                if text and text != self.last_text:
                    self.last_text = text
                    print(f"[{lang}] {text}")

                    self.socketio.emit(
                        "result",
                        {"text": text, "type": "speech", "lang": lang},
                        namespace="/",
                    )


# ─────────────────────────────────────────────
#  Module-level singleton + control functions
# ─────────────────────────────────────────────
_instance: VoskSpeechRecognizer | None = None


def start_speech(socketio):
    global _instance
    if _instance is None:
        _instance = VoskSpeechRecognizer(socketio)
    _instance.start()


def stop_speech():
    if _instance:
        _instance.stop()


def set_language(lang: str):
    if _instance:
        _instance.set_language(lang)
