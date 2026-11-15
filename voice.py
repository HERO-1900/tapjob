"""The band cannot speak, so the computer does: Deepgram's text-to-speech when the team's
key is there, the Mac's own `say` otherwise, and plain print when neither works.
Speaking happens on its own thread: the band is never kept waiting.
"""
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.request

SPEAK_URL = "https://api.deepgram.com/v1/speak?model=%s"
MODELS = [os.environ.get("DEEPGRAM_TTS_MODEL", "aura-2-thalia-en"), "aura-asteria-en"]
_line = threading.Lock()                       # one sentence at a time
_waiting = 0                                   # sentences asked for and not yet finished
_ended = 0.0                                   # when the last one finished


def speaking(grace=0.6):
    """True while the computer is talking, and for a moment after. The band lies next to the
    loudspeaker on a desk: its voice can shake it into a double-tap, so taps then do not count."""
    return _waiting > 0 or time.time() - _ended < grace


def _deepgram(text):
    key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    player = shutil.which("afplay") or shutil.which("ffplay") or shutil.which("mpg123")
    if not key or not player:
        return False
    for model in MODELS:
        try:
            request = urllib.request.Request(SPEAK_URL % model, data=json.dumps({"text": text}).encode("utf-8"),
                                             method="POST", headers={"Authorization": "Token " + key,
                                                                     "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context()) as answer:
                sound = answer.read()
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as file:
                file.write(sound)
            command = [player, file.name] if "ffplay" not in player else [player, "-nodisp", "-autoexit", "-loglevel",
                                                                           "quiet", file.name]
            subprocess.run(command, timeout=60, check=False)
            os.unlink(file.name)
            return True
        except Exception:
            continue
    return False


def _say(text):
    if not shutil.which("say"):
        return False
    try:
        subprocess.run(["say", "-r", "215", text], timeout=60, check=False)
        return True
    except Exception:
        return False


def speak(text):
    global _waiting

    def work():
        global _waiting, _ended
        try:
            with _line:
                if not _deepgram(text) and not _say(text):
                    print("(no voice on this computer) " + text)
        finally:
            _waiting -= 1
            _ended = time.time()

    _waiting += 1
    threading.Thread(target=work, daemon=True).start()
