// The capture-level badge, preset dimming, and the rate-graph/deep-link paths all key off the
// same wire detection in apply_preset_relevance (index.html:571), so one capture per vendor
// covers badge text, dimming, and filtering together.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, countFrames, openCapture, openSession, settle, shot } from './harness.mjs';

const REPAIR_FILTER = 'rtps.sm.acknack_analysis == 3 || tcp.analysis.retransmission';
const SPDP_FILTER = 'rtps.sm.wrEntityId == 0x000100c2';

describe('RMW badge and presets', () => {
  let s;

  before(async () => { s = await openSession({ width: 1700, height: 1200 }); });
  after(async () => {
    await openCapture(s.page, 'healthy-fastdds.pcap.gz');
    await settle(3000);
    await shot(s.page, 'rmw-presets.png', { clip: { x: 0, y: 0, width: 1700, height: 90 } });
    await closeSession(s);
  });

  // 1. Badge text: vendor name plus the same repair count the Retransmits preset would find,
  // since both read from the identical filter (index.html:1044-1046).
  for (const [file, vendor] of [
    ['healthy-cyclone.pcap.gz', 'Cyclone DDS (RTPS)'],
    ['healthy-fastdds.pcap.gz', 'Fast DDS (RTPS)'],
    ['healthy-zenoh.pcap.gz', 'Zenoh'],
  ]) {
    it(`badge on ${file} names the vendor and the real repair count`, async () => {
      const repairs = await countFrames(file, REPAIR_FILTER);
      const expected = `${vendor} · ${repairs} repair event${repairs === 1 ? '' : 's'}`;

      await openCapture(s.page, file, {}, 3);
      await s.page.waitForFunction(
        () => document.getElementById('toolbar_capture_summary').textContent.length > 0,
        { timeout: 60000 });
      const text = await s.page.evaluate(() => document.getElementById('toolbar_capture_summary').textContent);
      assert.equal(text, expected);
    });
  }

  // 2. Dimming: a preset scoped to the wrong wire fades, per apply_preset_relevance's proto check.
  for (const [file, wire, expectedDim] of [
    ['healthy-fastdds.pcap.gz', 'RTPS', { spdp: false, zenoh_declare: true }],
    ['healthy-zenoh.pcap.gz', 'Zenoh', { spdp: true, zenoh_declare: false }],
  ]) {
    it(`dims the wrong-wire preset on a ${wire} capture (${file})`, async () => {
      await openCapture(s.page, file, {}, 3);
      const dimKey = wire === 'RTPS' ? 'zenoh_declare' : 'spdp';
      await s.page.waitForFunction(
        k => document.getElementById('preset_' + k).classList.contains('rmw-preset-dim'),
        { timeout: 60000 }, dimKey);
      const dim = await s.page.evaluate(() => ({
        spdp: document.getElementById('preset_spdp').classList.contains('rmw-preset-dim'),
        zenoh_declare: document.getElementById('preset_zenoh_declare').classList.contains('rmw-preset-dim'),
      }));
      assert.deepEqual(dim, expectedDim);
    });
  }

  // 3. Filtering: clicking SPDP writes the preset's own filter, and its count matches sharkd's
  // own answer for that same filter string.
  it('SPDP applies its filter and the count matches sharkd', async () => {
    const file = 'healthy-cyclone-discovery.pcap.gz';
    const expected = await countFrames(file, SPDP_FILTER);

    await openCapture(s.page, file, {}, 3);
    await s.page.click('#preset_spdp');
    await settle(3000);
    const filter = await s.page.$eval('#display_filter', e => e.value);
    assert.equal(filter, SPDP_FILTER);

    const actual = await countFrames(file, filter);
    assert.equal(actual, expected);
  });

  // 4. Rate-graph mode: switching to rate before clicking a preset adds a named series instead
  // of filtering the packet list (run_preset, index.html:559-569).
  it('rate-graph mode adds a named series instead of filtering', async () => {
    await openCapture(s.page, 'healthy-cyclone.pcap.gz', {}, 3);
    await s.page.click('#preset_mode_rate');
    await s.page.click('#preset_retransmit');
    await settle(4000);
    const rows = await s.page.evaluate(() => {
      const table = document.getElementById('capture_graph_table');
      return table ? [...table.rows].map(r => r.cells[0].textContent.trim()) : [];
    });
    assert.ok(rows.some(name => /retransmit/i.test(name)), JSON.stringify(rows));
  });

  // 5. Deep-link: ?graph= opens the Advanced graph panel on load, the way set_preset_mode's own
  // comment says it has to (index.html:552-556) so the mode radio doesn't disagree with the view.
  it('?graph= deep-link opens the graph panel on load', async () => {
    await openCapture(s.page, 'healthy-cyclone.pcap.gz', { graph: 'retransmit' }, 3);
    await settle(4000);
    const open = await s.page.evaluate(() =>
      document.getElementById('report_graph').style.display === 'block');
    assert.ok(open);
  });
});
