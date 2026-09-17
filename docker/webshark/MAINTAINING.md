# Maintaining the fixture library, tests and guide

Three things describe the same fixture: `fixtures/README.md`'s table, `descriptions.tsv`'s row
in the viewer's own file list, and whichever guide section walks through it. Add a fixture and
touch only one, and the other two drift.

## Adding or re-recording a fixture

1. `./record-fixtures.sh record <name>` (needs the fleet up: `scripts/workshop -t flat up 3` then `scripts/workshop webshark up`), then `trim`, then
   `manifest`.
2. `./record-fixtures.sh verify` re-derives every count from the committed files. CI runs this
   on every PR that touches `docker/webshark/**`, so it should already pass locally before you
   push.
3. Add a row to `fixtures/README.md`, under "What each capture shows" or "The healthy ones".
   This is the prose a reader sees. `manifest.tsv` only carries numbers.
4. Add a line to `fixtures/descriptions.tsv`, copied from the README row you just wrote rather
   than re-derived. This is what the viewer's file list shows next to the filename.
5. If the fixture demonstrates a symptom the guide doesn't cover yet, add a guide section for
   it and a `fixtures.test.mjs` case that opens the file and asserts on it.

## Adding a test

- Extend an existing suite when the new case is a variant of what it already covers. Otherwise
  add a new `tests/*.test.mjs` file. Either way, `tests/README.md`'s "What each suite covers"
  table needs the matching row.
- After a full `npm test` run, update `tests/README.md`'s "Eighteen files, N tests" line to the
  count the runner actually reported. `guide.test.mjs` generates one test per guide section at
  runtime, so a static grep of the test files always undercounts.

## Changing the guide

- A new exercise, symptom section, or preset has to keep `guide.test.mjs`'s anchor check
  passing (every table-of-contents entry resolves to a real heading), and, if it's one of
  exercises 6-8, needs a matching `exercises.test.mjs` case for the count it should produce.
- `guide-screenshots.mjs` regenerates `guide-assets/` against a running container. Retake a
  screenshot when the UI it shows changes, not on a schedule.

## Before shipping any of it

`npm test` passing is necessary, not sufficient. For anything visible in the UI, load it in a
real browser and look: a filter that silently matches nothing, a column that renders in the
wrong place, or a button that never dims are all invisible to a test that only checks the HTTP
response. For prose changes (guide sections, this file, `fixtures/README.md`), read the whole
file once, not just the lines that changed. It's easy to introduce a claim one paragraph
contradicts three lines later.
