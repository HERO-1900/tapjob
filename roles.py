"""Who is wearing the band.

A role is a job: the business name, the price list, whether time is billed, and the hero
card the page shows for it. Four come ready-made; anyone can make their own from one
sentence (Gemini writes the card, this file checks every field before it is used).

The price list is what makes the money traceable: when the worker names something on the
list without saying a price, the price comes from the list, in plain code, and the ticket
says so.
"""
import difflib
import json
import os
import re
import ssl
import urllib.error
import urllib.request

GEARS = ("cap", "hardhat", "headset", "headband", "goggles", "none")

PRESETS = [
    {
        "id": "plumber",
        "look": "stocky and cheerful, a backwards cap and rosy cheeks, rolled-up sleeves, a tool belt heavy with fittings, knee pads, a short red hero cape", "tool": "a huge red pipe wrench resting on one shoulder", "scene": "a round base of shiny copper pipes with a brass valve, a small puddle and flying water drops", "pose": "one boot planted on a pipe, chest out, the free fist punched high in the air", "title": "Plumber", "hero": "Leakbreaker", "business": "Wang & Sons Plumbing",
        "power": "Stops the leak and writes the bill before the van door shuts.",
        "emoji": "🔧", "suit": "#1f4fd8", "cape": "#e23b2e", "gear": "cap",
        "bills_labor": True, "labor_rate": 95.0,
        "price_list": [["P-trap", 18], ["Supply line", 12], ["Faucet cartridge", 45], ["Shutoff valve", 22],
                       ["Wax ring", 9], ["Drain cleaning", 120]],
        "sample": "Job for Mrs. Chen. The kitchen faucet was dripping. Replaced the faucet cartridge "
                  "and two supply lines. One hour of labor.",
    },
    {
        "id": "drive-through",
        "look": "quick and bright, a striped paper hat and a headset with a microphone, an apron with a pocket full of straws, roller skates, a yellow hero scarf flying sideways", "tool": "a tray held high on one hand with a towering burger, fries and a shake", "scene": "a round base with a tiny drive-through window, a striped awning and the bumper of a toy car", "pose": "gliding forward on the skates, leaning into the turn, the free arm stretched out with the fist raised", "title": "Drive-through order taker", "hero": "Lane Captain",
        "business": "Sunset Drive-In",
        "power": "Hears the whole car and rings it up without a register.",
        "emoji": "🍔", "suit": "#e23b2e", "cape": "#ffc61a", "gear": "headset",
        "bills_labor": False, "labor_rate": 0.0,
        "price_list": [["Hamburger", 4.5], ["Cheeseburger", 5.0], ["Double cheeseburger", 6.9], ["Fries", 2.8],
                       ["Shake", 3.6], ["Soda", 2.4], ["Diet soda", 2.4], ["Lemonade", 2.6]],
        "sample": "Two double cheeseburgers, one fries, one diet soda and a shake.",
    },
    {
        "id": "massage",
        "look": "calm and strong, hair in a high bun with a jade pin, a wrap tunic with wide sleeves, bare feet in wooden sandals, a long teal sash floating like a cape", "tool": "three warm smooth stones floating in a curve above one open palm", "scene": "a round base with a folded massage table corner, rolled towels, a candle and curling steam", "pose": "a balanced martial-arts stance, one knee bent, the free fist raised by the ear", "title": "Massage therapist", "hero": "Knot Tamer", "business": "Calm Hands Studio",
        "power": "Unties the knots and settles the bill hands-free.",
        "emoji": "💆", "suit": "#7a4fd6", "cape": "#19b5a5", "gear": "headband",
        "bills_labor": False, "labor_rate": 0.0,
        "price_list": [["60-minute massage", 110], ["90-minute massage", 150], ["Hot stones", 25],
                       ["Aromatherapy", 15], ["Cupping", 30]],
        "sample": "Session for Ms. Rivera. Ninety-minute massage with hot stones.",
    },
    {
        "id": "mechanic",
        "look": "tall and wiry, a grease smudge on one cheek, a bandana, welding goggles on the forehead, coveralls tied at the waist, heavy gloves, a torn orange hero cape", "tool": "a roaring impact wrench held like a trophy, sparks flying from it", "scene": "a round base with a stack of tyres, a floor jack, an oil can and a chrome wheel", "pose": "one foot up on the tyres, leaning back with a grin, the free fist raised", "title": "Auto mechanic", "hero": "Torque Titan", "business": "Northside Auto Repair",
        "power": "Finds the rattle and bills by the bay clock.",
        "emoji": "🚗", "suit": "#2b3350", "cape": "#ff7a1a", "gear": "goggles",
        "bills_labor": True, "labor_rate": 140.0,
        "price_list": [["Oil change", 79], ["Brake pads", 95], ["Battery", 180], ["Air filter", 28],
                       ["Wiper blades", 32], ["Spark plug", 14]],
        "sample": "Job for Mr. Diaz. Changed the brake pads and the air filter. One and a half hours of labor.",
    },
]

