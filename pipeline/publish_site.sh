#!/usr/bin/env bash
# publish_site.sh — salin berkas ke cabang `site` (yang dilayani GitHub Pages) tanpa menambah riwayat git.
#
# Cabang `site` SELALU berisi 1 commit: tiap penerbitan = `git commit --amend` + force-push (dengan --force-with-lease supaya
# aman bila dua workflow menerbitkan bersamaan -> yang kalah mengulang). Dengan begini data yang diperbarui berkali-kali per
# hari (ensemble, sinoptik, deterministik, …) tidak membuat repo membengkak. Cabang `main` hanya berisi kode.
#
#   bash pipeline/publish_site.sh "<label>" berkas1 [berkas2 …]     (path relatif terhadap root repo)
#   bash pipeline/publish_site.sh --restore berkas1 [berkas2 …]     (ambil versi terbaru dari `site` ke working dir; abaikan bila tak ada)
set -uo pipefail

if [ -n "${SITE_REPO_URL:-}" ]; then            # untuk uji lokal
  URL="$SITE_REPO_URL"
else
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY tidak ada}"
  : "${GITHUB_TOKEN:?GITHUB_TOKEN tidak ada}"
  URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
fi
WORK="$(mktemp -d)"

if [ "${1:-}" = "--restore" ]; then
  shift
  if git clone --quiet --depth 1 --branch site "$URL" "$WORK/s" 2>/dev/null; then
    for f in "$@"; do [ -f "$WORK/s/$f" ] && cp "$WORK/s/$f" "$f" && echo "dipulihkan: $f"; done
  else
    echo "cabang site belum ada — lewati"
  fi
  exit 0
fi

LABEL="$1"; shift
for i in 1 2 3 4 5 6; do
  rm -rf "$WORK/s"
  git clone --quiet --depth 1 --branch site "$URL" "$WORK/s" || { echo "gagal clone cabang site"; sleep $((5 * i)); continue; }
  for f in "$@"; do
    mkdir -p "$WORK/s/$(dirname "$f")"
    cp -r "$f" "$WORK/s/$f"
  done
  (
    cd "$WORK/s" || exit 1
    git config user.name "mosaic-bot"
    git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
    git add -A
    if git diff --staged --quiet; then echo "Tidak ada perubahan."; exit 0; fi
    OLD="$(git rev-parse HEAD)"
    git commit --quiet --amend -m "site: ${LABEL} $(date -u +%Y-%m-%dT%H:%MZ)"
    git push --quiet --force-with-lease="site:${OLD}" origin site
  ) && { echo "diterbitkan: ${LABEL}"; exit 0; }
  echo "push ditolak (kemungkinan bersamaan dengan workflow lain) — ulang ${i}/6"
  sleep $((5 * i))
done
echo "GAGAL menerbitkan ${LABEL}"
exit 1
