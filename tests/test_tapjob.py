"""Checks that need no band, no keys and no internet.

    python3 -m unittest discover -s tests -v

The Gemini and Stripe calls are answered by stand-ins here, so the tests check what this
program sends and how it reads the answers, not the services themselves.
"""
import io
import json
import os
import subprocess
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import billing  # noqa: E402
import brain    # noqa: E402
import keys     # noqa: E402

CONFIG = {"labor_rate": 95.0, "currency": "usd", "customer_email": "", "business_name": "Test"}
WORDS = ("Job for Mr. Wang, kitchen sink is leaking under the cabinet. Replaced the supply hose, 18 dollars. "
         "Replaced one angle valve, 25 dollars. Labor one and a half hours.")


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class OfflineBrain(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)

    def tearDown(self):
        self.env.stop()

    def test_sample_sentence(self):
        draft = brain.make_draft(WORDS, CONFIG, on_site_seconds=1200, active_seconds=600, note=lambda _: None)
        self.assertEqual(draft["customer"], "Mr. Wang")
        self.assertEqual([(i["description"], i["amount"]) for i in draft["items"]],
                         [("Supply hose", 18.0), ("Angle valve", 25.0)])
        self.assertEqual(draft["labor"]["hours"], 1.5)
        self.assertEqual(draft["labor"]["source"], "said by the technician")
        self.assertEqual(draft["total"], 18 + 25 + 142.5)
        self.assertEqual(draft["warnings"], [])

    def test_no_hours_said_uses_the_band_clock(self):
        draft = brain.make_draft("Replaced a faucet cartridge, $32.", CONFIG, on_site_seconds=40 * 60,
                                 active_seconds=0, note=lambda _: None)
        self.assertEqual(draft["labor"]["hours"], 0.75)                    # 40 minutes -> three quarters
        self.assertEqual(draft["labor"]["source"], "measured by the band")
        self.assertTrue(draft["warnings"])

    def test_nothing_useful_still_gives_a_draft(self):
        draft = brain.make_draft("hello hello testing", CONFIG, on_site_seconds=10, note=lambda _: None)
        self.assertEqual(draft["items"], [])
        self.assertEqual(draft["labor"]["hours"], 0.25)


