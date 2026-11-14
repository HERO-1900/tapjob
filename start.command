#!/bin/bash
# Double-click this file in Finder. It sets everything up the first time, then starts
# TapJob with your band. Double-tap the band when it says so.
cd "$(dirname "$0")" || exit 1
echo "== TapJob =="
if [ ! -d vexo-open-kit/python/vexo_open ]; then
  echo "Getting the Vexo kit (first time only)..."
  git clone --depth 1 https://github.com/VexoAI-Org/vexo-open-kit.git || { echo "Could not download the kit. Is the internet on?"; read -r -p "Press Return to close."; exit 1; }
fi
if [ ! -x .venv/bin/python ]; then
  echo "Setting up Python (first time only)..."
  python3 -m venv .venv || { echo "python3 is missing. Install it from python.org, then double-click again."; read -r -p "Press Return to close."; exit 1; }
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet bleak || { echo "Could not install the Bluetooth library (bleak)."; read -r -p "Press Return to close."; exit 1; }
fi
[ -f .env ] || cp env.example .env
ask_key() {   # name, where to find it
  grep -Eq "^$1=.+" .env && return
  echo
  echo "$2"
  read -r -s -p "Paste $1 here and press Return (or just Return to skip): " value
  echo
  value="$(printf '%s' "$value" | tr -d '[:space:]')"
  [ -n "$value" ] || { echo "Skipped: a stand-in is used for now."; return; }
  KEY_NAME="$1" KEY_VALUE="$value" .venv/bin/python - <<'PY'
import os, re
from pathlib import Path
name, value = os.environ["KEY_NAME"], os.environ["KEY_VALUE"]
path = Path(".env")
text = path.read_text(encoding="utf-8") if path.exists() else ""
line = "%s=%s" % (name, value)
pattern = r"(?m)^%s=.*$" % re.escape(name)
text = re.sub(pattern, lambda _: line, text) if re.search(pattern, text) else text.rstrip("\n") + "\n" + line + "\n"
path.write_text(text, encoding="utf-8")
os.chmod(path, 0o600)
PY
  echo "Saved in .env on this computer."
}
ask_key DEEPGRAM_API_KEY  "1/3  Deepgram key (speech to text): console.deepgram.com, API Keys."
ask_key GEMINI_API_KEY    "2/3  Gemini key (words to invoice fields): aistudio.google.com/api-keys, the hackathon account."
ask_key STRIPE_SECRET_KEY "3/3  Stripe TEST secret key, starts with sk_test_: dashboard.stripe.com/test/apikeys."
(sleep 4; open "http://127.0.0.1:8765") &
echo
echo "Close the Vexo dashboard tab if it is open. Then DOUBLE-TAP the band (its light blinks blue)."
echo "If macOS asks whether Terminal may use Bluetooth, press Allow, then double-click this file again."
echo
.venv/bin/python app.py "$@"
echo
read -r -p "TapJob stopped. Press Return to close this window."
