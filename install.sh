#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
  python3 \
  python3-flask \
  python3-pip \
  mpv \
  chromium-browser \
  curl

if ! command -v yt-dlp >/dev/null 2>&1; then
  sudo apt-get install -y yt-dlp || true
fi

if ! command -v yt-dlp >/dev/null 2>&1; then
  python3 -m pip install --user --upgrade yt-dlp
fi

if ! command -v yt-dlp >/dev/null 2>&1; then
  echo "ERROR: yt-dlp konnte nicht installiert werden."
  echo "Bitte pruefe Netz/apt/pip und PATH (~/.local/bin)."
  exit 1
fi

echo "Installationsbasis ist bereit."
