#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECIPE_TEMPLATE="$ROOT_DIR/packaging/AppImageBuilder.yml.tmpl"
BUILD_DIR="$ROOT_DIR/build/appimage"
RECIPE_PATH="$BUILD_DIR/AppImageBuilder.yml"
DIST_DIR="$ROOT_DIR/dist"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "AppImage build is supported only on Linux." >&2
  exit 1
fi

if ! command -v appimage-builder >/dev/null 2>&1 && ! command -v podman >/dev/null 2>&1; then
  echo "Missing appimage-builder and podman in PATH." >&2
  echo "Install appimage-builder or podman first." >&2
  exit 1
fi

VERSION="$(python3 - <<'PY'
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"

mkdir -p "$BUILD_DIR" "$DIST_DIR"

sed \
  -e "s|__VERSION__|$VERSION|g" \
  "$RECIPE_TEMPLATE" >"$RECIPE_PATH"

cd "$ROOT_DIR"

if command -v apt-get >/dev/null 2>&1; then
  appimage-builder --recipe "$RECIPE_PATH" --skip-tests
elif command -v podman >/dev/null 2>&1; then
  podman run --rm \
    -v "$ROOT_DIR:$ROOT_DIR:Z" \
    -w "$ROOT_DIR" \
    ubuntu:24.04 \
    bash -lc '
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y --no-install-recommends \
        binutils \
        ca-certificates \
        coreutils \
        curl \
        desktop-file-utils \
        fakeroot \
        file \
        git \
        gtk-update-icon-cache \
        libgdk-pixbuf-2.0-0 \
        libgdk-pixbuf2.0-dev \
        patchelf \
        python3 \
        python3-pip \
        python3-setuptools \
        python3-venv \
        squashfs-tools \
        strace \
        util-linux \
        zsync
      python3 -m venv /tmp/aib
      /tmp/aib/bin/pip install --no-cache-dir "appimage-builder==1.1.0"
      /tmp/aib/bin/pip install --no-cache-dir "packaging<22"
      /tmp/aib/bin/appimage-builder --recipe "'$RECIPE_PATH'" --skip-tests
    '
else
  echo "apt-get not found and podman is unavailable." >&2
  exit 1
fi

shopt -s nullglob
for artifact in ./*.AppImage ./*.zsync; do
  mv "$artifact" "$DIST_DIR/"
done
shopt -u nullglob

echo "AppImage artifacts are in $DIST_DIR"