class GeminiBrain(unittest.TestCase):
    def test_request_and_answer(self):
        fields = {"customer": "Ana", "summary": "Fixed a leak", "labor_hours": None,
                  "parts": [{"description": "P-trap", "quantity": 2, "unit_price": 9.5},
                            {"description": "Sealant", "quantity": 1, "unit_price": None}]}
        seen = {}

        def urlopen(request, **_):
            seen["url"], seen["key"] = request.full_url, request.get_header("X-goog-api-key")
            seen["body"] = json.loads(request.data.decode())
            reply = {"candidates": [{"content": {"parts": [{"text": json.dumps(fields)}]}}]}
            return Answer(json.dumps(reply).encode())

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-4-hydrogen"}), \
                mock.patch("urllib.request.urlopen", urlopen):
            draft = brain.make_draft("whatever was said", CONFIG, on_site_seconds=1800, note=lambda _: None)
        self.assertIn("models/gemini-4-hydrogen:generateContent", seen["url"])
        self.assertEqual(seen["key"], "test-key")
        self.assertEqual(seen["body"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(draft["provider"], "Gemini (gemini-4-hydrogen)")
        self.assertEqual(draft["items"][0]["amount"], 19.0)
        self.assertIsNone(draft["items"][1]["unit_price"])
        self.assertEqual(draft["labor"]["hours"], 0.5)
        self.assertEqual(draft["total"], 19.0 + 47.5)
        self.assertEqual(len(draft["warnings"]), 2)                       # one missing price, hours not said

    def test_a_failing_model_falls_back_to_the_rules(self):
        def urlopen(*_, **__):
            raise OSError("no network")

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch("urllib.request.urlopen", urlopen):
            os.environ.pop("OPENAI_API_KEY", None)
            draft = brain.make_draft(WORDS, CONFIG, note=lambda _: None)
        self.assertEqual(draft["provider"], "offline rules")
        self.assertEqual(draft["total"], 185.5)


class StripeBilling(unittest.TestCase):
    def test_live_keys_are_refused(self):
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_live_x"}):
            with self.assertRaises(SystemExit):
                billing.create(8765)

    def test_invoice_calls(self):
        calls = []

        def urlopen(request, **_):
            path = request.full_url.replace(billing.API, "")
            fields = dict(urllib.parse.parse_qsl(request.data.decode())) if request.data else {}
            calls.append((request.get_method(), path, fields))
            if path == "customers":
                reply = {"id": "cus_1"}
            elif path == "invoices":
                reply = {"id": "in_1"}
            elif path == "invoiceitems":
                reply = {"id": "ii_%d" % len(calls)}
            elif path == "invoices/in_1/finalize":
                reply = {"id": "in_1", "hosted_invoice_url": "https://invoice.stripe.com/i/test", "amount_due": 18550,
                         "number": "T-0001"}
            else:
                reply = {"id": "in_1", "status": "paid"}
            return Answer(json.dumps(reply).encode())

        draft = brain.make_draft(WORDS, CONFIG, on_site_seconds=600, note=lambda _: None)
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_abc"}), \
                mock.patch("urllib.request.urlopen", urlopen):
            biller = billing.create(8765)
            invoice = biller.create_invoice(draft, CONFIG)
            self.assertTrue(biller.is_paid(invoice["id"]))
        self.assertEqual(invoice["url"], "https://invoice.stripe.com/i/test")
        self.assertEqual(invoice["total"], 185.5)
        items = [fields for _, path, fields in calls if path == "invoiceitems"]
        self.assertEqual([int(i["amount"]) for i in items], [1800, 2500, 14250])
        self.assertTrue(all(i["invoice"] == "in_1" and i["currency"] == "usd" for i in items))
        self.assertEqual(calls[1][2]["collection_method"], "send_invoice")


class Keys(unittest.TestCase):
    def test_saved_in_env_file_and_live_keys_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {}, clear=False):
            (Path(folder) / "env.example").write_text("# comment\nDEEPGRAM_API_KEY=\nSTRIPE_SECRET_KEY=\n")
            keys.save("DEEPGRAM_API_KEY", "abcdef0123456789", folder)
            keys.save("STRIPE_SECRET_KEY", "sk_test_abc12345", folder)
            keys.save("DEEPGRAM_API_KEY", "fedcba9876543210", folder)          # replaced, not doubled
            text = (Path(folder) / ".env").read_text()
            self.assertEqual(text.count("DEEPGRAM_API_KEY="), 1)
            self.assertIn("DEEPGRAM_API_KEY=fedcba9876543210", text)
            self.assertIn("STRIPE_SECRET_KEY=sk_test_abc12345", text)
            self.assertEqual(os.stat(Path(folder) / ".env").st_mode & 0o777, 0o600)
            self.assertEqual(os.environ["DEEPGRAM_API_KEY"], "fedcba9876543210")
            with self.assertRaises(ValueError):
                keys.save("STRIPE_SECRET_KEY", "sk_live_abc12345", folder)
            with self.assertRaises(ValueError):
                keys.save("OTHER", "abcdef0123456789", folder)
            self.assertIsNotNone(keys.check("GEMINI_API_KEY", "has a space in it"))


class WholeLoop(unittest.TestCase):
    def test_pretend_band_start_to_paid(self):
        if not (ROOT / "vexo-open-kit" / "python" / "vexo_open").is_dir():
            self.skipTest("the kit is not in this folder")
        env = {k: v for k, v in os.environ.items()
               if k not in ("GEMINI_API_KEY", "OPENAI_API_KEY", "STRIPE_SECRET_KEY", "DEEPGRAM_API_KEY")}
        done = subprocess.run([sys.executable, str(ROOT / "app.py"), "--sim", "--demo", "--quiet", "--port", "0"],
                              cwd=str(ROOT / "tests"), env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("JOB STARTED", done.stdout)
        self.assertIn("INVOICE SENT", done.stdout)
        self.assertIn("PAID.", done.stdout)


if __name__ == "__main__":
    unittest.main()
