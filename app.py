#!/usr/bin/env python3
"""TapJob: a wrist band that turns spoken job notes into a paid invoice.

    python3 app.py 42                  your band (number on the bag) over Bluetooth
    python3 app.py 42 --usb            the same band on the USB cable
    python3 app.py --sim               a pretend band: drive it from the web page
    python3 app.py --sim --say "..."   pretend band, typed words instead of the microphone
    python3 app.py --sim --demo        the whole loop runs by itself, then the program ends

The loop, all from the wrist:
    double-tap   start the job: microphone on (the band's light is solid blue)
    talk         say what you do, the parts you use and what they cost
    double-tap   stop: the notes become a draft invoice, read back to you
    double-tap   confirm: the invoice goes to Stripe, the customer gets a payment link
    green light  the customer has paid

Open http://127.0.0.1:8765 to watch it: live words, the draft, the payment link.
"""
import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE / "vexo-open-kit"
if not (KIT / "python" / "vexo_open").is_dir():
    sys.exit("The Vexo kit is missing. In this folder run:\n"
             "    git clone https://github.com/VexoAI-Org/vexo-open-kit.git")
sys.path.insert(0, str(KIT / "examples" / "python"))     # speech.py: sound -> Deepgram
sys.path.insert(0, str(KIT / "python"))                  # vexo_open: the band library

from vexo_open.sync import Band, VexoError               # noqa: E402
from vexo_open.transports.sim import SimTransport        # noqa: E402

import billing                                           # noqa: E402
import roles
import art
import brain                                             # noqa: E402
import keys                                              # noqa: E402
import link                                              # noqa: E402
import voice                                             # noqa: E402
import web                                               # noqa: E402

DEFAULTS = {
    "business_name": "TapJob Demo Plumbing",
    "labor_rate": 95.0,            # per hour
    "currency": "usd",
    "customer_email": "",          # where Stripe would send the invoice, if you want that
    "tap_threshold_g": 1.0,        # higher = a harder tap is needed (0.2 .. 8)
    "active_motion_g": 0.04,       # wrist motion above this counts as "hands working" (a guess: tune it)
    "ignore_taps_after_start_s": 3.0,
    "ignore_taps_after_draft_s": 4.0,   # a second tap right after "stop" must not send the invoice
    "raise_face": "",              # which side of the band points up when the fist is raised ("+x" .. "-z");
                                   # taught from the page ("Teach the raised fist"), kept in config.json
    "raise_hold_s": 0.7,           # hold the fist up this long (after the draft shows) to send it
}

SAMPLE_SAY = ("Job for Mr. Wang, kitchen sink is leaking under the cabinet. "
              "Replaced the supply hose, 18 dollars. Replaced one angle valve, 25 dollars. "
              "Labor one and a half hours.")


def load_env():
    """KEY=value lines from .env (in the folder you start in, or next to this file) into the
    environment. Keys never go anywhere else: not into code, not into git."""
    for folder in (Path.cwd(), HERE):
        try:
            for line in (folder / ".env").read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                name, _, value = line.partition("=")
                if name.strip() and value.strip() and not line.startswith("#"):
                    os.environ.setdefault(name.strip(), value.strip().strip("'\""))
        except OSError:
            pass


