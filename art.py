"""The hero's picture. Gemini's image model paints each job as a collectible figure, once;
the picture is kept in static/heroes/ and the page shows it in place of the drawn stand-in.
No key, no picture: the page keeps the figure it draws itself.
"""
import base64
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path

FOLDER = Path(__file__).resolve().parent / "static" / "heroes"
MODELS = ["gemini-3.1-flash-image", "gemini-3.1-flash-image-preview", "gemini-2.5-flash-image"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
GEAR = {"cap": "a work cap", "hardhat": "a yellow hard hat", "headset": "a headset with a small microphone",
        "headband": "a headband", "goggles": "safety goggles pushed up on the forehead", "none": ""}


def _file(role):
    return FOLDER / (re.sub(r"[^a-z0-9-]+", "-", str(role["id"]).lower()).strip("-")[:60] + ".png")


def url(role):
    """Where the page finds this job's picture, or None if it has not been painted."""
    file = _file(role)
    return "/heroes/%s?v=%d" % (file.name, int(file.stat().st_mtime)) if file.exists() else None


def brief(role):
    gear = GEAR.get(role.get("gear"), "")
    return (
        "Product photo of ONE collectible designer vinyl toy figure: an original hero character whose job is "
        "%s. Full body, centred, seen from a slightly low heroic angle, standing proud with the right fist "
        "raised to the sky; on the raised wrist a slim smart wristband with one small glowing light. "
        "Matte vinyl, big head and small body, a crisp refined work uniform for this job in the colour %s with "
        "%s accents, a short cape in %s%s. Friendly, confident face. Studio lighting, soft rim light, a faint "
        "floor reflection. Plain, very dark navy background (colour #070a16), nothing else in the frame. "
        "No text, no letters, no logos, no brand names, no watermark. Not based on any existing character, "
        "mascot or toy line." % (role["title"], role["suit"], role["cape"], role["cape"],
                                 (", wearing " + gear) if gear else ""))


def paint(role, note=print):
    """Paints the picture and returns its url, or None (and says why)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": brief(role)}]}],
                       "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}).encode("utf-8")
    models = [os.environ["GEMINI_IMAGE_MODEL"]] if os.environ.get("GEMINI_IMAGE_MODEL") else MODELS
    why = ""
    for model in models:
        request = urllib.request.Request(URL % model, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(request, timeout=120, context=ssl.create_default_context()) as answer:
                data = json.loads(answer.read().decode("utf-8"))
            for part in data["candidates"][0]["content"]["parts"]:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    FOLDER.mkdir(parents=True, exist_ok=True)
                    _file(role).write_bytes(base64.b64decode(inline["data"]))
                    return url(role)
            why = "%s gave no picture" % model
        except urllib.error.HTTPError as problem:
            why = "%s answered %s: %s" % (model, problem.code, problem.read().decode("utf-8", "replace")[:160])
        except Exception as problem:
            why = "%s: %s" % (model, str(problem)[:160])
    note("No picture for %s (%s). The drawn figure stays." % (role.get("hero", "this job"), why))
    return None


def kind(data):
    """The content type of a saved picture, from its first bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"
