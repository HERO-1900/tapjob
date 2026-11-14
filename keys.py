"""The three keys TapJob can use. They live in .env on this computer, nowhere else:
not in code, not in git, not in the page (the page only learns "saved" or "missing").
"""
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {
    "DEEPGRAM_API_KEY": "Deepgram: speech to text, and the read-back voice",
    "GEMINI_API_KEY": "Google AI Studio: words to invoice fields",
    "STRIPE_SECRET_KEY": "Stripe TEST secret key (starts with sk_test_): the invoice and pay page",
}


def status():
    return {name: bool(os.environ.get(name, "").strip()) for name in NAMES}


def check(name, value):
    """None if the value can be saved, else one sentence saying why not."""
    if name not in NAMES:
        return "Unknown key name."
    if not isinstance(value, str) or not re.fullmatch(r"[\x21-\x7e]{8,300}", value):
        return "That does not look like a key: no spaces, 8 characters or more."
    if name == "STRIPE_SECRET_KEY" and not value.startswith(("sk_test_", "rk_test_")):
        return "Only a Stripe TEST key is accepted here (it starts with sk_test_). Live keys are refused."
    return None


def save(name, value, folder=HERE):
    """Write NAME=value into .env (made from env.example the first time) and into this program."""
    problem = check(name, value)
    if problem:
        raise ValueError(problem)
    path = Path(folder) / ".env"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        try:
            text = (Path(folder) / "env.example").read_text(encoding="utf-8")
        except OSError:
            text = ""
    line = "%s=%s" % (name, value)
    pattern = r"(?m)^%s=.*$" % re.escape(name)
    if re.search(pattern, text):
        text = re.sub(pattern, lambda _: line, text)
    else:
        text = text.rstrip("\n") + ("\n" if text else "") + line + "\n"
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)
    os.environ[name] = value