def load_config():
    config = dict(DEFAULTS)
    try:
        config.update(json.loads((HERE / "config.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return config


class Hub:
    """Everything between the band and the invoice. One job at a time."""

    def __init__(self, band, args, config):
        self.band = band
        self.args = args
        self.config = config
        self.sim = band.transport if args.transport == "sim" else None
        self.inbox = queue.Queue()           # what handlers and the web page report; the main loop acts
        self.lock = threading.Lock()
        self.ears = None                     # the speech engine while a job is being recorded
        self.typed = []                      # words typed on the page or given with --say
        self.last_tap = 0.0
        self.paid_demo = set()               # invoices paid on the built-in demo pay page
        self.next_poll = 0.0
        self.paid_at = 0.0
        self.biller = billing.create(args.port)
        self.roles = [dict(role) for role in roles.PRESETS]          # the ready-made jobs, then invented ones
        self.roles[0].update(business=config["business_name"], labor_rate=float(config["labor_rate"]))
        self.role = self.roles[0]
        kept = config.get("role")                                    # who wore the band last time
        if isinstance(kept, dict) and kept.get("id"):
            known = next((r for r in self.roles if r["id"] == kept["id"]), None)
            if known is None:                                        # a card made from a sentence
                known = roles.clean(kept)
                known["id"] = str(kept["id"])[:60]
                self.roles.append(known)
            elif kept.get("price_list"):                             # a ready-made job with the wearer's own menu
                known["price_list"] = roles.clean(kept)["price_list"]
            self.role = known
        self.figure = config.get("figure") if config.get("figure") in art.FIGURES else "person"
        for role in self.roles:
            role["art"] = art.url(role, self.figure)         # the painted picture, if there is one from before
            role["backdrop"] = art.backdrop(role)
        self.to_paint = queue.Queue()        # jobs waiting for their picture (one painter, off the main loop)
        threading.Thread(target=self.painter, daemon=True).start()
        self.face = None                     # which side of the band points up (from its orientation events)
        self.face_at = 0.0
        self.teach_at = 0.0                  # when to read the face for "this is my raised fist"
        self.draft_at = 0.0
        self.sent_at = 0.0
        self.history = self.load_history()   # every bill that went out: waiting, paid or taken back
        threading.Thread(target=self.watcher, daemon=True).start()
        self.state = {
            "phase": "idle", "band": band.name, "link": args.transport,
            "led": {"color": "#ffffff", "pattern": "breathe", "note": "ready"},
            "started": None, "stopped": None, "active_seconds": 0,
            "transcript": [], "interim": "", "draft": None, "invoice": None,
            "log": [], "services": {"speech": "off", "brain": brain.provider(), "billing": self.biller.label},
            "business": self.role["business"], "role": self.role, "roles": self.roles, "making_role": False,
            "face": None, "raise_face": config.get("raise_face") or "", "teaching": False,
            "samples": roles.SAMPLES, "painting": [], "figure": self.figure, "payee": "",
            "history": self.history[:40],
        }

    # ---- small helpers -------------------------------------------------------------------

    def note(self, text):
        print(time.strftime("%H:%M:%S"), text, flush=True)
        with self.lock:
            self.state["log"] = (self.state["log"] + [{"t": time.time(), "text": text}])[-30:]

    def set(self, **changes):
        with self.lock:
            self.state.update(changes)

    def snapshot(self):
        with self.lock:
            shot = json.loads(json.dumps(self.state))
        shot["keys"] = keys.status()                         # saved or missing, never the values
        if shot["phase"] == "recording" and shot["started"]:
            shot["elapsed"] = round(time.time() - shot["started"])
        elif shot["started"] and shot["stopped"]:
            shot["elapsed"] = round(shot["stopped"] - shot["started"])
        return shot

    def led(self, color, pattern="solid", note="", **more):
        """Set the band's one light. While the microphone is on the band refuses: that is its rule."""
        self.set(led={"color": color, "pattern": pattern, "note": note})
        try:
            self.band.set_led(color, pattern=pattern, **more)
        except VexoError:
            pass

    def say(self, text):
        self.note("VOICE: " + text)
        if not self.args.quiet:
            voice.speak(text)

    # ---- what the band tells us (handlers: only note it, the main loop does the work) -----

    def on_double_tap(self, _event):
        self.inbox.put(("tap", None))

    def on_orientation(self, event):
        face = getattr(event, "face", None)
        if face is None and isinstance(event, dict):
            face = event.get("face")
        self.inbox.put(("face", face))

    def on_audio(self, packet):
        ears = self.ears
        if ears is not None:
            try:
                ears.feed(packet.opus, packet.seq)
            except Exception as problem:                     # a speech problem must not stop the band
                self.inbox.put(("speech-problem", str(problem)))

    def on_activity(self, reading):
        moving = getattr(reading, "state", "still") != "still" or \
            (getattr(reading, "motion", 0) or 0) >= self.config["active_motion_g"]
        if moving and self.state["phase"] == "recording":
            with self.lock:
                self.state["active_seconds"] += 1

    def on_text(self, text, final):                          # called by the speech engine, another thread
        with self.lock:
            if final:
                if text:
                    self.state["transcript"].append(text)
                self.state["interim"] = ""
            else:
                self.state["interim"] = text

    # ---- the job ------------------------------------------------------------------------

    def tap(self, by_hand=False):
        now = time.time()
        if now - self.last_tap < 1.2:                        # one double-tap, reported twice
            return
        if not by_hand and voice.speaking() and self.state["phase"] != "recording":
            return                                           # the loudspeaker shook the band: not a tap
        self.last_tap = now
        phase = self.state["phase"]
        if phase == "idle":
            self.start_job()
        elif phase == "recording":
            if now - self.state["started"] < self.config["ignore_taps_after_start_s"]:
                return
            self.stop_job()
        elif phase == "draft":
            if now - getattr(self, "draft_at", 0) < self.config["ignore_taps_after_draft_s"]:
                return                                       # still reading the draft back
            self.send_invoice()
        elif phase == "sent":
            if now - self.sent_at > 4:                       # the bill stays open on the dashboard
                self.next_job()
        elif phase == "paid":
            self.reset()

    def start_job(self):
        self.typed = list(filter(None, [self.args.say]))
        self.set(phase="recording", started=time.time(), stopped=None, active_seconds=0,
                 transcript=[], interim="", draft=None, invoice=None)
        self.ears = None
        if not self.args.say:
            try:
                import speech                                # the kit's helper: Deepgram, nothing to install
                self.ears = speech.create().start(self.on_text)
                self.state["services"]["speech"] = self.ears.label
            except Exception as problem:
                self.state["services"]["speech"] = "typed words only"
                self.note("No live transcript: %s" % problem)
                self.note("Type the words on the page instead, or start with --say \"...\".")
        else:
            self.state["services"]["speech"] = "typed words (--say)"
        try:
            self.band.configure(audio=True, activity=True)   # mic on: the band's light goes solid blue
        except VexoError as problem:
            self.note("The band did not start the microphone: %s" % problem)
        self.set(led={"color": "#0050ff", "pattern": "solid", "note": "microphone on"})
        self.note("JOB STARTED. Talk while you work. Double-tap to stop.")

    def stop_job(self):
        self.set(stopped=time.time())
        try:
            self.band.configure(audio=False)                 # mic off, the light is ours again
        except VexoError:
            pass
        heard = ""
        if self.ears is not None:
            try:
                heard = self.ears.stop() or ""
            except Exception as problem:
                self.note("Speech engine: %s" % problem)
                heard = " ".join(self.state["transcript"])
            self.ears = None
        words = " ".join(filter(None, [heard] + self.typed)).strip()
        self.set(phase="thinking", interim="", transcript=[words] if words else [])
        self.led("#ff9900", "blink", "working on the invoice", period=400)
        self.note("JOB STOPPED after %d s. Heard: %s" % (self.snapshot().get("elapsed", 0), words or "(nothing)"))
        if not words:
            self.say("I did not hear anything. Double tap to start again.")
            self.reset()
            return
        shot = self.snapshot()
        draft = brain.make_draft(words, self.config, on_site_seconds=shot.get("elapsed", 0),
                                 active_seconds=shot["active_seconds"], note=self.note, role=self.role)
        self.state["services"]["brain"] = draft["provider"]
        self.set(phase="draft", draft=draft)
        self.draft_at = time.time()
        self.led("#ff9900", "breathe", "draft ready: double-tap to send", period=1500)
        self.say(brain.read_back(draft) + (" Fist up, or double tap, to send." if self.config.get("raise_face")
                                           else " Double tap to send."))

    def send_invoice(self):
        draft = self.state["draft"]
        if not draft:
            return
        self.set(phase="sending")
        try:
            invoice = self.biller.create_invoice(draft, self.config)
        except billing.BillingError as problem:
            self.note("Billing: %s" % problem)
            self.set(phase="draft")
            self.led("#ff0000", "flash", "could not send", period=600)
            self.say("I could not send the invoice. Look at the screen.")
            return
        self.set(phase="sent", invoice=invoice)
        self.sent_at = time.time()
        self.keep(draft, invoice)
        self.next_poll = time.time() + 2
        self.led("#ffffff", "blink", "sent: waiting for payment", period=900)
        self.note("INVOICE SENT (%s): %s" % (self.biller.label, invoice["url"]))
        self.say("Invoice sent. %s." % brain.money(draft["total"], self.config["currency"]))

    def check_paid(self):
        invoice = self.state["invoice"]
        if not invoice or time.time() < self.next_poll:
            return
        self.next_poll = time.time() + 2
        paid = invoice["id"] in self.paid_demo
        if not paid:
            try:
                paid = self.biller.is_paid(invoice["id"])
            except billing.BillingError as problem:
                self.note("Billing: %s" % problem)
        if paid:
            invoice = dict(invoice, paid=True)
            self.set(phase="paid", invoice=invoice)
            self.paid_at = time.time()
            self.mark(invoice["id"], "paid")
            self.led("#00ff44", "solid", "paid")
            self.note("PAID.")
            self.say("Payment received.")
            self.archive()

    def archive(self):
        shot = self.snapshot()
        folder = HERE / "jobs"
        folder.mkdir(exist_ok=True)
        name = time.strftime("job-%Y%m%d-%H%M%S.json", time.localtime(shot["started"] or time.time()))
        record = {key: shot.get(key) for key in ("band", "started", "stopped", "elapsed", "active_seconds",
                                                  "transcript", "draft", "invoice", "services")}
        (folder / name).write_text(json.dumps(record, indent=2), encoding="utf-8")
        self.note("Job record saved: jobs/%s" % name)

    def discard(self):
        if self.state["phase"] in ("draft", "sent"):
            invoice = self.state.get("invoice")
            if self.state["phase"] == "sent" and invoice and hasattr(self.biller, "void"):
                try:                                         # taking a sent bill back, for real
                    self.biller.void(invoice["id"])
                    self.mark(invoice["id"], "void")
                    self.note("The invoice was taken back: Stripe has voided it.")
                except billing.BillingError as problem:
                    self.note("Could not void the invoice at Stripe: %s" % problem)
            self.note("Discarded.")
            self.reset()

    def use_role(self, value):
        """Another job puts the band on. Only between jobs, never in the middle of one."""
        value = value if isinstance(value, dict) else {}
        if self.state["phase"] != "idle":
            self.note("Finish or discard this job before changing who wears the band.")
            return
        role = next((r for r in self.roles if r["id"] == value.get("id")), None)
        if role is None and value.get("sentence"):
            self.set(making_role=True)
            self.note("Making a hero card for: %s" % str(value["sentence"])[:120])
            try:
                role = roles.invent(value["sentence"], note=self.note)
            finally:
                self.set(making_role=False)
            if role:
                taken = {r["id"] for r in self.roles}
                while role["id"] in taken:
                    role["id"] += "-2"
                role["backdrop"] = art.backdrop(role)
                self.roles.append(role)
        if not role:
            return
        self.role = role
        self.set(role=role, roles=self.roles, business=role["business"])
        self.remember(role=role)
        self.paint(role)
        self.note("Now wearing the band: %s, %s at %s (%d prices on the list)." % (
            role["hero"], role["title"], role["business"], len(role["price_list"])))
        self.say("%s. Ready." % role["hero"])

    def ask_payee(self):
        """Off the main loop: whose Stripe account is this? Shown on the page."""
        biller = self.biller

        def work():
            name = biller.payee() if hasattr(biller, "payee") else "the built-in demo pay page (no Stripe key)"
            self.set(payee=name)
        threading.Thread(target=work, daemon=True).start()

    def painter(self):
        """Its own thread: asks the image model for one picture at a time, never holds up the band."""
        while True:
            role, figure = self.to_paint.get()
            try:
                where = art.paint(role, note=self.note, figure=figure)
            except Exception as problem:                     # a picture must never stop a job
                self.note("Picture: %s" % str(problem)[:160])
                where = None
            self.inbox.put(("art", (role["id"], where, figure)))

    def paint(self, role):
        if role.get("art") or not os.environ.get("GEMINI_API_KEY") or role["id"] in self.state["painting"]:
            return
        self.set(painting=self.state["painting"] + [role["id"]])
        self.to_paint.put((dict(role), self.figure))

    def use_figure(self, value):
        """Paint the heroes as women, men, or leave it open. Pictures are kept for each choice."""
        if value not in art.FIGURES:
            return
        self.figure = value
        self.remember(figure=value)
        for role in self.roles:
            role["art"] = art.url(role, value)
        self.set(figure=value, roles=self.roles, role=self.role, painting=[])
        for role in [self.role] + [r for r in self.roles if r is not self.role]:
            self.paint(role)

    def use_prices(self, value):
        """The wearer's own menu or price list, pasted on the page."""
        if self.state["phase"] != "idle":
            self.note("Finish or discard this job before changing the price list.")
            return
        rows = roles.read_prices((value or {}).get("text") if isinstance(value, dict) else value, note=self.note)
        if not rows:
            self.note("No prices found in that text. One item per line works: name, price.")
            self.say("I found no prices in that.")
            return
        self.role["price_list"] = rows
        self.set(role=self.role, roles=self.roles)
        self.remember(role=self.role)
        self.note("Price list saved for %s: %d items." % (self.role["business"], len(rows)))
        self.say("Price list saved. %d items." % len(rows))

    def remember(self, **settings):
        """Kept in config.json for the next start (the file is not in git)."""
        try:
            path = HERE / "config.json"
            saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            saved.update(settings)
            path.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except (OSError, ValueError) as problem:
            self.note("Could not save that in config.json: %s" % problem)

    def gestures(self):
        """The raised fist: taught once, then it sends the draft. Called from the main loop."""
        now = time.time()
        if self.teach_at and now >= self.teach_at:
            self.teach_at = 0.0
            self.set(teaching=False)
            if not self.face:
                self.note("The band has not said which way it points yet. Move your arm, then teach again.")
                self.say("I could not feel the band. Try again.")
                return
            if now - self.face_at < 0.8 or self.face == getattr(self, "teach_from", None):
                self.note("Not learned: the band pointed %s up %s. Point the fist straight up, hold it still, "
                          "and teach again." % (self.face, "the whole time, the same as before"
                                                if self.face == getattr(self, "teach_from", None) else "only just now"))
                self.say("I did not get that. Fist straight up, hold still, and teach again.")
                return
            self.config["raise_face"] = self.face
            self.set(raise_face=self.face)
            self.remember(raise_face=self.face)
            self.note("Raised fist learned: the band points %s up. Hold it up for a second to send a draft." % self.face)
            self.say("Got it. Raise your fist to send.")
            return
        raised = self.config.get("raise_face")
        if (raised and self.state["phase"] == "draft" and self.face == raised
                and now - max(self.face_at, self.draft_at) >= float(self.config["raise_hold_s"])):
            self.note("Fist raised: sending.")
            self.send_invoice()

    # ---- the dashboard: every bill that went out, and whether it has been paid -------------

    def load_history(self):
        try:
            jobs = json.loads((HERE / "jobs" / "history.json").read_text(encoding="utf-8"))
            return [job for job in jobs if isinstance(job, dict) and job.get("id")][:200]
        except (OSError, ValueError):
            return []

    def save_history(self):
        with self.lock:
            self.state["history"] = [dict(job) for job in self.history[:40]]
        try:
            folder = HERE / "jobs"
            folder.mkdir(exist_ok=True)
            (folder / "history.json").write_text(json.dumps(self.history[:200], indent=2), encoding="utf-8")
        except OSError as problem:
            self.note("Could not save the dashboard: %s" % problem)

    def keep(self, draft, invoice):
        self.history.insert(0, {
            "id": invoice["id"], "url": invoice.get("url", ""), "total": draft.get("total", 0),
            "customer": draft.get("customer") or "", "summary": draft.get("summary") or "",
            "lines": len(draft.get("items") or []), "business": self.role["business"], "hero": self.role.get("hero", ""),
            "at": time.time(), "status": "sent", "paid_at": None})
        self.save_history()

    def mark(self, number, status):
        for job in self.history:
            if job["id"] == number and job["status"] != status:
                job["status"] = status
                job["paid_at"] = time.time() if status == "paid" else None
                self.save_history()
                return job
        return None

    def next_job(self):
        """Leave a sent bill open on the dashboard and get ready for the next job."""
        if self.state["phase"] == "sent":
            self.note("That bill stays open on the dashboard. Ready for the next job.")
        self.reset()

    def watcher(self):
        """Off the main loop: ask whether the bills left open have been paid."""
        while True:
            time.sleep(4)
            current = (self.state.get("invoice") or {}).get("id")
            for job in [job for job in self.history[:12] if job["status"] == "sent" and job["id"] != current]:
                try:
                    if job["id"] in self.paid_demo or self.biller.is_paid(job["id"]):
                        self.inbox.put(("job-paid", job["id"]))
                except Exception:                            # no network just now: ask again next time
                    pass

    def job_paid(self, number):
        job = self.mark(number, "paid")
        if job:
            self.note("PAID (an earlier bill): %s" % brain.money(job["total"], self.config["currency"]))
            if self.state["phase"] == "idle":
                self.say("An earlier bill was paid.")

    def reset(self):
        self.set(phase="idle", started=None, stopped=None, active_seconds=0, transcript=[], interim="",
                 draft=None, invoice=None)
        self.led("#ffffff", "breathe", "ready: double-tap to start a job", brightness=0.2, period=4000)

    # ---- the main loop ------------------------------------------------------------------

    def act(self, kind, value):
        if kind == "tap":
            self.tap()
        elif kind == "page-tap":                             # the button on the page
            if self.sim is not None:
                self.sim.tap("double-tap")                   # through the real protocol, like a wrist
            else:
                self.tap(by_hand=True)                       # a click on the page is never the loudspeaker
        elif kind == "say" and self.state["phase"] == "recording" and value:
            self.typed.append(str(value)[:2000])
            with self.lock:
                self.state["transcript"].append(str(value)[:2000])
        elif kind == "send" and self.state["phase"] == "draft":
            self.send_invoice()
        elif kind == "discard":
            self.discard()
        elif kind == "new" and self.state["phase"] in ("sent", "paid"):
            self.next_job()
        elif kind == "job-paid":
            self.job_paid(value)
        elif kind == "role":
            self.use_role(value)
        elif kind == "face" and value is not None:
            self.face, self.face_at = str(value), time.time()
            self.set(face=self.face)
        elif kind == "teach-raise":
            self.teach_at = time.time() + 5.0
            self.teach_from = self.face                      # how the band lies before the fist goes up
            self.set(teaching=True)
            self.say("Raise your fist to the sky and hold it.")
        elif kind == "prices":
            self.use_prices(value)
        elif kind == "figure":
            self.use_figure(value)
        elif kind == "art" and value:
            number, where, figure = value
            for role in self.roles:
                if role["id"] == number and where and figure == self.figure:
                    role["art"] = where
            self.set(roles=self.roles, role=self.role, painting=[n for n in self.state["painting"] if n != number])
        elif kind == "demo-pay" and value:
            self.paid_demo.add(value)
            self.next_poll = 0
        elif kind == "speech-problem":
            self.note("Speech engine: %s" % value)
        elif kind == "key" and value:
            self.use_key(*value)

    def use_key(self, name, value):
        """A key typed on the page: into .env, and in use at once (no restart)."""
        try:
            keys.save(name, value)
        except (ValueError, OSError) as problem:
            self.note("Key not saved: %s" % problem)
            return
        if name == "STRIPE_SECRET_KEY" and self.state["phase"] in ("idle", "recording", "thinking", "draft"):
            try:
                self.biller = billing.create(self.args.port)
            except SystemExit as problem:
                self.note(str(problem))
        self.state["services"]["brain"] = brain.provider()
        self.state["services"]["billing"] = self.biller.label
        self.note("Key saved in .env: %s" % name)
        if name == "STRIPE_SECRET_KEY":
            self.ask_payee()

    def run(self, seconds=None):
        band = self.band
        band.on("double-tap", self.on_double_tap)
        band.on("audio", self.on_audio)
        band.on("activity", self.on_activity)
        band.on("orientation", self.on_orientation)
        try:
            band.set_events(kinds=["double-tap", "motion", "orientation"],
                            tap_threshold=self.config["tap_threshold_g"])
        except (VexoError, TypeError, ValueError):
            pass
        band.configure(events=True, activity=True)
        self.reset()
        self.note("Connected to %s. Double-tap the band to start a job." % band.name)
        for role in [self.role] + [r for r in self.roles if r is not self.role]:
            self.paint(role)                                 # pictures for the cards, the wearer's first
        self.ask_payee()
        end = time.time() + seconds if seconds else None
        while band.connected or getattr(band, "reconnecting", False):
            band.wait(0.2)
            while True:
                try:
                    kind, value = self.inbox.get_nowait()
                except queue.Empty:
                    break
                self.act(kind, value)
            self.gestures()
            if self.state["phase"] == "sent":
                self.check_paid()
            if self.state["phase"] == "paid" and self.args.demo:
                return 0
            if self.state["phase"] == "paid" and time.time() - self.paid_at > 25:
                self.reset()
            if end and time.time() > end:
                return 1
        return 0


def demo_script(hub):
    """--demo: a pretend tradesperson. Start, talk, stop, confirm, and the customer pays."""
    def wait_for(phase, seconds=30):
        end = time.time() + seconds
        while hub.state["phase"] != phase and time.time() < end:
            time.sleep(0.1)
        return hub.state["phase"] == phase

    time.sleep(1.0)
    hub.inbox.put(("page-tap", None))
    if not wait_for("recording"):
        return
    time.sleep(hub.config["ignore_taps_after_start_s"] + 0.5)
    hub.inbox.put(("page-tap", None))
    if not wait_for("draft", 60):
        return
    time.sleep(hub.config["ignore_taps_after_draft_s"] + 0.5)
    while voice.speaking():                                  # let it finish reading the draft
        time.sleep(0.2)
    hub.inbox.put(("page-tap", None))
    if not wait_for("sent", 30):
        return
    time.sleep(1.0)
    if hub.biller.label.startswith("demo"):
        hub.inbox.put(("demo-pay", hub.state["invoice"]["id"]))


def main():
    parser = argparse.ArgumentParser(description="TapJob: spoken job notes -> paid invoice, from a wrist band.")
    parser.add_argument("number", nargs="?", type=int, help="the number on your band's bag, e.g. 42")
    parser.add_argument("--sim", dest="transport", action="store_const", const="sim", default="ble",
                        help="a pretend band (no hardware)")
    parser.add_argument("--usb", dest="transport", action="store_const", const="serial", help="the USB cable")
    parser.add_argument("--say", help="typed words instead of the microphone (no Deepgram key needed)")
    parser.add_argument("--demo", action="store_true", help="with --sim: run the whole loop once, then end")
    parser.add_argument("--port", type=int, default=8765, help="the web page's port (default 8765)")
    parser.add_argument("--quiet", action="store_true", help="do not speak, only print")
    args = parser.parse_args()
    load_env()
    if args.demo:
        args.transport = "sim"
        args.say = args.say or SAMPLE_SAY
    config = load_config()
    if args.number is None and args.transport != "sim":
        saved = str(os.environ.get("BAND_NUMBER") or config.get("band_number") or "").strip()
        if saved.isdigit():                                         # "band_number": 51 in config.json
            args.number = int(saved)
        else:
            parser.error("add your band number, or --sim for a pretend band:   python3 app.py 42   or   "
                         "python3 app.py --sim   (or put \"band_number\": 42 in config.json)")
    number = args.number or 42
    if args.transport == "sim":
        band = Band.connect(number, transport=SimTransport(number, auto_tap=False))
    else:
        band, args.transport = link.connect(number, args.transport)
        print("连上了：%s（%s）" % (band.name, "USB" if args.transport == "serial" else "蓝牙"))

    hub = Hub(band, args, config)
    server = web.start(hub, args.port)
    args.port = server.server_address[1]
    hub.biller.port = args.port
    print("Open http://127.0.0.1:%d in a browser." % args.port)
    if args.demo:
        threading.Thread(target=demo_script, args=(hub,), daemon=True).start()
    code = 0
    try:
        code = hub.run(seconds=90 if args.demo else None)
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        try:
            band.disconnect()
        except Exception:
            pass
        server.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
