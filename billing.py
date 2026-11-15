"""A draft -> a real invoice the customer can pay.

With STRIPE_SECRET_KEY (a TEST key, sk_test_...): a Stripe invoice with a hosted payment
page. Pay it with Stripe's test card 4242 4242 4242 4242, any future date, any CVC.
Without a key: a demo pay page served by this program, so the loop still closes.

Live keys are refused on purpose: this is a hackathon project and must not move real money.
Plain HTTPS from the standard library: nothing to install.
"""
import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://api.stripe.com/v1/"


class BillingError(Exception):
    pass


def create(port):
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key:
        return DemoBilling(port)
    if not (key.startswith("sk_test_") or key.startswith("rk_test_")):
        raise SystemExit("STRIPE_SECRET_KEY is not a test key. Use the one that starts with sk_test_ "
                         "(Stripe dashboard, test mode). This program refuses live keys.")
    return StripeBilling(key)


class DemoBilling:
    """No Stripe key: the invoice lives in this program and is paid on its own page."""
    label = "demo pay page (no Stripe key)"

    def __init__(self, port):
        self.port = port
        self.invoices = {}

    def create_invoice(self, draft, config):
        number = "demo_" + uuid.uuid4().hex[:10]
        self.invoices[number] = draft
        return {"id": number, "url": "http://127.0.0.1:%d/pay/%s" % (self.port, number),
                "total": draft["total"], "provider": self.label, "paid": False}

    def is_paid(self, _number):
        return False                                   # the hub hears about demo payments itself


class StripeBilling:
    label = "Stripe (test mode)"

    def __init__(self, key):
        self.key = key
        self.port = None

    def _call(self, method, path, fields=None):
        data = urllib.parse.urlencode(fields or {}).encode("utf-8") if method == "POST" else None
        request = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": "Basic " + base64.b64encode((self.key + ":").encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as answer:
                return json.loads(answer.read().decode("utf-8"))
        except urllib.error.HTTPError as problem:
            try:
                message = json.loads(problem.read().decode("utf-8"))["error"]["message"]
            except Exception:
                message = "HTTP %s" % problem.code
            raise BillingError("Stripe: %s" % message)
        except (urllib.error.URLError, OSError) as problem:
            raise BillingError("Could not reach Stripe: %s" % problem)

    def create_invoice(self, draft, config):
        currency = config["currency"].lower()
        customer = {"name": draft["customer"], "metadata[source]": "tapjob"}
        # Stripe wants an email on the customer for an invoice with a payment page. Nothing is
        # mailed (auto_advance is off and we never call "send"), so a placeholder is enough.
        customer["email"] = config.get("customer_email") or "customer@example.com"
        customer = self._call("POST", "customers", customer)
        invoice = self._call("POST", "invoices", {
            "customer": customer["id"], "collection_method": "send_invoice", "days_until_due": 7,
            "auto_advance": "false", "description": draft["summary"][:500],
            "metadata[source]": "tapjob",
            "metadata[on_site_minutes]": draft["evidence"]["on_site_minutes"],
            "metadata[hands_working_minutes]": draft["evidence"]["hands_working_minutes"],
        })
        lines = [("%s x%g" % (item["description"], item["quantity"]) if item["quantity"] != 1
                  else item["description"], item["amount"]) for item in draft["items"]]
        labor = draft.get("labor")
        if labor:
            lines.append(("Labor %g h at %s/h (%s)" % (labor["hours"], labor["rate"], labor["source"]),
                          labor["amount"]))
        for description, amount in lines:
            self._call("POST", "invoiceitems", {
                "customer": customer["id"], "invoice": invoice["id"], "currency": currency,
                "amount": int(round(amount * 100)), "description": description[:500]})
        invoice = self._call("POST", "invoices/%s/finalize" % invoice["id"])
        url = invoice.get("hosted_invoice_url")
        if not url:
            raise BillingError("Stripe made the invoice but gave no payment page.")
        return {"id": invoice["id"], "url": url, "total": invoice.get("amount_due", 0) / 100,
                "number": invoice.get("number"), "provider": self.label, "paid": False}

    def is_paid(self, number):
        return self._call("GET", "invoices/%s" % number).get("status") == "paid"

    def payee(self):
        """The name of the Stripe account these invoices are paid into (asked once, shown on the page)."""
        try:
            account = self._call("GET", "account")
        except BillingError:
            return "your Stripe account (test mode)"
        name = ((account.get("settings") or {}).get("dashboard") or {}).get("display_name") \
            or (account.get("business_profile") or {}).get("name") or "your Stripe account"
        return "%s, Stripe test mode" % str(name)[:60]