# Made-up menus to try the price list with. Paste your own in their place.
SAMPLES = {
    "Burger stand": "Hamburger, 4.50\nCheeseburger, 5.00\nDouble cheeseburger, 6.90\nFries, 2.80\nShake, 3.60\n"
                    "Soda, 2.40\nDiet soda, 2.40\nLemonade, 2.60",
    "Boba tea shop": "Classic milk tea, 5.50\nBrown sugar boba, 6.25\nMatcha latte, 6.00\nMango green tea, 5.75\n"
                     "Taro smoothie, 6.50\nExtra boba, 0.75\nCheese foam, 1.00",
    "Sushi bar": "Salmon nigiri, 7.00\nTuna nigiri, 8.00\nCalifornia roll, 9.00\nSpicy tuna roll, 11.00\n"
                 "Miso soup, 3.50\nEdamame, 5.00\nGreen tea, 3.00",
}

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean(raw, fallback_title="My job"):
    """A role from untrusted fields (a model's answer): every field checked, nothing trusted."""
    raw = raw if isinstance(raw, dict) else {}

    def text(key, default, limit):
        value = re.sub(r"[<>\x00-\x1f]", "", str(raw.get(key) or "")).strip()
        return value[:limit] or default

    def color(key, default):
        value = str(raw.get(key) or "")
        return value.lower() if HEX.match(value) else default

    prices = []
    for row in raw.get("price_list") or []:
        if isinstance(row, dict):
            name, price = row.get("name"), row.get("price")
        elif isinstance(row, (list, tuple)) and len(row) == 2:
            name, price = row
        else:
            continue
        name = re.sub(r"[<>\x00-\x1f]", "", str(name or "")).strip()[:60]
        try:
            price = round(float(price), 2)
        except (TypeError, ValueError):
            continue
        if name and 0 <= price <= 100000:
            prices.append([name, price])
    try:
        rate = float(raw.get("labor_rate") or 0)
    except (TypeError, ValueError):
        rate = 0.0
    rate = rate if 0 < rate <= 2000 else 0.0
    title = text("title", fallback_title, 48)
    gear = str(raw.get("gear") or "").lower()
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", text("id", title, 40).lower()).strip("-") or "job",
        "title": title, "hero": text("hero", "The " + title, 32),
        "business": text("business", title, 48), "power": text("power", "Does the job, sends the bill.", 110),
        "emoji": text("emoji", "⭐", 8), "suit": color("suit", "#1f4fd8"), "cape": color("cape", "#e23b2e"),
        "gear": gear if gear in GEARS else "none",
        "bills_labor": bool(raw.get("bills_labor")) and rate > 0, "labor_rate": rate,
        "price_list": prices[:80], "sample": text("sample", "", 220),
        "look": text("look", "", 220), "tool": text("tool", "", 160), "scene": text("scene", "", 200),
        "pose": text("pose", "", 180),
    }


