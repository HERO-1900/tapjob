"""Words -> a draft invoice.

The model only pulls out what was said (customer, parts, prices, hours). All the sums are
done here in plain code: a model can be wrong, and money must not be.

Which model: Gemini 4 if GEMINI_API_KEY is set, else OpenAI through the kit's helper if
OPENAI_API_KEY is set, else simple offline rules (good enough for a demo sentence).
Plain HTTPS from the standard library: nothing to install.
"""
import json
import math
import os
import re
import ssl
import urllib.error
import urllib.request

import roles

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
GEMINI_MODEL = "gemini-4-hydrogen"          # the fast one; set GEMINI_MODEL to try another

INSTRUCTIONS = (
    "You turn a tradesperson's spoken job notes into invoice fields. The notes come from a "
    "microphone on a wrist band, so they are rough: fix obvious speech-to-text slips, keep the meaning. "
    "Use only what was said. Never invent a part, a quantity, a price or hours. "
    "A price that was not said is null. Hours of labor that were not said are null. "
    "unit_price is the price of ONE unit, in plain numbers without currency signs. "
    "summary is one short sentence a customer understands."
)

# Gemini's schema dialect (an OpenAPI subset, type names in capitals).
GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "customer": {"type": "STRING", "nullable": True},
        "summary": {"type": "STRING"},
        "parts": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "description": {"type": "STRING"},
                "quantity": {"type": "NUMBER"},
                "unit_price": {"type": "NUMBER", "nullable": True},
            },
            "required": ["description", "quantity"],
        }},
        "labor_hours": {"type": "NUMBER", "nullable": True},
    },
    "required": ["summary", "parts"],
}

# The same for OpenAI's strict structured output (every field required, nulls allowed).
OPENAI_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["customer", "summary", "parts", "labor_hours"],
    "properties": {
        "customer": {"type": ["string", "null"]},
        "summary": {"type": "string"},
        "parts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["description", "quantity", "unit_price"],
            "properties": {
                "description": {"type": "string"},
                "quantity": {"type": "number"},
                "unit_price": {"type": ["number", "null"]},
            }}},
        "labor_hours": {"type": ["number", "null"]},
    },
}


def provider():
    if os.environ.get("GEMINI_API_KEY"):
        return "Gemini (%s)" % os.environ.get("GEMINI_MODEL", GEMINI_MODEL)
    if os.environ.get("OPENAI_API_KEY"):
        return "OpenAI (kit helper)"
    return "offline rules (no model key)"


# ---- the three ways to read the words ----------------------------------------------------

def _gemini(words, instructions=None):
    model = os.environ.get("GEMINI_MODEL", GEMINI_MODEL)
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": instructions or INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": words}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": GEMINI_SCHEMA},
    }).encode("utf-8")
    request = urllib.request.Request(GEMINI_URL % model, data=body, method="POST", headers={
        "Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    try:
        with urllib.request.urlopen(request, timeout=40, context=ssl.create_default_context()) as answer:
            data = json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as problem:
        detail = problem.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("Gemini answered %s: %s" % (problem.code, detail))
    text = "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"]
                   if not part.get("thought"))
    return _json(text)


def _openai(words, instructions=None):
    import ai                                    # the kit's helper (vexo-open-kit/examples/python/ai.py)
    return ai.extract(words, OPENAI_SCHEMA, instructions or INSTRUCTIONS)


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        found = re.search(r"\{.*\}", text, re.S)
        if not found:
            raise RuntimeError("The model's answer was not JSON.")
        return json.loads(found.group(0))


NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "half": 0.5, "quarter": 0.25}
AMOUNT = r"(?:\$\s?(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:dollars?|bucks|usd))"
VERBS = r"^(?:and\s+|then\s+|also\s+|i\s+)*(?:replaced|installed|used|swapped|changed|added|fitted|put in|fixed)\s+"


def _number(word):
    word = word.lower().strip()
    if word in NUMBER_WORDS:
        return NUMBER_WORDS[word]
    try:
        return float(word)
    except ValueError:
        return None


