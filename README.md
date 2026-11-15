# TapJob

**Every job has a hero. Say it, tap it, get paid.** A wrist band for people whose hands are
busy: double-tap, say what you did or what was ordered, double-tap again, and the customer
gets a payment link. The band turns green when they pay. No phone in your hand, no register,
no paperwork at the kitchen table at 9 pm.

It started with a plumber's invoice. The same loop takes a drive-through order, a massage
session or a brake job: pick the job's card (or make one from a single sentence) and the band
brings that job's price list with it.

Built at VexoHacks (Y Combinator, 14 Nov 2026) on the Vexo Open band. Project page: http://tapjob.ipolab.ai

## The loop, all from the wrist

| You do | TapJob does |
|---|---|
| **Double-tap** the band | Starts the job. Microphone on: the band's light is solid blue so people nearby can see it. |
| **Talk while you work**: "Job for Mr. Wang, kitchen sink leaking. Replaced the supply hose, 18 dollars. One angle valve, 25 dollars." | Live speech-to-text. The band also times the job and how long your hands were moving. |
| **Double-tap** | Stops. The words become a draft invoice. The computer reads it back to you. |
| **Double-tap**, or **raise your fist** for a second, to confirm | Creates a Stripe invoice. The customer scans a QR code or opens the link and pays. |
| Nothing | Light goes **green**: paid. The job record (words, times, invoice) is saved. |

## Every job has a hero

The page opens on a card for whoever wears the band. Four come ready-made:

| Card | Job | Bills | Price list |
|---|---|---|---|
| Leakbreaker | Plumber | parts + hours | P-trap, supply line, faucet cartridge ... |
| Lane Captain | Drive-through order taker | items | hamburger, double cheeseburger, fries, shake ... |
| Knot Tamer | Massage therapist | sessions | 60 and 90 minute massage, hot stones ... |
| Torque Titan | Auto mechanic | parts + hours | oil change, brake pads, battery ... |

**Any job, from one sentence.** Type "I fix rockets on the launch pad": Gemini writes the card
(job title, hero name, colours, headgear, a starter price list, whether the job bills by the
hour) and `roles.py` checks every field before it is used. Gemini's image model then paints
the hero once, as a collectible figure with the band on a raised fist (`art.py`); until the
picture arrives, and whenever there is no key, the page shows a figure it draws itself.

**Bring your own price list.** "Edit or upload yours" on the page: paste a menu, pick a text
file, or try a made-up one (burger stand, boba tea shop, sushi bar). Plain `name, price`
lines are read in code; a messier menu is laid out by Gemini and each row is checked.

**The price list makes the money traceable.** The worker says "two double cheeseburgers and a
shake", never a price. Gemini only matches the words to names on the list; the price is then
looked up in plain code and the ticket marks the line `price list`. A price said out loud
still wins, and is not marked. Nothing on the ticket is a number a model made up.

**The page takes the wearer's colours**, and the band's light is drawn on the hero's raised
wrist. Three looks (stage, comic, carbon copy) switch with one button.

**Raise your fist to send.** The band reports which of its six sides points up. Teach it once
("Teach the raised fist", under the hood); after that, holding the fist up for a second while
a draft is waiting sends it. A double-tap still works.

## The dashboard

A bill that is still unpaid does not block the next job. After sending, double-tap the band or
press **New job**: the bill stays open on the **Dashboard** (top right of the page) and the band
is ready again. The dashboard lists every bill that went out as Waiting, Paid or Taken back,
with the totals and a link to each payment page. Open bills are checked in the background, so
an earlier bill turns to Paid by itself. Discard after sending voids the invoice at Stripe.
The list is kept in `jobs/history.json` (not committed).

## Try it without a band

The project page runs the same loop on a pretend band in the browser, with a pretend payment:
http://tapjob.ipolab.ai/#live

## Why a band and not a phone app

Voice-to-invoice phone apps exist. They all start *after* the job: wash your hands, find the
phone, remember what you used. TapJob listens *during* the job, so nothing is recalled from
memory, and it needs no screen:

- **Hands stay on the work.** Gloves, grease, a ladder: a double-tap still works.
- **A tap is a timestamp.** Start and stop are measured, not estimated.
- **The wrist knows when you worked.** If you do not say the hours, the band's clock bills
  the time on site, in quarter hours, and says so on the invoice.
- **One bit of feedback is enough.** The only thing a tradesperson needs to know before
  packing up is "did they pay?" That is the green light.

## How it works

```
 Vexo Open band                      laptop (this repo)                         cloud
 ───────────────                     ───────────────────                        ─────
 double-tap  ───── Bluetooth ─────▶  app.py   state machine: idle → recording
 microphone  ───── Opus audio ────▶           → draft → sent → paid
 wrist motion ──── activity ──────▶    │
 light  ◀───────── LED commands ───    ├─ speech (kit helper) ─────────────▶ Deepgram  live speech-to-text
                                       ├─ brain.py   words → fields ────────▶ Gemini 4  structured output
                                       │             fields → money: plain code, no model
                                       ├─ billing.py draft → invoice ───────▶ Stripe    test-mode invoice + pay page
                                       ├─ voice.py   reads the draft aloud ─▶ Deepgram  text-to-speech (or macOS `say`)
                                       └─ web.py     http://127.0.0.1:8765   live words, draft, QR code
```

Design rules we kept:

- **The model never does arithmetic and never sets a price.** Gemini only pulls out what was
  said (customer, parts, prices, hours) and matches names to the price list. Prices from the
  list, quantities times prices, labor and the total are computed in `brain.py` and `roles.py`.