def _plain(name):
    words = re.sub(r"[^a-z0-9 ]+", " ", str(name).lower()).split()
    return " ".join(word[:-1] if len(word) > 3 and word.endswith("s") else word for word in words)


def find_price(name, role):
    """(the list's own name, its price) for what the worker said, or None. Plain code, no model."""
    said, best = _plain(name), None
    if not said or not role:
        return None
    for listed, price in role.get("price_list") or []:
        plain = _plain(listed)
        if plain == said:
            return listed, float(price)
        score = difflib.SequenceMatcher(None, plain, said).ratio()
        if plain in said or said in plain:
            score = max(score, 0.8)
        if score >= 0.72 and (best is None or score > best[0]):
            best = (score, listed, float(price))
    return (best[1], best[2]) if best else None


def prompt(role):
    """What the model is told about this job, added to the general instructions."""
    if not role:
        return ""
    lines = ["\nThe worker is a %s at %s." % (role["title"], role["business"]),
             "The notes may be an order taken from a customer instead of a repair: then the parts are "
             "the things ordered."]
    if role.get("price_list"):
        lines.append("Their price list:")
        lines += ["- %s" % name for name, _price in role["price_list"]]
        lines.append("When the worker means something on this list (a nickname, a brand name, a plural), "
                     "use the list's exact name as the description. Still leave unit_price null unless a "
                     "price was said out loud: the price list is applied later, not by you.")
    if not role.get("bills_labor"):
        lines.append("This job does not bill by the hour: labor_hours is null.")
    return "\n".join(lines)


INVENT = (
    "Someone describes their job in one sentence. Make the card for a wrist band that turns what they "
    "say at work into a bill. Honour the job: every job has a hero. "
    "title: the job in two to four plain words. hero: an original hero name of two or three words, never "
    "an existing character, person or brand. power: one short sentence, what this hero does, in the "
    "present tense, starting with a verb, no he or she, no exclamation mark. business: a plausible invented business name. "
    "emoji: one emoji for the job. suit and cape: two hex colours (#rrggbb) that look good together and "
    "suit the job; the suit must not be near white. gear: what is on the hero's head. "
    "bills_labor: true only if this job normally charges by the hour; then labor_rate is a typical "
    "hourly rate in US dollars, else 0. price_list: five to eight things this job sells or charges for, "
    "with plausible US dollar prices. sample: one sentence this worker might say to the band while "
    "working, naming two or three things from the price list, without prices. "
    "Then direct the picture of this hero as a collectible figure, so that nobody could mistake it for another "
    "job: look: face, hair, build, clothes and three or four accessories that only this job has, plus one hero "
    "touch (a cape, scarf or sash); tool: the one signature tool or product of the job, held in one hand, "
    "oversized; scene: a small round base under the feet built from the job's own things; pose: a bold, "
    "exaggerated action pose that leaves one fist free and raised. Each of these is one short phrase, with no "
    "brand names and no existing characters."
)
INVENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"}, "hero": {"type": "STRING"}, "power": {"type": "STRING"},
        "business": {"type": "STRING"}, "emoji": {"type": "STRING"},
        "suit": {"type": "STRING"}, "cape": {"type": "STRING"},
        "gear": {"type": "STRING", "enum": list(GEARS)},
        "bills_labor": {"type": "BOOLEAN"}, "labor_rate": {"type": "NUMBER"},
        "price_list": {"type": "ARRAY", "items": {
            "type": "OBJECT", "properties": {"name": {"type": "STRING"}, "price": {"type": "NUMBER"}},
            "required": ["name", "price"]}},
        "sample": {"type": "STRING"},
        "look": {"type": "STRING"}, "tool": {"type": "STRING"}, "scene": {"type": "STRING"},
        "pose": {"type": "STRING"},
    },
    "required": ["title", "hero", "power", "business", "emoji", "suit", "cape", "gear", "bills_labor",
                 "labor_rate", "price_list", "sample", "look", "tool", "scene", "pose"],
}


