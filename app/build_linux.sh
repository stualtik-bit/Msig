#!/bin/bash
# Builds MSIG for Linux (x86_64): MSIG-<version>-linux-x86_64.tar.gz
#     bash app/build_linux.sh
# Run on Linux x86_64. Requirements: uv (https://docs.astral.sh/uv/) or PYTHON=<python>.
# By default uses uv's "standalone" Python (built for glibc 2.17): the resulting executable
# runs on both recent and old distributions (Ubuntu 18.04+, Debian 10+...).
# The editor opens in the default browser; the gateway is msig_serveur.py.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
VERSION=$(python3 -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('msig_serveur.py').read()).group(1))")
ARCH=$(uname -m)
NAME=MSIG-$VERSION-linux-$ARCH

python3 editeur/build.py
VENV=${VENV:-$HOME/.cache/msig-build-venv-linux}
if [ ! -x "$VENV/bin/python" ]; then
  if [ -n "${PYTHON:-}" ]; then "$PYTHON" -m venv "$VENV"; else uv venv -q -p 3.12 --managed-python "$VENV"; fi
fi
if [ -x "$VENV/bin/pip" ]; then "$VENV/bin/pip" install -q --upgrade pyinstaller pyserial
else uv pip install -q -p "$VENV/bin/python" pyinstaller pyserial; fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/msig-linux.XXXXXX")
"$VENV/bin/pyinstaller" --noconfirm --clean --name msig \
  --exclude-module ssl --exclude-module _ssl --exclude-module _hashlib --exclude-module tkinter \
  --add-data "$ROOT/editeur/msig_editeur_public.html:." \
  --distpath "$WORK/dist" --workpath "$WORK/pyinstaller" --specpath "$WORK" \
  msig_serveur.py

STAGE=$WORK/$NAME
mkdir -p "$STAGE"
mv "$WORK/dist/msig" "$STAGE/msig"
cp app/icon-1024.png "$STAGE/msig.png"
cp app/README-linux.txt "$STAGE/README.txt"
cp app/install-linux.sh "$STAGE/install.sh"
chmod +x "$STAGE/install.sh" "$STAGE/msig/msig"

# Smoke test: the executable starts and responds (no serial port, no browser)
XDG_STATE_HOME="$WORK/state" XDG_DATA_HOME="$WORK/data" \
  "$STAGE/msig/msig" --no-browser --http 0 --port /dev/null </dev/null >/dev/null 2>&1 &
PID=$!; sleep 4; kill $PID 2>/dev/null || true
grep -q "Editor: http://127.0.0.1:" "$WORK/state/msig/msig.log" || { cat "$WORK/state/msig/msig.log"; echo "startup test failed"; exit 1; }

mkdir -p dist
tar -C "$WORK" --owner=0 --group=0 -czf "dist/$NAME.tar.gz" "$NAME"
echo
echo "OK: $ROOT/dist/$NAME.tar.gz ($(du -h "dist/$NAME.tar.gz" | cut -f1))"
echo "minimum glibc required: $(objdump -T "$STAGE"/msig/msig "$STAGE"/msig/_internal/*.so* 2>/dev/null | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
sha256sum "dist/$NAME.tar.gz"
