#!/usr/bin/env bash
set -euo pipefail

MODEL="sherpa-onnx-streaming-zipformer-korean-2024-06-16"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL}.tar.bz2"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSETS="${ROOT}/app/src/main/assets"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$ASSETS"
cd "$TMP"

if command -v curl >/dev/null 2>&1; then
  curl -fL "$URL" -o model.tar.bz2
elif command -v wget >/dev/null 2>&1; then
  wget -O model.tar.bz2 "$URL"
else
  echo "curl or wget is required" >&2
  exit 1
fi

tar xjf model.tar.bz2
SRC="${TMP}/${MODEL}"
DST="${ASSETS}/${MODEL}"
rm -rf "$DST"
mkdir -p "$DST"

# Keep only the files used by sherpa's official Korean streaming int8 config.
cp "${SRC}/encoder-epoch-99-avg-1.int8.onnx" "$DST/"
cp "${SRC}/decoder-epoch-99-avg-1.onnx" "$DST/"
cp "${SRC}/joiner-epoch-99-avg-1.int8.onnx" "$DST/"
cp "${SRC}/tokens.txt" "$DST/"

printf 'Provisioned %s into %s\n' "$MODEL" "$DST"
ls -lh "$DST"
