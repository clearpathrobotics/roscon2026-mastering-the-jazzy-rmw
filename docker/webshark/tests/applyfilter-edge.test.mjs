// The cases apply-as-filter could plausibly break on, none of which applyfilter.test.mjs
// reaches. The tap reports are in here because their filter links look identical to the tree's
// and are deliberately outside the delegate's scope.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { HOST, clickElement, closeSession, fieldGlyph, openCapture, openSession, selectRow, settle }
  from './harness.mjs';

const ZENOH = 'healthy-zenoh.pcap.gz';
const DDS = 'healthy-cyclone-discovery.pcap.gz';

describe('apply as filter, edge cases', () => {
  let s, newTargets = [];

  const applied = () => s.page.evaluate(() =>
    [g_webshark.filter, document.getElementById('display_filter').value]);

  before(async () => {
    s = await openSession();
    s.browser.on('targetcreated', t => { if (t.type() === 'page') newTargets.push(t); });
  });
  after(async () => { await closeSession(s); });

  describe('on a Zenoh capture, where the RTPS presets are dimmed', () => {
    let glyphFilter, result;

    before(async () => {
      await openCapture(s.page, ZENOH);
      await selectRow(s.page, 2);
      newTargets = [];
      const [glyph, filter] = await fieldGlyph(s.page, f => /^(zenoh|tcp|udp)\./.test(f));
      glyphFilter = filter;
      if (glyph) {
        await clickElement(s.page, glyph);
        await settle(3000);
        result = await applied();
      }
    });

    it('offers a glyph in the Zenoh tree', () => assert.ok(glyphFilter, 'no zenoh/tcp/udp field glyph'));
    it('applies it', () => assert.deepEqual(result, [glyphFilter, glyphFilter]));
    it('opens no tab', () => assert.equal(newTargets.length, 0));
  });

  describe('the top-level node, whose filter matches every frame', () => {
    let result;

    before(async () => {
      await openCapture(s.page, DDS);
      await selectRow(s.page, 1);
      const [glyph] = await fieldGlyph(s.page, f => f === 'frame');
      assert.ok(glyph, 'no bare protocol filter on the top-level node');
      await clickElement(s.page, glyph);
      await settle(3000);
      result = await applied();
    });

    it('applies rather than being swallowed as a no-op', () => assert.deepEqual(result, ['frame', 'frame']));
    it('leaves the list populated', async () =>
      assert.ok(await s.page.evaluate(() => document.querySelectorAll('#packet_list_frames tr').length) > 1));

    it('survives Refresh', async () => {
      await s.page.click('#toolbar_capture_refresh');
      await settle(4000);
      assert.deepEqual(await applied(), ['frame', 'frame']);
    });
  });

  describe('a tap report, which the delegate cannot reach', () => {
    let link;

    // The Traffic buttons open their report in a new tab, so drive the tap deep-link directly.
    before(async () => {
      await s.page.goto(`${HOST}/webshark/index.html?file=${DDS}&tap=${encodeURIComponent('conv:UDP')}`,
        { waitUntil: 'networkidle2', timeout: 60000 });
      await s.page.waitForFunction(
        () => document.querySelectorAll('#ws_tap_table table tr').length > 2, { timeout: 30000 });
      newTargets = [];
      link = (await s.page.$$('#ws_tap_table a[href]'))[0];
    });
    after(async () => {
      for (const t of newTargets) { const p = await t.page(); if (p) await p.close().catch(() => {}); }
    });

    it('renders filter links', () => assert.ok(link, 'no links in the tap table'));

    // The boundary is structural: the tap table hangs off toolbar_tap, so the delegate on
    // ws_packet_detail_view cannot see it. A tap row does apply its filter in place, but that
    // is upstream's own webshark_tap_row_on_click_filter.
    it('sits outside the delegate container', async () =>
      assert.ok(await s.page.evaluate(() => !document.getElementById('ws_packet_detail_view')
        .contains(document.getElementById('ws_tap_table')))));

    it('still opens its own window', async () => {
      await clickElement(s.page, link);
      await settle(3000);
      assert.equal(newTargets.length, 1);
    });
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
