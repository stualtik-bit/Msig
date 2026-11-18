#!/bin/sh
# MSIG for Linux - installs for the current user only (no root needed).
#   ./install.sh             install (or update) MSIG
#   ./install.sh --uninstall remove it (your patches and module list are kept)
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DEST="$HOME/.local/share/msig-app"
BIN="$HOME/.local/bin"
DESKTOP="$HOME/.local/share/applications/msig.desktop"

if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$DEST"
  rm -f "$BIN/msig" "$DESKTOP"
  echo "MSIG removed. Your patches and ~/.local/share/msig (module list) were kept."
  exit 0
fi

mkdir -p "$DEST" "$BIN" "$(dirname "$DESKTOP")"
rm -rf "$DEST/msig"
cp -R "$HERE/msig" "$DEST/msig"
cp "$HERE/msig.png" "$HERE/README.txt" "$DEST/"
ln -sf "$DEST/msig/msig" "$BIN/msig"
cat > "$DESKTOP" <<DESK
[Desktop Entry]
Type=Application
Name=MSIG
Comment=Algorithm editor for a DSP rack (RS-232)
Exec=$DEST/msig/msig
Icon=$DEST/msig.png
Terminal=false
Categories=AudioVideo;Audio;Music;
DESK
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$(dirname "$DESKTOP")" >/dev/null 2>&1 || true

echo "MSIG installed: start it from your applications menu, or type 'msig' in a terminal."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: $BIN is not in your PATH; use $DEST/msig/msig or the applications menu." ;; esac

# Access to serial ports: the 'dialout' group (Debian, Ubuntu, Fedora...) or 'uucp' (Arch).
GROUP=""
for g in dialout uucp; do getent group "$g" >/dev/null 2>&1 && { GROUP=$g; break; }; done
if [ -n "$GROUP" ] && ! id -nG "$USER" | tr ' ' '\n' | grep -qx "$GROUP"; then
  echo
  echo "To use the serial port, add yourself to the '$GROUP' group, then log out and back in:"
  echo "    sudo usermod -aG $GROUP $USER"
fi
