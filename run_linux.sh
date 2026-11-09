#!/usr/bin/env bash
# Leo 3D AI Cartoon Studio - start the desktop app on Linux
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo "Not installed yet. Run: bash install_linux.sh"; exit 1; fi
exec .venv/bin/python main.py "$@"
