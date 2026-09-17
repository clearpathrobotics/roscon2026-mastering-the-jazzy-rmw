# Tests

Headless browser suites for the Webshark UI, plus a linter for `index.html`'s inline
JavaScript. Everything here drives the real page in a real browser, because the things that
break in this UI (a filter that does not apply, a button that does not dim, a column that
renders in the wrong place) are invisible to any check that stops at the HTTP response.

They run on every pull request that touches `docker/webshark/**`, via
`.github/workflows/webshark-tests.yml`.

## Running them

```bash
cd docker/webshark
mkdir -p captures && cp fixtures/*.pcap.gz captures/
docker compose -f webshark.yml up -d --build

cd tests
npm install          # puppeteer-core only, no bundled browser
npm test             # or: WEBSHARK_URL=http://some-other-host:8085 npm test
```

Eighteen files, 226 tests, about six minutes. To run one:

```bash
npm test -- dissect.test.mjs
```

`npm run test:ci` is the same run with a JUnit report written to `junit.xml` alongside the
usual output.

The driver is `puppeteer-core` against the system browser: `/usr/bin/chromium` on the
development box, `google-chrome` on the GitHub runner, or whatever `CHROME_PATH` names.
`puppeteer` proper downloads its own browser and is not used. On Debian the
`playwright` package is broken, so do not reach for it.

Every suite reads a fixture from `../fixtures`, which is why they have to be copied into
`captures/` first. The viewer serves exactly one directory.

`arm64-check.mjs` is a plain script rather than a suite, because what it tests is that the
arm64 image serves the same page, and running it against localhost would prove nothing:

```bash
WEBSHARK_URL=http://<arm64-host>:8085 node arm64-check.mjs
```

## How the run is put together

`global-setup.mjs` launches one browser for the whole run and publishes its endpoint, so the
eighteen files share one Chromium instead of starting eighteen. A file run on its own finds no
endpoint and launches its own, which is what keeps `npm test -- one.test.mjs` working.

`harness.mjs` holds what the suites share, and is where a new helper belongs.

Two settings are load-bearing:

- **Concurrency is 1.** Dissection preferences live on the sharkd session rather than in the
  browser, so two files toggling them at once would fight.
- **Each file gets its own browser context.** Hidden columns and saved graph rows live in
  `localStorage`, so under one shared context a file that ends with columns hidden decides what
  the next file sees. `colvis.test.mjs` is the one that would notice, because it filters on
  visibility. `columns.test.mjs` reads `th` elements without filtering, so it survives the leak.

## Linting

```bash
npm run lint
```

Expect zero errors. Anything reported is new.

`index.html` keeps its JavaScript in one inline `<script>`, which eslint cannot read directly.
`extract-inline-js.sh` pulls it into `.inline.js` and appends a generated block referencing
every function named by an inline `onclick=` or `onchange=` attribute.

Without that appendix eslint reports about twenty `no-unused-vars` errors on
functions it cannot see being called, and a real error hides in the noise. With it, an event
attribute naming a function that does not exist becomes a `no-undef` error, which is a typo
nothing caught before.

Top-level `g_*` variables are referenced the same way. They are page globals the vendored
`webshark-app.js` reads, and that file lives in the image rather than the repo, so there is
nothing to cross-check against here.

## What each suite covers

| Suite | Covers |
|---|---|
| `applyfilter`, `applyfilter-edge` | The frame tree's filter glyph applying in place, and modifier-click still opening a tab |
| `capturegone` | A capture deleted, never-existing, or unsized under an open page reading as an error, not blank fields or undefined |
| `columns` | The ten packet-list columns, against tshark's own values |
| `colvis` | The Columns menu hiding columns in every header, the menu bar's own order, and the choice persisting |
| `dissect` | The Dissection row's toggles reaching sharkd's preferences, and which of them dim on an RTPS capture |
| `exercises` | Every count guide section 8's fixture exercises tell a reader to expect |
| `filtercount` | The count beside the filter box, against sharkd's own answer, filtered and cleared and after a scroll |
| `filtererror` | A rejected display filter turning red and carrying sharkd's reason, both from the Dockerfile's `data['err']` patch |
| `fixtures` | Every committed fixture opening and showing the thing it is named for |
| `fragments` | The Fragments preset against RTPS DATA_FRAG, both the fixture that has it and the one that fragments at IP instead |
| `graphsave` | Advanced Graph rows surviving a reload |
| `guide` | `guide.html` rendering, and every table-of-contents anchor resolving |
| `iograph` | Y-axis labels on the Advanced graph |
| `phs` | The Protocol Hierarchy table against sharkd's own tap output |
| `rmw-presets` | The capture-level vendor badge, preset dimming by wire, SPDP's filter and count, rate-graph mode, and the `?graph=` deep-link |
| `traffic` | The four Traffic buttons, their dimming, each one's tap, and an upstream placeholder staying gone from all of them |
| `zenohcase` | The Dissection row on a Zenoh capture, where there is no RTPS at all |

## Writing another one

Three things will waste an afternoon if nobody tells you.

**The packet list is virtualized.** `#packet_list_frames tr` stays at about 101 rows whether
the capture holds 1752 frames or the filter matches 735, so a row count proves nothing. Assert
on the first row's text, on `#display_filter`'s value, or on the outgoing `req=frames` URL
caught with `page.on('request')`.

**To count what a filter matches, use `countFrames()`, which asks `req=intervals` and reads its
`frames` field.** It reports 0 as 0, which is what an absence assertion needs. `req=frames`
cannot do this job: it rejects `skip=0` with "must be a positive integer", so no match and one
match come back looking the same. `exercises.test.mjs` counts this way and agrees with
`tshark -Y` to the frame.

**Subtrees render collapsed, and a collapsed field's glyph has a zero-size rect**, so puppeteer
refuses to click it. `selectRow()` in the harness expands first, reading each node's own
`li.data_ws_subtree.expanded` rather than clicking every expander: the expander toggles and
remembers its state in `sessionStorage`, so a blind pass closes a tree a previous row already
opened.

Fixture counts belong in `../fixtures/manifest.tsv`, not in your head. Re-derive an expected
value from the committed fixture with `./record-fixtures.sh verify` rather than from whatever
capture you happened to be looking at.
