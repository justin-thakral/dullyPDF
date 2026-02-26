#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PUBLIC_DIR="${ROOT_DIR}/frontend/public"
WEBP_QUALITY="${WEBP_QUALITY:-82}"
WEBP_METHOD="${WEBP_METHOD:-6}"

if ! command -v convert >/dev/null 2>&1; then
  echo "ImageMagick 'convert' is required. Install ImageMagick and re-run." >&2
  exit 1
fi

if [[ ! -d "${PUBLIC_DIR}" ]]; then
  echo "Missing frontend public directory: ${PUBLIC_DIR}" >&2
  exit 1
fi

mapfile -t PNG_FILES < <(find "${PUBLIC_DIR}" -type f -name '*.png' | sort)

if [[ ${#PNG_FILES[@]} -eq 0 ]]; then
  echo "No PNG files found under ${PUBLIC_DIR}."
  exit 0
fi

converted=0
skipped=0
for png_path in "${PNG_FILES[@]}"; do
  webp_path="${png_path%.png}.webp"
  if [[ -f "${webp_path}" && "${webp_path}" -nt "${png_path}" ]]; then
    echo "skip: ${webp_path#${ROOT_DIR}/} (up-to-date)"
    skipped=$((skipped + 1))
    continue
  fi

  convert "${png_path}" \
    -strip \
    -define "webp:method=${WEBP_METHOD}" \
    -quality "${WEBP_QUALITY}" \
    "${webp_path}"
  echo "wrote: ${webp_path#${ROOT_DIR}/}"
  converted=$((converted + 1))
done

echo "WebP conversion complete: converted=${converted} skipped=${skipped} quality=${WEBP_QUALITY} method=${WEBP_METHOD}"
