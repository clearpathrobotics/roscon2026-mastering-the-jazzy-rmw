#!/usr/bin/env bash
# Lint index.html's inline JavaScript. Expect zero errors; anything reported is new.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
./extract-inline-js.sh
node --check .inline.js
npx --yes eslint@9 -c eslint.config.mjs .inline.js
echo "lint clean"