def _offline(words):
    """No model at hand: look for 'thing, 18 dollars' and 'labor one and a half hours'."""
    customer = None
    who = re.search(r"\b(?:for|customer(?: is)?)\s+((?:mr|mrs|ms|miss|dr)\.?\s+[A-Za-z][\w'-]+)", words, re.I)
    if who:
        customer = who.group(1).strip()
    parts, hours = [], None
    sentences = [s.strip() for s in re.split(r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bMrs\.)(?<=[.!?;])\s+|\n+", words)
                 if s.strip()]
    for sentence in sentences:
        labor = re.search(r"(\d+(?:\.\d+)?|[a-z]+)\s+(and a half\s+|and a quarter\s+)?(hours?|hrs?|minutes?|mins?)",
                          sentence, re.I)
        if labor and re.search(r"labou?r|work|took|spent", sentence, re.I):
            amount = _number(labor.group(1))
            if amount is not None:
                amount += 0.5 if (labor.group(2) or "").strip().endswith("half") else 0
                amount += 0.25 if (labor.group(2) or "").strip().endswith("quarter") else 0
                hours = amount / 60 if labor.group(3).lower().startswith("min") else amount
            sentence = sentence[:labor.start()].rstrip(" ,")           # prices may sit in the same sentence
        start = 0
        for price in re.finditer(AMOUNT, sentence, re.I):          # "P-trap, $18, and a supply line, $25"
            what = sentence[start:price.start()].strip(" ,:-")
            start = price.end()
            what = re.sub(r"^(?:and|plus|also|then)\s+", "", what, flags=re.I)
            what = re.sub(VERBS, "", what, flags=re.I)
            what = re.sub(r"\s+(?:for|at|costs?|was|is)$", "", what, flags=re.I).strip(" ,:-")
            quantity = 1.0
            first = what.split(" ", 1)
            if len(first) == 2 and first[0].lower() not in ("a", "an", "the") and _number(first[0]) is not None:
                quantity, what = _number(first[0]), first[1]
            what = re.sub(r"^(?:a|an|the|one)\s+", "", what, flags=re.I)
            if what:
                parts.append({"description": what[:1].upper() + what[1:], "quantity": quantity,
                              "unit_price": float(price.group(1) or price.group(2))})
    summary = ""
    for sentence in sentences:                                         # the first one that says something
        summary = re.sub(r"^job for [^,]+(?:,\s*|$)", "", sentence.strip(" ."), flags=re.I).strip(" .")
        summary = re.split(AMOUNT, summary, maxsplit=1, flags=re.I)[0].strip(" ,:-")
        if summary:
            break
    summary = (summary[:1].upper() + summary[1:]) if summary else "Service call"
    return {"customer": customer, "summary": summary[:160], "parts": parts, "labor_hours": hours}


def _listed(words, role, already):
    """No model at hand: things on the price list that were named without a price."""
    have = {roles._plain(part.get("description", "")) for part in already}
    text, parts = " " + roles._plain(words) + " ", []
    for name, _price in sorted((role or {}).get("price_list") or [], key=lambda row: -len(row[0])):
        plain = roles._plain(name)
        spot = re.search(r"(?:\b([a-z]+|\d+(?:\.\d+)?) )?%s\b" % re.escape(plain), text) if plain else None
        if not spot:
            continue
        if plain in have:                            # already on the draft with a said price: just not twice
            text = text[:spot.start()] + " " * (spot.end() - spot.start()) + text[spot.end():]
            continue
        quantity = _number(spot.group(1)) if spot.group(1) else None
        parts.append({"description": name, "quantity": quantity or 1.0, "unit_price": None})
        text = text[:spot.start()] + " " * (spot.end() - spot.start()) + text[spot.end():]    # not twice
    return parts


# ---- from the fields to money ------------------------------------------------------------

def money(amount, currency="usd"):
    return ("$%.2f" % amount) if currency.lower() == "usd" else "%.2f %s" % (amount, currency.upper())


