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
fi
.venv/bin/python -c "import bleak, serial" 2>/dev/null || .venv/bin/python -m pip install --quiet bleak pyserial || { echo "Could not install the Bluetooth/USB libraries (bleak, pyserial). Is the internet on?"; read -r -p "Press Return to close."; exit 1; }
[ -f .env ] || cp env.example .env
for name in DEEPGRAM_API_KEY GEMINI_API_KEY STRIPE_SECRET_KEY; do
  grep -Eq "^${name}=.+" .env || echo "Not set yet: $name (add it on the page that opens, under Keys)"
done
# The page exists only once the band is connected, so open it then (not before).
(for _ in $(seq 1 400); do
  if nc -z 127.0.0.1 8765 >/dev/null 2>&1; then open "http://127.0.0.1:8765"; break; fi
  sleep 1
done) &
echo
echo "先关掉 Vexo 的 dashboard 网页（如果开着）。程序会反复找手环，最多 4 分钟，不用着急。"
echo "如果 macOS 弹窗问「终端想要使用蓝牙」，点「允许」，然后重新双击 start.command。"
echo "手环没反应就用 USB-C 线把它接到这台电脑上。"
echo "手环一连上，TapJob 的网页会自动在浏览器里打开（没连上之前不会打开，这是正常的）。"
echo
.venv/bin/python app.py "$@"
echo
read -r -p "TapJob stopped. Press Return to close this window."
