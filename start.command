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
missing=""
for name in DEEPGRAM_API_KEY GEMINI_API_KEY STRIPE_SECRET_KEY; do
  grep -Eq "^${name}=.+" .env || missing="$missing $name"
done
if [ -n "$missing" ] && [ ! -f .keys-asked ]; then
  touch .keys-asked
  echo "These keys are still empty in .env:$missing"
  echo "The file opens now in TextEdit. Paste each key after its = sign, save (Cmd+S), close it,"
  echo "then double-click start.command again. (It still runs without them, with stand-ins.)"
  open -e .env
  read -r -p "Press Return to close this window."
  exit 0
fi
[ -n "$missing" ] && echo "Still empty in .env (stand-ins are used):$missing"
(sleep 4; open "http://127.0.0.1:8765") &
echo
echo "Close the Vexo dashboard tab if it is open. Then DOUBLE-TAP the band (its light blinks blue)."
echo "If macOS asks whether Terminal may use Bluetooth, press Allow, then double-click this file again."
echo
.venv/bin/python app.py "$@"
echo
read -r -p "TapJob stopped. Press Return to close this window."
