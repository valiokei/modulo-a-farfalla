#!/usr/bin/env bash
# Build the self-contained Linux AppImage (loopback-only desktop edition).
#
# The bundle carries its own CPython, the pinned backend wheels, the built
# frontend, static FFmpeg/FFprobe (BtbN 8.1: drawtext + vaapi/nvenc), a
# minimal fontconfig with bundled DejaVu fonts and libva 2.24 (VA-API works
# even on hosts whose system libva is older), so overlays render and hardware
# encoding works on any host without system Python, FFmpeg or fontconfig.
# Output: dist/appimage/Modulo-a-Farfalla-<version>-x86_64.AppImage (+ .sha256)
# The version comes from the committed VERSION file; the commit hash is only
# a fallback when VERSION is absent.
#
# Usage:  scripts/build-appimage.sh
#   SKIP_NPM_CI=1            reuse an existing frontend/node_modules
#   APPIMAGETOOL_SHA256=...  accept a newer upstream appimagetool build
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/dist/appimage-build"
STAGE="$BUILD/AppDir"
CACHE="$ROOT/dist/appimage-cache"
WHEELS="$BUILD/wheels"
OUTPUT_DIR="$ROOT/dist/appimage"
SHORT_SHA="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || true)"
[[ -n "$SHORT_SHA" ]] || SHORT_SHA=development
VERSION_VALUE=""
if [[ -f "$ROOT/VERSION" ]]; then
  VERSION_VALUE="$(tr -d '[:space:]' < "$ROOT/VERSION")"
fi
[[ -n "$VERSION_VALUE" ]] || VERSION_VALUE="$SHORT_SHA"
OUTPUT="$OUTPUT_DIR/Modulo-a-Farfalla-$VERSION_VALUE-x86_64.AppImage"

# Pinned upstream inputs; checksums verified against the publishers' own files.
PYTHON_URL='https://github.com/astral-sh/python-build-standalone/releases/download/20261001/cpython-3.12.15%2B20261001-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
PYTHON_TAR="$CACHE/cpython-3.12.15+20261001-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PYTHON_SHA256=7bb1659e3235077b7f63d5b6eb6ce653c6fcd6c5041e9d5f73b42ce10421464d
FFMPEG_URL='https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-01-13-06/ffmpeg-n8.1.3-14-g330caae0c1-linux64-gpl-8.1.tar.xz'
FFMPEG_TAR="$CACHE/ffmpeg-n8.1.3-14-g330caae0c1-linux64-gpl-8.1.tar.xz"
FFMPEG_SHA256=89cca03b81002bef5a48c2e983afa6100e52904052c1c75dfd2090b09b57efee
# The bundled FFmpeg resolves libva.so.2 at runtime and needs the 2.24 ABI
# (vaMapBuffer2); ship it beside ffmpeg so VA-API also works on hosts whose
# system libva is older.
LIBVA_URL='https://archive.ubuntu.com/ubuntu/pool/main/libv/libva/libva2_2.24.1-2_amd64.deb'
LIBVA_DEB="$CACHE/libva2_2.24.1-2_amd64.deb"
LIBVA_SHA256=2df9b53e853cc4ba3ac1f07982c8cc7d06ccc363c79fd797e05b885f7e200d08
DEJAVU_URL='https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip'
DEJAVU_ZIP="$CACHE/dejavu-fonts-ttf-2.37.zip"
DEJAVU_SHA256=7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a
# Pinned immutable release: the 'continuous' tag is rebuilt periodically and
# would make the checksum below fail without warning.
APPIMAGETOOL_URL='https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage'
APPIMAGETOOL="$CACHE/appimagetool-1.9.1-x86_64.AppImage"
APPIMAGETOOL_SHA256="${APPIMAGETOOL_SHA256:-ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0}"

[[ "$(uname -s)" == Linux ]] || { echo 'This build must run on Linux' >&2; exit 1; }
for executable in curl npm node python3 rsync sha256sum unzip tar xz ar; do
  command -v "$executable" >/dev/null || { echo "Missing build tool: $executable" >&2; exit 1; }
done
mkdir -p "$CACHE" "$WHEELS" "$BUILD/ffmpeg-extract" "$BUILD/dejavu-extract" "$BUILD/libva-extract" "$OUTPUT_DIR"

