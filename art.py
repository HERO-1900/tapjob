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


STYLE = "toy4"                                  # part of the file name: a new style paints new pictures
FIGURES = {"woman": "a woman", "man": "a man", "person": "a person"}


def _file(role, figure="person"):
    name = re.sub(r"[^a-z0-9-]+", "-", str(role["id"]).lower()).strip("-")[:50]
    return FOLDER / ("%s-%s-%s.png" % (name, STYLE, figure if figure in FIGURES else "person"))


def url(role, figure="person"):
    """Where the page finds this job's picture, or None if it has not been painted."""
    file = _file(role, figure)
    return "/heroes/%s?v=%d" % (file.name, int(file.stat().st_mtime)) if file.exists() else None


def backdrop(role):
    """The poster colour behind the figure: the job's accent colour, lightened."""
    cape = role.get("cape") or "#e23b2e"
    parts = [int(cape[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("%02x" % round(v + (255 - v) * 0.5) for v in parts)


def brief(role, figure="person"):
    gear = GEAR.get(role.get("gear"), "")
    look = role.get("look") or ("a crisp work uniform for this job" + (", " + gear if gear else ""))
    tool = role.get("tool") or "the one signature tool of this job, oversized"
    scene = role.get("scene") or "a small round base built from the things of this job"
    pose = role.get("pose") or "a bold action pose with one fist raised"
    return (
        "Toy photography of ONE highly detailed collectible designer figure: an original character, %s whose "
        "job is %s. Loud, proud and unmistakable for this job. Stylised proportions with a large head, "
        "expressive eyes and a big grin. The character: %s. In one hand: %s. Pose: %s. On the wrist of the "
        "raised fist: a chunky smart wristband with one bright glowing light, clearly visible. Under the feet: "
        "%s. Main colours %s and %s, with strong contrast. Layered materials: matte vinyl skin, textured "
        "fabric, shiny metal, glossy details. Dramatic studio light with a coloured rim light, seen from "
        "slightly below, a slight tilt for energy. The whole figure and its base are inside the picture and "
        "fill about 88 percent of its height, centred. Background: ONE flat solid colour, %s, no gradient. "
        "Portrait picture. No text, no letters, no numbers, no logos, no brand names, no watermark. An "
        "original design, not based on any existing character, mascot or toy line."
        % (FIGURES.get(figure, "a person"), role["title"], look, tool, pose, scene, role["suit"], role["cape"],
           backdrop(role)))


def _ask(model, key, text, shape):
    setup = {"responseModalities": ["TEXT", "IMAGE"]}
    if shape:
        setup["imageConfig"] = {"aspectRatio": "3:4"}
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": text}]}],
                       "generationConfig": setup}).encode("utf-8")
    request = urllib.request.Request(URL % model, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(request, timeout=120, context=ssl.create_default_context()) as answer:
        data = json.loads(answer.read().decode("utf-8"))
    for part in data["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    return None


def paint(role, note=print, figure="person"):
    """Paints the picture and returns its url, or None (and says why)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    models = [os.environ["GEMINI_IMAGE_MODEL"]] if os.environ.get("GEMINI_IMAGE_MODEL") else MODELS
    why = ""
    for model in models:
        for shape in (True, False):                  # ask for a portrait; if that setting is refused, ask plainly
            try:
                picture = _ask(model, key, brief(role, figure), shape)
                if picture:
                    FOLDER.mkdir(parents=True, exist_ok=True)
                    _file(role, figure).write_bytes(picture)
                    return url(role, figure)
                why = "%s gave no picture" % model
                break
            except urllib.error.HTTPError as problem:
                why = "%s answered %s: %s" % (model, problem.code, problem.read().decode("utf-8", "replace")[:160])
                if problem.code != 400:
                    break
            except Exception as problem:
                why = "%s: %s" % (model, str(problem)[:160])
                break
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
