# Licences and provenance for the webshark image

The viewer is a modified copy of QXIP's node-webshark, so `index.html`, `root.js` and
`sharkd_dict.js` are **GPL-2.0-or-later**, with the text in `LICENSE` next to this file.
Everything else here is Apache-2.0. The image also ships a lot of other people's software,
listed below.

## The viewer

| | |
|---|---|
| Upstream | [QXIP/node-webshark](https://github.com/QXIP/node-webshark) |
| Commit | `4615493c36c5020592700b06198b3f9188556e99`, 2020-11-29 |
| Image | `qxip/webshark@sha256:2a4de07772d566f910418e87014f58da379f696a55b874fb685d174cfb6ca349` |
| Licence | GPL-2.0-or-later |
| Copyright | © 2016 Jakub Zawadzki; © 2020 QXIP B.V. |

node-webshark is itself a fork of [webshark](https://bitbucket.org/jwzawadzki/webshark) by
Jakub Zawadzki.

QXIP relicensed node-webshark to AGPL-3.0 after the snapshot we build from, so the GitHub page
shows AGPL-3.0 today while the code we received is GPL-2.0. The 2020 terms are the ones that
apply, since a later relicence does not change the copy we already had.

The "or later" needs justifying, because both repo-level statements in the pinned image say
plain GPL-2.0: the `LICENSE` file, and `"license": "GPLv2"` in
`api/package.json`. It comes instead from Jakub Zawadzki's frontend modules, whose headers
offer "either version 2 of the License, or (at your option) any later version". The three
files we modified carry no headers of their own.

QXIP's own relicence supports that reading. Taking the project to AGPL-3.0 is only lawful if
the tree was GPL-2.0-or-later, since they do not hold Zawadzki's copyright and GPL-2.0-only
cannot be moved to AGPL-3.0. The bundled `clusterize.js` being GPLv3 only works for the same
reason.

## Statement of changes

GPL-2.0 section 2(a) asks that modified files say they were modified and when. Three files in
this directory replace their upstream counterparts at build time, and the Dockerfile patches a
fourth in place.

| This file | Replaces | Changed |
|---|---|---|
| `index.html` | `web/index.html` | 2026-08-16 to 2026-09-01 |
| `root.js` | `api/services/root.js` | 2026-08-16 to 2026-09-01 |
| `sharkd_dict.js` | `api/custom_module/sharkd_dict.js` | 2026-08-06 to 2026-08-17 |

**`sharkd_dict.js`** translates between webshark's request format and sharkd's. Upstream was
written for sharkd 3.x; this image ships Wireshark 4.6, whose sharkd speaks JSON-RPC 2.0 and
changed several payload shapes.

**`root.js`** adds each file's mtime to the file listing so the frontend can sort newest-first,
widens the capture-file allow-list from `.pcap` alone to `.pcap`, `.pcapng` and `.cap`, gzipped
or not, and adds a per-fixture description read from `fixtures/descriptions.tsv`.

**`index.html`** has the most changes. It adds a manual refresh control and a frame count for live
captures, a visible border on the statistics toolbar, a capture-level badge naming the RMW
vendor and counting repair events, RMW preset filter buttons, a Clear Graphs control, a
rewritten Advanced graph with named series and a selectable bucket width and a second Y axis,
deep-linking parameters, a Columns menu, a Dissection row for sharkd preferences, a Traffic
report row, apply-as-filter in place of the popup window, a link to the field guide, and a
loading message in the toolbar for a capture sharkd is still reading. It also
drops upstream's remote favicon and logo, a GitHub-hosted PNG fetched on every page view, and uses
the one already bundled with the image. The toolbar's upload link goes too, since the Dockerfile
removes the backend route it pointed at.

**`web/js/webshark-app.js`** stays upstream's file but the Dockerfile rewrites three lines in
it with `sed` (see the three `Frontend patch` blocks in `Dockerfile`): Follow-Stream links appear for single-follow
captures, the file list sorts on mtime, and a bad display filter's error is surfaced on the
filter box instead of being dropped.

Everything else in this directory is original work under the root Apache-2.0 licence: the field
guide, the Dockerfile, the compose files, `demo`, `record-fixtures.sh`, `shell-hint.sh`,
`colorfilters`, the fixtures and the test suites.

## Bundled with the viewer

These ship inside the upstream image and we redistribute them unchanged.

| Component | Version | Licence | Copyright |
|---|---|---|---|
| D3 | 4.13.0 | BSD-3-Clause | © 2018 Mike Bostock |
| C3.js | 0.5.4 | MIT | C3 Team and contributors |
| Clusterize.js | 0.16.1 | **GPL-3.0** | © 2015 Denis Lukov |
| wavesurfer.js | 1.3.2 | **CC-BY-3.0** | katspaugh and contributors |
| Awesomplete | bundled | MIT | Lea Verou |
| OpenLayers | 2.x | BSD-2-Clause | © 2006-2013 OpenLayers Contributors |

The Node backend pulls roughly 395 packages, led by fastify, promise-socket, async-lock and
node-fetch. They are permissive (MIT, ISC, BSD) and their texts travel in each package's own
directory under `node_modules` in the image.

Two are unusual. Clusterize.js is GPLv3, so the upstream bundle was already GPLv3-effective
before we touched it, which works only because everything around it is "or later".
wavesurfer.js is CC-BY-3.0, a licence meant for creative work rather than software. Both are
upstream's choices.

## Added by this image

| Component | Licence | How it gets here |
|---|---|---|
| Wireshark, tshark, sharkd | GPL-2.0-or-later | `ppa:wireshark-dev/stable`, Wireshark 4.6 |
| [zenoh-dissector](https://github.com/eclipse-zenoh/zenoh-dissector) | **GPL-3.0-or-later** | 1.9.0 release binary on amd64, built from commit `37c21100` on arm64 |
| Ubuntu 24.04 base | various, per package | `ubuntu:24.04` |
| Python, matplotlib, pandas | PSF, BSD-3-Clause | Ubuntu archive |

## What this means if you redistribute the image

The image contains GPL-2.0-or-later and GPL-3.0-or-later code, so passing it on carries the
usual obligation to offer corresponding source. For the parts we modified, this repository is
that source. For Wireshark, the zenoh dissector and the Ubuntu packages, upstream's own
distributions are.

No AGPL code is involved, so running the viewer as a network service creates no additional
source-offer obligation. Pinning the 2020 snapshot is what keeps it that way, and we license
our changes to match.
