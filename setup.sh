#!/usr/bin/env bash
# One-step setup on macOS/Linux:  ./setup.sh        (add --names for the local names model, ~1.7 GB)
# Then:                            uv run hushmask serve --open
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

extras=(--extra proxy)
[[ "${1:-}" == "--names" ]] && extras+=(--extra ner)
echo "Installing hushmask..."
uv sync "${extras[@]}"

if command -v npm >/dev/null 2>&1; then
  echo "Building the dashboard..."
  (cd web && npm ci --no-audit --no-fund && npm run build)
else
  echo "Node.js not found: skipping the dashboard. The proxy and CLI still work."
fi

echo
echo "Done. Start it with:  uv run hushmask serve --open"
[[ "${1:-}" == "--names" ]] || echo "For names nobody listed, re-run with:  ./setup.sh --names"
