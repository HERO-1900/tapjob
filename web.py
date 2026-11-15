"""The page that shows what the band is doing: http://127.0.0.1:8765
Only this computer can open it (it listens on 127.0.0.1). Standard library only.
"""
import html
import json
import re
import threading

import keys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).resolve().parent / "static" / "index.html"
import art

ACTIONS = {"page-tap", "send", "discard", "say", "role", "teach-raise", "prices", "figure", "new"}


def start(hub, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):                       # keep the terminal for the job log
            pass

        def reply(self, code, body, kind="text/html; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def same_site(self):
            """A page from somewhere else must not press our buttons."""
            origin = self.headers.get("Origin")
            if not origin:
                return True
            mine = self.server.server_address[1]
            return origin in ("http://127.0.0.1:%d" % mine, "http://localhost:%d" % mine)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self.reply(200, PAGE.read_bytes())
            elif path == "/state":
                self.reply(200, json.dumps(hub.snapshot()), "application/json")
            elif path.startswith("/pay/"):
                self.reply(200, pay_page(hub, path[5:]))
            elif re.match(r"^/heroes/[a-z0-9-]+\.png$", path):       # a hero's picture, painted once
                file = art.FOLDER / path[8:]
                if file.is_file():
                    data = file.read_bytes()
                    self.reply(200, data, art.kind(data))
                else:
                    self.reply(404, "Not painted yet.")
            else:
                self.reply(404, "Not here.")

        def do_POST(self):
            if not self.same_site():
                return self.reply(403, "No.")
            path = self.path.split("?", 1)[0]
            size = min(int(self.headers.get("Content-Length") or 0), 60000)
            raw = self.rfile.read(size) if size else b""
            if path == "/action":
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except ValueError:
                    return self.reply(400, "Not JSON.")
                if body.get("type") not in ACTIONS:
                    return self.reply(400, "Unknown action.")
                hub.inbox.put((body["type"], body.get("value")))
                self.reply(200, "{}", "application/json")
            elif path == "/keys":
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except ValueError:
                    return self.reply(400, "Not JSON.")
                name, value = body.get("name"), str(body.get("value") or "").strip()
                problem = keys.check(name, value)
                if problem:
                    return self.reply(400, json.dumps({"problem": problem}), "application/json")
                hub.inbox.put(("key", (name, value)))
                self.reply(200, "{}", "application/json")
            elif path.startswith("/pay/"):
                number = path[5:]
                if number in getattr(hub.biller, "invoices", {}):
                    hub.inbox.put(("demo-pay", number))
                    self.reply(200, "<body style='font:20px system-ui;padding:3em;text-align:center'>"
                                    "<h1>Paid. Thank you.</h1><p>You can close this page.</p></body>")
                else:
                    self.reply(404, "No such invoice.")
            else:
                self.reply(404, "Not here.")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def pay_page(hub, number):
    draft = getattr(hub.biller, "invoices", {}).get(number)
    if not draft:
        return "<body style='font:18px system-ui;padding:3em'>No such invoice.</body>"
    safe = html.escape
    rows = "".join("<tr><td>%s%s</td><td style='text-align:right'>$%.2f</td></tr>" % (
        safe(item["description"]), " &times; %g" % item["quantity"] if item["quantity"] != 1 else "", item["amount"])
        for item in draft["items"])
    labor = draft.get("labor")
    if labor:
        rows += "<tr><td>Labor %g h at $%.2f/h</td><td style='text-align:right'>$%.2f</td></tr>" % (
            labor["hours"], labor["rate"], labor["amount"])
    return """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Invoice</title>
<body style="font:17px system-ui;max-width:520px;margin:2em auto;padding:0 1em;color:#111">
<p style="color:#666">%s &middot; DEMO invoice (no Stripe key set)</p>
<h1 style="margin:.2em 0">Invoice for %s</h1><p>%s</p>
<table style="width:100%%;border-collapse:collapse" cellpadding="8">%s
<tr style="border-top:2px solid #111;font-weight:700"><td>Total</td><td style="text-align:right">$%.2f</td></tr></table>
<form method="post" action="/pay/%s"><button style="margin-top:1.5em;width:100%%;padding:1em;font-size:1.1em;
background:#0a7d2c;color:#fff;border:0;border-radius:10px">Pay $%.2f (demo)</button></form></body>""" % (
        safe(hub.config["business_name"]), safe(draft["customer"]), safe(draft["summary"]), rows,
        draft["total"], safe(number), draft["total"])
