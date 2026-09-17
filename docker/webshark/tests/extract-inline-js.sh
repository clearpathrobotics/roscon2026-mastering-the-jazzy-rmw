#!/usr/bin/env bash
# Pull the inline <script> blocks out of index.html into one file eslint can read, and append
# a generated reference for every function named by an inline event attribute.
#
# Without that appendix, eslint reports about twenty no-unused-vars errors on functions that
# are reached only from onclick= and onchange=, which it cannot see. Silencing the rule would
# hide real ones. Generating the references instead turns the noise into a check: an attribute
# naming a function that does not exist becomes a no-undef error, which is a typo eslint had
# no way to catch before.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:-$HERE/../index.html}"
OUT="${2:-$HERE/.inline.js}"

python3 - "$SRC" "$OUT" <<'PY'
import re, sys
src, out = sys.argv[1], sys.argv[2]
html = open(src, encoding='utf-8').read()

blocks = [m.group(1) for m in
          re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S | re.I)]

# Identifiers named by an inline handler attribute: onclick="foo(1)" -> foo. Both quote
# styles: this file uses double quotes for onclick and single for onchange.
handlers = set()
for m in re.finditer(r'\bon[a-z]+\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', html, re.I):
    handlers.update(re.findall(r'([A-Za-z_$][\w$]*)\s*\(', m.group(1) or m.group(2)))

# Top-level g_* are page globals the vendored bundle reads. webshark-app.js is not in the
# repo (it lives in the image), so there is nothing to cross-check against at lint time and
# eslint sees only the assignment. The cost is that a genuinely dead g_* goes unreported;
# the alternative was four permanent errors, which would bury a real one.
shared = sorted(set(re.findall(r'\bvar\s+(g_[\w$]+)', '\n'.join(blocks))))

with open(out, 'w', encoding='utf-8') as f:
    f.write('\n'.join(blocks))
    f.write('\n\n/* generated: reached only from inline event attributes or the vendored bundle */\n')
    f.write('void [\n')
    for h in sorted(handlers) + shared:
        f.write('  %s,\n' % h)
    f.write('];\n')

print('%d script blocks, %d inline handlers, %d shared globals'
      % (len(blocks), len(handlers), len(shared)))
PY
