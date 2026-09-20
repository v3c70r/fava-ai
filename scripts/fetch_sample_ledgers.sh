#!/usr/bin/env bash
# Fetch external sample Beancount ledgers for manual analysis / perf testing.
#
# These repositories are NOT vendored into this project (licenses are
# unknown or GPL-2.0), so they are cloned into .sample-ledgers/ which is
# gitignored. Use them for local analysis only.
#
# Usage:  scripts/fetch_sample_ledgers.sh [target_dir]
# Then:   FAVA_AI_SAMPLE_LEDGERS=$PWD/.sample-ledgers python3 scripts/analyze_ledgers.py
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-$REPO_ROOT/.sample-ledgers}"

mkdir -p "$TARGET"

# name|url|license-note
REPOS=(
  "beancount-boilerplate-cn|https://github.com/mckelvin/beancount-boilerplate-cn|no license - local analysis only"
  "finzytrack|https://github.com/sagarbehere/finzytrack|GPL-2.0 - local analysis only"
  "cfo-stack|https://github.com/MikeChongCan/cfo-stack|NOASSERTION - local analysis only"
  "beancount-example-wileykestner|https://github.com/wileykestner/beancount-example|no license - local analysis only"
  "beancount-example-jmgilman|https://github.com/jmgilman/beancount-example|MIT"
  "beancount-examples-peberanek|https://github.com/peberanek/beancount-examples|no license - local analysis only"
  "beancount-upstream|https://github.com/beancount/beancount|GPL-2.0 - contains examples/example.beancount"
)

for entry in "${REPOS[@]}"; do
  IFS='|' read -r name url note <<< "$entry"
  dest="$TARGET/$name"
  if [ -d "$dest/.git" ]; then
    echo "==> updating $name"
    git -C "$dest" pull --ff-only --quiet || echo "    (update failed, keeping existing checkout)"
  else
    echo "==> cloning $name ($note)"
    git clone --depth 1 --quiet "$url" "$dest" || echo "    (clone failed, skipping)"
  fi
done

echo
echo "Sample ledgers available in: $TARGET"
echo "Note: these are external repositories with their own licenses; do not commit them."