download_verified() {
  local url="$1" target="$2" checksum="$3"
  if [[ -f "$target" ]] && echo "$checksum  $target" | sha256sum -c - >/dev/null 2>&1; then
    return 0
  fi
  rm -f "$target.tmp"
  curl --fail --location --retry 3 --output "$target.tmp" "$url" || return 1
  echo "$checksum  $target.tmp" | sha256sum -c - >/dev/null 2>&1 || return 1
  mv "$target.tmp" "$target"
}

extract_deb() {
  local deb="$1" dest="$2"
  rm -rf "$dest"; mkdir -p "$dest"
  if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb -x "$deb" "$dest"
    return 0
  fi
  (cd "$dest" && ar x "$deb" && tar --zstd -xf data.tar.zst)
}

download_verified "$PYTHON_URL" "$PYTHON_TAR" "$PYTHON_SHA256"
download_verified "$FFMPEG_URL" "$FFMPEG_TAR" "$FFMPEG_SHA256"
download_verified "$DEJAVU_URL" "$DEJAVU_ZIP" "$DEJAVU_SHA256"
download_verified "$LIBVA_URL" "$LIBVA_DEB" "$LIBVA_SHA256"
if ! download_verified "$APPIMAGETOOL_URL" "$APPIMAGETOOL" "$APPIMAGETOOL_SHA256"; then
  echo 'appimagetool 1.9.1 could not be verified.' >&2
  echo 'Download it, recompute sha256 and re-run with APPIMAGETOOL_SHA256=<new value>.' >&2
  exit 1
fi

