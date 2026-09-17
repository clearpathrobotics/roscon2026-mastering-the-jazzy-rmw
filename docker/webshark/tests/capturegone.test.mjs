// A capture can vanish under an open page. scripts/workshop capture keeps a rolling ring of windows, so the
// file someone opened a minute ago gets deleted while they are still reading it. sharkd answers
// that with {"err":1,"errstr":"Nope"} and no counts, and the page has to say so rather than
// report "no new frames" over a title full of undefined.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { copyFileSync, rmSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { captureUrl, capturesDir, closeSession, openCapture, openSession, settle, sharkd, shot } from './harness.mjs';

const SRC = 'healthy-cyclone-discovery.pcap.gz';
const DOOMED = 'capturegone-doomed.pcap.gz';
const NEVER = 'capturegone-never-existed.pcap.gz';
// A file sharkd opens but cannot size: status comes back with frames and duration and no
// filesize, which is the other way the title used to print undefined.
const PARTIAL = 'capturegone-partial.pcap';

const PRESET_DOOMED = 'capturegone-preset-doomed.pcap.gz';

describe('a capture that is gone', () => {
  let s, dir, open, gone, cold, partial, deleted, preset;

  const read = () => s.page.evaluate(() => ({
    title: document.getElementById('toolbar_capture_description').textContent,
    status: document.getElementById('toolbar_capture_refresh_status').textContent,
    statusColor: getComputedStyle(document.getElementById('toolbar_capture_refresh_status')).color,
    refreshShown: getComputedStyle(document.getElementById('toolbar_capture_refresh')).display !== 'none',
    badge: document.getElementById('toolbar_capture_summary').textContent,
    rows: document.querySelectorAll('#packet_list_frames tr').length,
    dimmed: [...document.querySelectorAll('[id^=preset_].rmw-preset-dim')].map(e => e.id),
  }));

  before(async () => {
    dir = await capturesDir();
    copyFileSync(`${dir}/${SRC}`, `${dir}/${DOOMED}`);
    copyFileSync(`${dir}/${SRC}`, `${dir}/${PRESET_DOOMED}`);
    writeFileSync(`${dir}/${PARTIAL}`, randomBytes(4000));

    s = await openSession();
    await openCapture(s.page, DOOMED);
    await settle(3000);
    open = await read();

    rmSync(`${dir}/${DOOMED}`);
    deleted = await sharkd({ req: 'status', capture: DOOMED });
    await s.page.evaluate(() => refresh_capture());
    await settle(4000);
    gone = await read();

    // Neither of these renders a packet list, so openCapture's wait would never come back.
    for (const [file, into] of [[NEVER, r => (cold = r)], [PARTIAL, r => (partial = r)]]) {
      await s.page.goto(captureUrl(file), { waitUntil: 'networkidle2', timeout: 90000 });
      await settle(3000);
      into(await read());
    }

    // A preset click never calls load(), only setFilter(). It takes the intervals
    // response's err branch, not refresh_capture's, so it needs its own capture-vanished
    // check rather than inheriting the one above.
    await s.page.goto(captureUrl(PRESET_DOOMED), { waitUntil: 'networkidle2', timeout: 90000 });
    await settle(3000);
    rmSync(`${dir}/${PRESET_DOOMED}`);
    await s.page.evaluate(() => run_preset('spdp'));
    await settle(3000);
    preset = await read();
  });

  after(async () => {
    await shot(s.page, 'capturegone.png', { clip: { x: 0, y: 0, width: 1800, height: 60 } });
    await closeSession(s);
    for (const f of [DOOMED, PARTIAL, PRESET_DOOMED]) rmSync(`${dir}/${f}`, { force: true });
  });

  it('reads as an error from sharkd, not as an empty capture', () =>
    assert.equal(deleted.err, 1));

  it('opened with real totals before the delete', () =>
    assert.match(open.title, /\(\d+ frames, [\d.]+ seconds, \d+ bytes\)/));

  it('says the capture cannot be opened instead of counting undefined frames', () => {
    assert.match(gone.title, /can no longer be opened/);
    assert.doesNotMatch(gone.title, /undefined/);
  });

  it('answers a refresh with a failure rather than "no new frames"', () => {
    assert.equal(gone.status, 'capture unavailable');
    assert.equal(gone.statusColor, 'rgb(170, 0, 0)');
  });

  // The summary re-runs its wire probes on every refresh and takes silence for "no such
  // traffic", so an unguarded refresh blanked the badge and lit every preset back up, which
  // reads as the fleet having gone quiet.
  it('leaves the badge and the dimmed presets as they were', () => {
    assert.equal(gone.badge, open.badge);
    assert.deepEqual(gone.dimmed, open.dimmed);
    assert.ok(open.dimmed.length > 0, 'fixture should dim at least one preset to test against');
  });

  it('keeps the last packet list on screen, stale rather than empty', () =>
    assert.equal(gone.rows, open.rows));

  it('says the same on a capture that was already gone before the page loaded', () => {
    assert.match(cold.title, /can no longer be opened/);
    assert.doesNotMatch(cold.title, /undefined/);
  });

  it('offers no Refresh on a capture it never read', () =>
    assert.equal(cold.refreshShown, false));

  it('omits a missing size rather than printing undefined bytes', () => {
    assert.match(partial.title, /\(0 frames, 0 seconds\)/);
    assert.doesNotMatch(partial.title, /undefined/);
  });

  it('says the same when a preset click is what discovers the capture is gone', () => {
    assert.match(preset.title, /can no longer be opened/);
    assert.doesNotMatch(preset.title, /undefined/);
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