def invent(sentence, note=print):
    """A new role from one sentence. With no Gemini key (or no answer) it is a plain card
    with an empty price list: prices then have to be said out loud."""
    sentence = re.sub(r"\s+", " ", str(sentence or "")).strip()[:300]
    if not sentence:
        return None
    raw = {"title": sentence[:48]}
    if os.environ.get("GEMINI_API_KEY"):
        model = os.environ.get("GEMINI_MODEL", "gemini-4-hydrogen")
        body = json.dumps({
            "systemInstruction": {"parts": [{"text": INVENT}]},
            "contents": [{"role": "user", "parts": [{"text": sentence}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": INVENT_SCHEMA},
        }).encode("utf-8")
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
            data=body, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        try:
            with urllib.request.urlopen(request, timeout=40, context=ssl.create_default_context()) as answer:
                data = json.loads(answer.read().decode("utf-8"))
            text = "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"]
                           if not part.get("thought"))
            raw = json.loads(text)
        except Exception as problem:
            note("Gemini could not make the card (%s). Using a plain one." % str(problem)[:160])
            raw = {"title": sentence[:48]}
    else:
        note("No Gemini key: a plain card, with no price list.")
    role = clean(raw, fallback_title=sentence[:48])
    role["id"] = "my-" + role["id"]
    return role


def parse_prices(text):
    """([name, price] rows, lines that were not understood) from 'name, 4.50' lines."""
    rows, missed = [], 0
    for line in str(text or "").splitlines():
        line = line.strip(" \t-•*|")
        if not line:
            continue
        found = re.match(r"^(.*?)[\s,:;|.·…-]*\$?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:usd|dollars?)?\s*$", line, re.I)
        name = found.group(1).strip(" ,:;|.-") if found else ""
        if name and re.search(r"[A-Za-z\u4e00-\u9fff]", name):
            rows.append([name[:60], float(found.group(2).replace(",", "."))])
        else:
            missed += 1
    return rows, missed


PRICES = ("This is a menu or price list pasted by a business, in any layout. Return every item that has a "
          "price, with the price as a plain number. Skip headings, descriptions and anything without a price. "
          "Never invent an item or a price.")
PRICES_SCHEMA = {"type": "OBJECT", "properties": {"items": {"type": "ARRAY", "items": {
    "type": "OBJECT", "properties": {"name": {"type": "STRING"}, "price": {"type": "NUMBER"}},
    "required": ["name", "price"]}}}, "required": ["items"]}


def read_prices(text, note=print):
    """A price list from whatever was pasted. Plain 'name, price' lines are read in code; a
    messier menu goes to Gemini to be laid out, and every row is still checked here."""
    text = str(text or "")[:20000]
    rows, missed = parse_prices(text)
    if (not rows or missed > len(rows)) and os.environ.get("GEMINI_API_KEY") and text.strip():
        try:
            model = os.environ.get("GEMINI_MODEL", "gemini-4-hydrogen")
            body = json.dumps({
                "systemInstruction": {"parts": [{"text": PRICES}]},
                "contents": [{"role": "user", "parts": [{"text": text}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": PRICES_SCHEMA},
            }).encode("utf-8")
            request = urllib.request.Request(
                "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
                data=body, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            with urllib.request.urlopen(request, timeout=60, context=ssl.create_default_context()) as answer:
                data = json.loads(answer.read().decode("utf-8"))
            found = json.loads("".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"]
                                       if not part.get("thought")))
            rows = [[row.get("name"), row.get("price")] for row in found.get("items") or []]
        except Exception as problem:
            note("Gemini could not lay out that menu (%s). Using the lines that read as 'name, price'." %
                 str(problem)[:140])
    return clean({"price_list": rows})["price_list"]
