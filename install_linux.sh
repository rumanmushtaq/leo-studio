#!/usr/bin/env bash
# Leo 3D AI Cartoon Studio - Linux installer (Ubuntu 24.04 tested). Run from the project folder:
#   bash install_linux.sh
set -euo pipefail
cd "$(dirname "$0")"
BLENDER_VERSION=4.5.15
BLENDER_TAR="blender-${BLENDER_VERSION}-linux-x64.tar.xz"
BLENDER_SHA256=0d2b8bb2efe97e6c8eb57de6b7322f8800e1984e3125b60decca5f6771e4773e

echo "== 1/4 Python =="
PY=""
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys,tkinter; assert sys.version_info >= (3,11)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  if command -v uv >/dev/null; then
    echo "No system Python 3.11+ with Tk; using uv-managed Python 3.11"; uv python install 3.11; PY="uv-3.11"
  else
    echo "Need Python 3.11+ with Tk:  sudo apt install python3-venv python3-tk"; exit 1
  fi
fi

echo "== 2/4 Virtual environment and packages =="
if [ ! -d .venv ]; then
  if [ "$PY" = "uv-3.11" ]; then uv venv --python 3.11 .venv; else "$PY" -m venv .venv; fi
fi
if [ -x .venv/bin/pip ]; then PIP=".venv/bin/pip install"; else PIP="uv pip install --python .venv/bin/python"; fi
$PIP -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
if [ -z "${WAYLAND_DISPLAY:-}" ] && ! ldconfig -p 2>/dev/null | grep -q libxcb-cursor; then
  echo "NOTE: the studio window (Qt) needs libxcb-cursor0 on X11:  sudo apt install libxcb-cursor0"
  echo "      Until then the app opens its classic window."
fi

echo "== 3/4 Blender ${BLENDER_VERSION} LTS (portable, ~370 MB) =="
have_blender() {
  command -v blender >/dev/null && return 0
  for b in tools/blender-4.*/blender "$HOME"/opt/blender-4.*/blender; do [ -x "$b" ] && return 0; done
  return 1
}
if have_blender; then
  echo "Blender already available."
else
  mkdir -p tools
  curl -L -o "tools/${BLENDER_TAR}" "https://download.blender.org/release/Blender4.5/${BLENDER_TAR}"
  echo "${BLENDER_SHA256}  tools/${BLENDER_TAR}" | sha256sum -c -
  tar -xf "tools/${BLENDER_TAR}" -C tools && rm "tools/${BLENDER_TAR}"
fi

echo "== Adding to the applications menu =="
APP_DIR="$(pwd)"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/leo-3d-ai-cartoon-studio.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Leo 3D AI Cartoon Studio
GenericName=3D Cartoon Video Generator
Comment=Paste an Urdu or English script and get a 3D animated cartoon video
Exec="$APP_DIR/run_linux.sh"
Path=$APP_DIR
Icon=$APP_DIR/assets/icon.png
Terminal=false
Categories=AudioVideo;Video;
Keywords=cartoon;animation;urdu;video;blender;
StartupWMClass=leo3dstudio
DESKTOP
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "== 4/4 Checking the installation =="
.venv/bin/python main.py --check
echo
echo "Done. Start the studio with: ./run_linux.sh"
echo "Optional system packages for best results: sudo apt install ffmpeg libraqm0 fonts-noto-core"
