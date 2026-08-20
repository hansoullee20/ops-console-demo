#!/usr/bin/env bash
set -euo pipefail

MODEL="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
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

ACTUAL_ARCHIVE_SHA256="$(sha256sum model.tar.bz2 | awk '{print $1}')"
if [[ -n "${OKJA_MODEL_SHA256:-}" && "$ACTUAL_ARCHIVE_SHA256" != "$OKJA_MODEL_SHA256" ]]; then
  echo "SenseVoice archive SHA-256 mismatch" >&2
  echo "expected: $OKJA_MODEL_SHA256" >&2
  echo "actual:   $ACTUAL_ARCHIVE_SHA256" >&2
  exit 1
fi

printf 'archive_sha256=%s\nsource=%s\n' "$ACTUAL_ARCHIVE_SHA256" "$URL" > provenance.txt

tar xjf model.tar.bz2
SRC="${TMP}/${MODEL}"
DST="${ASSETS}/${MODEL}"
rm -rf "$DST"
mkdir -p "$DST"

cp "${SRC}/model.int8.onnx" "$DST/"
cp "${SRC}/tokens.txt" "$DST/"
cp provenance.txt "$DST/OKJA_MODEL_PROVENANCE.txt"

(
  cd "$DST"
  sha256sum model.int8.onnx tokens.txt > OKJA_MODEL_FILES.sha256
)

printf 'Provisioned %s into %s\n' "$MODEL" "$DST"
printf 'Archive SHA-256: %s\n' "$ACTUAL_ARCHIVE_SHA256"
if [[ -z "${OKJA_MODEL_SHA256:-}" ]]; then
  printf 'WARNING: archive digest was recorded but not pre-pinned; do not treat this as release-grade provenance.\n' >&2
fi
ls -lh "$DST"
