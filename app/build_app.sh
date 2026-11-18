#!/bin/bash
# Builds MSIG.app and MSIG-<version>.dmg (run on a Mac):
#     bash app/build_app.sh
# Requirements: python3 and Internet access (PyInstaller, pyserial and PyObjC are installed in a
# virtual environment outside the source folder).
#
# Optional signing with an Apple Developer account (environment variables, no defaults):
#   SIGN_IDENTITY   code signing identity: SHA-1 hash (recommended) or the full name
#                   "Developer ID Application: ..." (list: security find-identity -v -p codesigning)
#   NOTARY_PROFILE  notarytool keychain profile, created once with
#                   xcrun notarytool store-credentials <profile> --apple-id ... --team-id ...
#   TEAM_ID         (optional) your team ID; the build stops if the identity belongs to another team
#   SIGN_IDENTITY=... NOTARY_PROFILE=... TEAM_ID=... bash app/build_app.sh
# Intel + Apple Silicon: PYTHON=<universal python.org python3> TARGET_ARCH=universal2 ...
# Without SIGN_IDENTITY: ad hoc signature (first launch: right-click > Open).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
VERSION=$(python3 -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('msig_serveur.py').read()).group(1))")
ENT=$ROOT/app/entitlements.plist
SIGN_IDENTITY=${SIGN_IDENTITY:-}
NOTARY_PROFILE=${NOTARY_PROFILE:-}

python3 editeur/build.py
# Python environment outside the source folder (a synced folder can corrupt it)
PYTHON=${PYTHON:-python3}
VENV=${VENV:-$HOME/.cache/msig-build-venv${TARGET_ARCH:+-$TARGET_ARCH}}
[ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip pyinstaller pyserial pyobjc-framework-WebKit

# Build and sign in a temporary folder: file sync tools add extended attributes that codesign
# refuses ("resource fork, Finder information... not allowed").
WORK=$(mktemp -d "${TMPDIR:-/tmp}/msig-build.XXXXXX")

SIGN_ARGS=()
if [ -n "$SIGN_IDENTITY" ]; then
  # PyInstaller signs every embedded library with this identity and these entitlements
  SIGN_ARGS=(--codesign-identity "$SIGN_IDENTITY" --osx-entitlements-file "$ENT")
fi
"$VENV/bin/pyinstaller" --noconfirm --clean --windowed --name MSIG \
  --osx-bundle-identifier com.moteka.msig --icon "$ROOT/app/MSIG.icns" \
  ${TARGET_ARCH:+--target-arch "$TARGET_ARCH"} \
  --exclude-module ssl --exclude-module _ssl --exclude-module _hashlib \
  --add-data "$ROOT/editeur/msig_editeur_public.html:." \
  --distpath "$WORK" --workpath "$WORK/pyinstaller" --specpath "$WORK" \
  ${SIGN_ARGS[@]+"${SIGN_ARGS[@]}"} \
  msig_app.py

APP=$WORK/MSIG.app
PL=$APP/Contents/Info.plist
# Windowed app (msig_app.py): Dock icon and menu bar
plutil -remove LSUIElement "$PL" 2>/dev/null || true
plutil -replace NSHighResolutionCapable -bool true "$PL"
# the editor is served locally (127.0.0.1) to the window's web view
plutil -replace NSAppTransportSecurity -json '{"NSAllowsLocalNetworking": true}' "$PL"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PL"
plutil -replace CFBundleVersion -string "$VERSION" "$PL"
plutil -replace NSHumanReadableCopyright -string "© Moteka. Independent software, not affiliated with the hardware manufacturer." "$PL"

xattr -cr "$APP"
# Info.plist changed: re-sign the bundle (embedded libraries stay signed)
if [ -n "$SIGN_IDENTITY" ]; then
  codesign --force --options runtime --timestamp --entitlements "$ENT" -s "$SIGN_IDENTITY" "$APP"
  if [ -n "${TEAM_ID:-}" ]; then
    TEAM=$(codesign -dv "$APP" 2>&1 | sed -n 's/^TeamIdentifier=//p')
    [ "$TEAM" = "$TEAM_ID" ] || { echo "signed with team '$TEAM', expected '$TEAM_ID'"; exit 1; }
  fi
else
  codesign --force --deep -s - "$APP"
fi
codesign --verify --deep --strict "$APP"

# Disk image (new temporary folder: no recursive delete)
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/msig-dmg.XXXXXX")
ditto "$APP" "$STAGE/MSIG.app"
ln -s /Applications "$STAGE/Applications"
cp app/README.txt "$STAGE/README.txt"
DMG=$WORK/MSIG-$VERSION.dmg
hdiutil create -quiet -volname "MSIG $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"

if [ -n "$SIGN_IDENTITY" ]; then
  codesign --timestamp -s "$SIGN_IDENTITY" "$DMG"
  if [ -n "$NOTARY_PROFILE" ]; then
    # Apple notarization (a few minutes), then the ticket is stapled to the DMG
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    xcrun stapler validate "$DMG"
    spctl -a -t open --context context:primary-signature -v "$DMG" || true
    xcrun stapler staple "$APP"
  else
    echo "NOTARY_PROFILE not set: DMG signed but not notarized (Gatekeeper will still block it)."
  fi
fi

# Results in dist/ (copies; previous builds are overwritten)
mkdir -p dist
rm -rf dist/MSIG.app
ditto "$APP" dist/MSIG.app
cp "$DMG" "dist/MSIG-$VERSION.dmg"

echo
echo "OK: $ROOT/dist/MSIG.app"
echo "    $ROOT/dist/MSIG-$VERSION.dmg ($(du -h "$DMG" | cut -f1))"
echo "Architecture: $(lipo -archs "$APP/Contents/MacOS/MSIG")"
echo "Work folder: $WORK"
shasum -a 256 "dist/MSIG-$VERSION.dmg"
