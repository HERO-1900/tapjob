#!/bin/bash
# Double-click: the same program with a pretend band. No hardware needed. Drive it from the page.
cd "$(dirname "$0")" || exit 1
if [ ! -d vexo-open-kit/python/vexo_open ]; then
  git clone --depth 1 https://github.com/VexoAI-Org/vexo-open-kit.git || { read -r -p "Could not download the kit. Press Return."; exit 1; }
fi
[ -f .env ] || cp env.example .env
(sleep 3; open "http://127.0.0.1:8765") &
python3 app.py --sim
read -r -p "Stopped. Press Return to close this window."