# Generated staging only; never reuse stale trees.
[[ "$STAGE" == "$ROOT"/dist/* ]] || { echo 'Refusing to clean outside dist/' >&2; exit 1; }
rm -rf "$STAGE" "$WHEELS" "$BUILD/ffmpeg-extract" "$BUILD/dejavu-extract" "$BUILD/libva-extract"
mkdir -p "$STAGE/backend" "$WHEELS" "$BUILD/ffmpeg-extract" "$BUILD/dejavu-extract" "$BUILD/libva-extract" \
  "$STAGE/desktop" "$STAGE/ffmpeg" "$STAGE/fontconfig/fonts" "$STAGE/fontconfig/cache" "$STAGE/frontend"

# SQLite desktop build: no PostgreSQL driver, no pytest, plain uvicorn.
sed -e '/^pytest==/d' -e '/^psycopg\[binary\]==/d' -e 's/^uvicorn\[standard\]/uvicorn/' \
  "$ROOT/backend/requirements.txt" > "$BUILD/runtime-requirements.txt"
python3 -m pip download --disable-pip-version-check --dest "$WHEELS" \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
  --python-version 312 --implementation cp --abi cp312 --abi abi3 --abi none \
  --only-binary=:all: -r "$BUILD/runtime-requirements.txt"

rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
  "$ROOT/backend/app/" "$STAGE/backend/app/"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
  "$ROOT/backend/alembic/" "$STAGE/backend/alembic/"
for file in __init__.py launcher.py update.py diagnostics.py THIRD_PARTY_NOTICES.md; do
  cp "$ROOT/desktop/$file" "$STAGE/desktop/$file"
done
printf '%s' "$VERSION_VALUE" > "$STAGE/desktop/build-version.txt"
if [[ -f "$ROOT/VERSION" ]]; then
  cp "$ROOT/VERSION" "$STAGE/VERSION"
fi

tar -xzf "$PYTHON_TAR" -C "$STAGE"
python3 -m pip install --disable-pip-version-check --no-index --no-deps --no-compile \
  --target "$STAGE/python/lib/python3.12/site-packages" \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
  --python-version 3.12 --implementation cp --abi cp312 --abi abi3 --abi none \
  --only-binary=:all: "$WHEELS"/*.whl
[[ -f "$STAGE/python/lib/python3.12/site-packages/fastapi/__init__.py" ]] || \
  { echo 'Wheel installation failed' >&2; exit 1; }

tar -xJf "$FFMPEG_TAR" -C "$BUILD/ffmpeg-extract"
ffmpeg_dir="$(find "$BUILD/ffmpeg-extract" -mindepth 1 -maxdepth 1 -type d -name 'ffmpeg-*-linux64-*' -print -quit)"
[[ -n "$ffmpeg_dir" ]] || { echo 'FFmpeg archive layout unexpected' >&2; exit 1; }
cp "$ffmpeg_dir/bin/ffmpeg" "$ffmpeg_dir/bin/ffprobe" "$STAGE/ffmpeg/"
cp "$ffmpeg_dir/LICENSE.txt" "$STAGE/ffmpeg/LICENSE.txt"

extract_deb "$LIBVA_DEB" "$BUILD/libva-extract"
libva_lib="$(find "$BUILD/libva-extract/usr/lib" -name 'libva.so.2.*' ! -type l -print -quit)"
[[ -n "$libva_lib" ]] || { echo 'libva archive layout unexpected' >&2; exit 1; }
cp "$libva_lib" "$STAGE/ffmpeg/libva.so.2"
cp "$BUILD/libva-extract/usr/share/doc/libva2/copyright" "$STAGE/ffmpeg/libva-copyright.txt"

unzip -q -o "$DEJAVU_ZIP" -d "$BUILD/dejavu-extract"
dejavu_dir="$(find "$BUILD/dejavu-extract" -mindepth 1 -maxdepth 1 -type d -name 'dejavu-fonts-ttf-*' -print -quit)"
[[ -n "$dejavu_dir" ]] || { echo 'DejaVu archive layout unexpected' >&2; exit 1; }
cp "$dejavu_dir/ttf/DejaVuSans.ttf" "$dejavu_dir/ttf/DejaVuSans-Bold.ttf" "$STAGE/fontconfig/fonts/"
cp "$dejavu_dir/LICENSE" "$STAGE/fontconfig/DejaVu-LICENSE.txt"
cat > "$STAGE/fontconfig/fonts.conf" <<'FONTCONF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir prefix="relative">fonts</dir>
  <cachedir prefix="relative">cache</cachedir>
</fontconfig>
FONTCONF

cp "$ROOT/desktop/modulo-a-farfalla.desktop" "$STAGE/modulo-a-farfalla.desktop"
cp "$ROOT/desktop/modulo-a-farfalla.png" "$STAGE/modulo-a-farfalla.png"
if command -v convert >/dev/null 2>&1 && file "$STAGE/modulo-a-farfalla.png" | grep -q '16-bit'; then
  convert "$STAGE/modulo-a-farfalla.png" -depth 8 PNG32:"$STAGE/icon.tmp.png" && \
    mv "$STAGE/icon.tmp.png" "$STAGE/modulo-a-farfalla.png"
fi
cp "$STAGE/modulo-a-farfalla.png" "$STAGE/.DirIcon"

cat > "$STAGE/AppRun" <<'APPRUN'
#!/bin/bash
# AppRun: loopback-only local desktop edition; never used by the server deployment.
set -euo pipefail
HERE="${APPDIR:-$(cd "$(dirname "$(readlink -f "$0")")" && pwd)}"
export MODULO_PACKAGER=appimage
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
exec "$HERE/python/bin/python3" "$HERE/desktop/launcher.py" "$@"
APPRUN
chmod 755 "$STAGE/AppRun"

if [[ "${SKIP_NPM_CI:-0}" == "1" && -d "$ROOT/frontend/node_modules" ]]; then
  echo 'SKIP_NPM_CI=1: reusing frontend/node_modules'
else
  npm ci --prefix "$ROOT/frontend"
fi
VITE_DESKTOP=true npm run --prefix "$ROOT/frontend" build
rsync -a --delete "$ROOT/frontend/dist/" "$STAGE/frontend/dist/"
[[ -f "$STAGE/frontend/dist/index.html" ]] || { echo 'Frontend build missing' >&2; exit 1; }

if command -v desktop-file-validate >/dev/null; then
  desktop-file-validate "$STAGE/modulo-a-farfalla.desktop"
fi

rm -f "$OUTPUT"
chmod +x "$APPIMAGETOOL"
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$STAGE" "$OUTPUT" || \
  ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" --no-appstream "$STAGE" "$OUTPUT"
[[ -s "$OUTPUT" ]] || { echo 'AppImage was not created' >&2; exit 1; }
( cd "$OUTPUT_DIR" && sha256sum "$(basename "$OUTPUT")" ) > "$OUTPUT.sha256"
echo "AppImage: $OUTPUT  ($(du -h "$OUTPUT" | cut -f1))"
echo "SHA-256: $(cut -d' ' -f1 "$OUTPUT.sha256")"
echo
echo 'Real smoke test (actual AppImage, isolated data directory):'
echo "  PATH=\"/usr/bin:\$PATH\" \"$ROOT/backend/.venv/bin/python\" \"$ROOT/desktop/smoke_test.py\" --executable \"$OUTPUT\""