def make_draft(words, config, on_site_seconds=0, active_seconds=0, note=print, role=None):
    """The fields a model found, checked and priced. Never raises: the worst case is the
    offline rules and a warning on the draft."""
    used, found = "offline rules", None
    attempts = []
    if os.environ.get("GEMINI_API_KEY"):
        attempts.append(("Gemini (%s)" % os.environ.get("GEMINI_MODEL", GEMINI_MODEL), _gemini))
    if os.environ.get("OPENAI_API_KEY"):
        attempts.append(("OpenAI (kit helper)", _openai))
    for name, read in attempts:
        try:
            found, used = read(words, INSTRUCTIONS + roles.prompt(role)), name
            break
        except Exception as problem:                 # try the next one, say why
            note("%s could not read the notes: %s" % (name, str(problem)[:200]))
    if not isinstance(found, dict):
        found, used = _offline(words), "offline rules"
        found["parts"] = (found.get("parts") or []) + _listed(words, role, found.get("parts") or [])

    rate = float((role or {}).get("labor_rate") or config["labor_rate"])
    bills_labor = role is None or bool(role.get("bills_labor"))
    warnings, items = [], []
    for part in found.get("parts") or []:
        description = str(part.get("description") or "").strip()[:200]
        if not description:
            continue
        try:
            quantity = float(part.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1.0
        if not math.isfinite(quantity) or quantity <= 0 or quantity > 1000:
            quantity = 1.0
        price = part.get("unit_price")
        try:
            price = None if price is None else float(price)
        except (TypeError, ValueError):
            price = None
        if price is not None and (not math.isfinite(price) or price < 0 or price > 100000):
            price = None
        source = "said" if price is not None else None
        listed = roles.find_price(description, role)
        if listed:                                   # the business's own price list, looked up in code
            description = listed[0]
            if price is None:
                price, source = listed[1], "price list"
        if price is None:
            warnings.append("No price was said for: %s. It is on the invoice at $0, fix it before you send." % description)
        items.append({"description": description, "quantity": quantity, "unit_price": price,
                      "amount": round(quantity * (price or 0), 2), "source": source})

    labor = None
    if bills_labor:
        hours = found.get("labor_hours")
        try:
            hours = None if hours is None else float(hours)
        except (TypeError, ValueError):
            hours = None
        if hours is not None and (not math.isfinite(hours) or hours <= 0 or hours > 24):
            hours = None
        if hours is not None:
            source = "said by the technician"
        else:
            hours = max(0.25, math.ceil(on_site_seconds / 900) / 4)      # quarter hours, at least one
            source = "measured by the band"
            warnings.append("No hours were said. The band timed %d minutes on site." % round(on_site_seconds / 60))
        labor = {"hours": hours, "rate": rate, "amount": round(hours * rate, 2), "source": source}

    total = round(sum(item["amount"] for item in items) + (labor["amount"] if labor else 0), 2)
    return {
        "customer": (str(found.get("customer") or "").strip() or "Customer")[:80],
        "summary": (str(found.get("summary") or "").strip() or "Service call")[:300],
        "items": items, "labor": labor, "total": total, "warnings": warnings, "provider": used,
        "role": (role or {}).get("title"), "business": (role or {}).get("business"),
        "evidence": {"on_site_minutes": round(on_site_seconds / 60, 1),
                     "hands_working_minutes": round(active_seconds / 60, 1)},
    }


def read_back(draft):
    """One breath, for the ear: the customer, each line, the total."""
    lines = ["%s for %s." % ("Invoice" if draft.get("labor") else "Order", draft["customer"])]
    for item in draft["items"]:
        lines.append("%s, %s." % (item["description"], _spoken(item["amount"]) if item["unit_price"] is not None
                                  else "no price"))
    labor = draft.get("labor")
    if labor:
        lines.append("Labor %g hours, %s." % (labor["hours"], _spoken(labor["amount"])))
    lines.append("Total %s." % _spoken(draft["total"]))
    return " ".join(lines)


def _spoken(amount):
    dollars, cents = int(amount), int(round((amount - int(amount)) * 100))
    return "%d dollars" % dollars if not cents else "%d dollars %02d" % (dollars, cents)