- **Nothing is invented.** A part with no spoken price goes on the draft at $0 with a warning.
- **A human confirms before money moves.** The third double-tap (or the Send button) is the
  only way an invoice is created.
- **Test mode only.** `billing.py` refuses Stripe live keys.
- **It degrades instead of failing.** No Gemini key: OpenAI through the kit's helper, then
  simple offline rules. No Stripe key: a built-in demo pay page. No Deepgram key: type the
  words on the page. The loop closes in every case.

## Sponsor technology used

- **Vexo Open band**: double-tap events, orientation events (the raised fist), Opus microphone
  stream, activity stream, LED, over the USB cable or Bluetooth.
- **Deepgram**: live speech-to-text (through the kit's `speech.py`), text-to-speech for the read-back.
- **Google Gemini 4** (`gemini-4-hydrogen` by default): structured output three times: words to
  invoice fields, one sentence to a job card, a pasted menu to a price list. Gemini's image
  model (`gemini-3.1-flash-image`) paints the hero for each job.
- **Stripe**: customers, invoice items, invoices, hosted payment page, in test mode.

Not used: Pipecat. The voice loop here is a small state machine of our own.

## Run it

You need Python 3.9 or newer.

```bash
git clone <this repo> tapjob && cd tapjob
git clone https://github.com/VexoAI-Org/vexo-open-kit.git     # the band library, used as it is
cp env.example .env                                            # then paste your keys into .env
```

**No band, no keys (30 seconds):**

```bash
python3 app.py --sim --demo          # the whole loop runs by itself and ends with PAID
python3 app.py --sim                 # or drive it yourself: open http://127.0.0.1:8765
```

**With your band** (42 = the number on your band's bag):

```bash
python3 -m pip install bleak pyserial   # Bluetooth and the USB cable, for Python
python3 app.py 42                    # double-tap the band first: its light blinks blue
```

Close the kit's dashboard tab first: the band takes one Bluetooth connection at a time.

On a Mac you can skip the commands: double-click `start.command` (it sets up Python, gets the kit,
reads `band_number` from `config.json`, and starts; missing keys can be typed into the Keys box on the page, which saves them in `.env`), or `demo.command` for the pretend band.

**Paying the test invoice:** on the Stripe page use card `4242 4242 4242 4242`, any future
date, any CVC.

### Keys (`.env`, never committed)

| Key | What for | Without it |
|---|---|---|
| `DEEPGRAM_API_KEY` | speech-to-text, and the voice that reads the draft | type the words on the page; macOS `say` speaks |
| `GEMINI_API_KEY` | words to invoice fields | OpenAI if `OPENAI_API_KEY` is set, else offline rules |
| `STRIPE_SECRET_KEY` | the invoice and pay page (must start with `sk_test_`) | built-in demo pay page |

### Settings (`config.json`, optional)

Copy `config.example.json` to `config.json`: business name, hourly rate, tap sensitivity.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Ten checks, no band, keys or internet needed. Gemini and Stripe are answered by stand-ins,
so the tests cover what we send and how we read the answers. The last one runs the whole
loop against the kit's pretend band.

## What is real and what is not

- Run end to end on a real band (Vexo-HACK-51, 14 Nov 2026), first over the USB cable and then
  over Bluetooth with no cable: double-tap, live speech-to-text, Gemini's draft, a price list
  order with every line priced in code, a Stripe test invoice, payment with the test card, the
  PAID state. Also on the real services: a job card from one sentence, and the hero pictures
  from Gemini's image model.
- The raised fist was taught once and has sent two drafts on the real band (one of them over
  Bluetooth). Two is not a test: expect it to need tuning on other wrists.
- Found the hard way: a loudspeaker next to the band can shake it into a double-tap. Taps are
  ignored while the computer is speaking.
- Tuned by guess, not measured: the tap sensitivity and the "hands working" motion threshold
  (`config.json`). A loud job site will need a harder tap setting.
- Not solved: speech recognition next to a compressor; two people talking; parts catalogues
  and tax. The draft is always shown and read back before it is sent for this reason.
- The QR code image comes from `api.qrserver.com`, which therefore sees the invoice link.

## The microphone

While a job is recorded the band's light is solid blue and the sound goes to Deepgram.
The microphone is on only between two double-taps, never in the background. Tell the people
near you. Saved job records (`jobs/`) stay on this computer and are not committed.

## Who it is for, and how it would be sold

- **User and buyer are the same person:** the owner-operator plumber, electrician, HVAC or
  appliance tech with one to three people, who does the invoicing personally, at night.
- **Value:** every part billed (nothing forgotten), invoice out before the van leaves, paid
  the same day.
- **Wedge:** a band plus a subscription; invoices land in Stripe first, then in the tools
  they already use (QuickBooks, Jobber, Housecall Pro) through their APIs.
- **First test of demand:** ten tradespeople, one week, count invoices sent from the
  driveway instead of the kitchen table.

## Files

| File | What it is |
|---|---|
| `app.py` | The hub: band, state machine, main loop |
| `brain.py` | Words to fields (Gemini / OpenAI / rules), fields to money |
| `roles.py` | The jobs: price lists, the card from one sentence, the price lookup, reading a pasted menu |
| `art.py` | The hero pictures, from Gemini's image model |
| `billing.py` | Stripe test-mode invoice, or the demo pay page |
| `voice.py` | Speaks the draft |
| `web.py`, `static/index.html` | The live page |
| `keys.py` | Saves keys typed on the page into `.env` |
| `link.py` | Finds the band: USB cable if plugged in, else Bluetooth with retries and plain-words diagnosis |
| `tests/` | Offline tests |
| `AGENTS.md` | Notes for AI coding agents working on this repo |

MIT licence.
