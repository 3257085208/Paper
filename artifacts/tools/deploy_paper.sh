#!/bin/bash
# Regenerate the paper site and push it to GitHub (Cloudflare Pages auto-builds).
set -e
ROOT="/Users/marknkx/Desktop/SCI II"
cd "$ROOT"
python3 manuscript/make_reader.py >/dev/null
python3 manuscript/make_site.py site
# publish the reproduction artifacts (tools + raw data + guide)
mkdir -p site/artifacts
rsync -a --delete --exclude ".DS_Store" tools/ site/artifacts/tools/
rsync -a --delete --exclude ".DS_Store" research_data/ site/artifacts/research_data/
mkdir -p site/artifacts/figs
rsync -a --include='*.py' --exclude='*' manuscript/figs/ site/artifacts/figs/
cp manuscript/REPRODUCE.md site/REPRODUCE.md
cp manuscript/README.md site/README.md
cd site
git add -A
if git diff --cached --quiet; then
  echo "no changes; nothing to push"
else
  git commit -m "paper update $(date '+%F %H:%M')" >/dev/null
  git push origin main
  echo "pushed"
fi
