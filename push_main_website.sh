#!/usr/bin/env bash
set -euo pipefail

# Push changes to main, then rebuild and deploy website branch
git checkout main
git push origin main

source .venv/bin/activate
python -m scripts.generate

git checkout -B website
git add --force static/ index.html MonPotager.html
git commit -m "Generate static site"
git push origin website --force

git checkout main
