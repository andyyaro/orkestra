#!/bin/bash
# Fetch the film's JavaScript library at the version it was built with, and check the file
# against the copy that rendered the film (SHA-256). Run from media/launch-film/.
set -euo pipefail
cd "$(dirname "$0")/.."

fetch() {  # url  destination  sha256
  mkdir -p "$(dirname "$2")"
  curl -fsSL "$1" -o "$2.tmp"
  got=$(shasum -a 256 "$2.tmp" | cut -d' ' -f1)
  if [ "$got" != "$3" ]; then
    rm -f "$2.tmp"
    echo "checksum mismatch for $1" >&2
    exit 1
  fi
  mv "$2.tmp" "$2"
  echo "ok  $2"
}

GSAP=https://cdn.jsdelivr.net/npm/gsap@3.14.2

fetch "$GSAP/dist/gsap.min.js" assets/vendor/gsap.min.js \
  c174bfce53a729418d57a8ad8625e7247c793a22fef8e2851e3cfa3de9cd8280
