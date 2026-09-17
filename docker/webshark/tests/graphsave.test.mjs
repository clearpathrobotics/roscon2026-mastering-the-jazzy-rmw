// Advanced Graph rows are saved when Render is pressed, so a row left over from a rehearsal
// comes back on the day.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, openCapture, openSession, settle, shot } from './harness.mjs';

const FILE = 'healthy-fastdds.pcap.gz';

describe('advanced graph persistence', () => {
  let s, built;

  const rowState = () => s.page.evaluate(() => g_webshark_iograph.graphs.map(g => ({
    name: g.rmwName || '', filter: g.filter.value, style: g.style.value,
    func: g.function.value, field: g.field.value, axis: g.axis ? g.axis.value : '?' })));
  const lines = () => s.page.evaluate(() => document.querySelectorAll('#capture_graph .c3-line').length);
  const open = async () => {
    await openCapture(s.page, FILE);
    await s.page.evaluate(() => {
      if (document.getElementById('report_graph').style.display !== 'block')
        document.getElementById('capture_interval_adv').click();
    });
    await settle(500);
  };

  before(async () => {
    s = await openSession();
    await open();
  });
  after(async () => {
    await shot(s.page, 'graphsave.png', { clip: { x: 0, y: 0, width: 1800, height: 900 } });
    await closeSession(s);
  });

  describe('two rows built from the SPDP and SEDP presets', () => {
    before(async () => {
      await s.page.evaluate(() => { set_preset_mode('rate'); });
      await s.page.click('#preset_spdp');
      await settle(2500);
      await s.page.click('#preset_sedp');
      await s.page.waitForFunction(
        () => document.querySelectorAll('#capture_graph .c3-line').length >= 2,
        { timeout: 30000 }).catch(() => {});
      built = await rowState();
    });

    it('creates two rows', () => assert.equal(built.length, 2));
    it('gives both a filter', () => assert.ok(built.every(r => r.filter !== ''), JSON.stringify(built)));
    it('draws both lines', async () => assert.ok(await lines() >= 2, String(await lines())));
  });

  describe('after a reload', () => {
    let restored;
    before(async () => {
      await open();
      restored = await rowState();
      await s.page.waitForFunction(
        () => document.querySelectorAll('#capture_graph .c3-line').length >= 2,
        { timeout: 30000 }).catch(() => {});
    });

    it('restores the rows unchanged', () => assert.deepEqual(restored, built));
    it('redraws the lines without pressing Render', async () =>
      assert.ok(await lines() >= 2, String(await lines())));
  });

  describe('Clear Graphs', () => {
    it('leaves one empty row', async () => {
      await s.page.evaluate(() => clear_graphs());
      await settle(2500);
      const cleared = await rowState();
      assert.equal(cleared.length, 1);
      assert.equal(cleared[0].filter, '');
    });

    it('still leaves one empty row after a reload', async () => {
      await open();
      const cleared = await rowState();
      assert.equal(cleared.length, 1);
      assert.equal(cleared[0].filter, '');
    });
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
