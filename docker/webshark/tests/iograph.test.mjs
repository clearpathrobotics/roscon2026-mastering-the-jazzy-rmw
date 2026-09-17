// The Advanced graph's axis labels name a bucket width, so they are asserted against the
// interval actually sent on req=iograph rather than against sharkd's 1000 ms default.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { HOST, closeSession, openSession, settle, sharkd, shot } from './harness.mjs';

const FILE = 'healthy-cyclone.pcap.gz';
const STEPS = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000];

describe('advanced graph axis labels', () => {
  let s, expectMs;
  const intervals = [];

  // Scope every selector to #capture_graph. The capture-summary chart under #capture_interval
  // carries its own .c3-axis-y-label, and an unscoped querySelector reads that one instead.
  const labels = () => s.page.evaluate(() => {
    const t = sel => { const e = document.querySelector('#capture_graph ' + sel); return e ? e.textContent : null; };
    const y2 = document.querySelector('#capture_graph .c3-axis-y2');
    return {
      y: t('.c3-axis-y-label'),
      y2: t('.c3-axis-y2-label'),
      x: t('.c3-axis-x-label'),
      y2Shown: !!y2 && getComputedStyle(y2).visibility !== 'hidden',
      lines: document.querySelectorAll('#capture_graph .c3-line').length,
    };
  });

  before(async () => {
    // Ground truth for the bucket width, computed the way graph_interval_ms() does.
    const status = await sharkd({ req: 'status', capture: FILE });
    const target = (status.duration * 1000) / 300;
    expectMs = STEPS.find(step => step >= target) || STEPS[STEPS.length - 1];

    s = await openSession({ width: 1700, height: 1200 });
    s.page.on('request', r => {
      const m = r.url().includes('req=iograph') && r.url().match(/[?&]interval=(\d+)/);
      if (m) intervals.push(parseInt(m[1], 10));
    });
    await s.page.goto(`${HOST}/webshark/index.html?file=${FILE}`,
      { waitUntil: 'networkidle2', timeout: 60000 });
    await s.page.waitForFunction(() => window.g_capture_duration > 0, { timeout: 30000 });
    await s.page.evaluate(() => show_hide_graph('report_graph', 'capture_interval_adv'));
  });
  after(async () => {
    await shot(s.page, 'iograph.png');
    await closeSession(s);
  });

  describe('a preset row', () => {
    let L;
    // run_preset only draws a graph in rate mode; the default mode sets the display filter
    // instead and leaves #capture_graph empty.
    before(async () => {
      await s.page.evaluate(() => { set_preset_mode('rate'); run_preset('sedp'); });
      await settle(2500);
      L = await labels();
    });

    it('names the unit and the live bucket width on y', () =>
      assert.equal(L.y, `Packets / ${expectMs} ms`));
    it('sends that same interval on the wire', () =>
      assert.equal(intervals.at(-1), expectMs, `intervals=${intervals}`));
    it('draws a line', () => assert.ok(L.lines > 0, `lines=${L.lines}`));
  });

  describe('a second row on y2 with a different unit', () => {
    let L;
    before(async () => {
      await s.page.evaluate(() => {
        add_graph();
        const g = g_webshark_iograph.graphs[g_webshark_iograph.graphs.length - 1];
        g['filter'].value = 'rtps';
        g['function'].value = 'bytes';
        g['axis'].value = 'y2';
        render_graph();
      });
      await settle(2500);
      L = await labels();
      await shot(s.page, 'iograph-y2.png', { clip: await s.page.$eval('#report_graph', e => {
        const r = e.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: Math.min(r.height, 500) };
      }) });
    });

    it('labels y2 with its own unit', () => assert.equal(L.y2, `Bytes / ${expectMs} ms`));
    it('leaves the y label alone', () => assert.equal(L.y, `Packets / ${expectMs} ms`));
    it('shows the y2 axis', () => assert.equal(L.y2Shown, true));
  });

  it('collapses to Mixed units when two units share an axis', async () => {
    await s.page.evaluate(() => {
      const gs = g_webshark_iograph.graphs;
      gs[gs.length - 1]['axis'].value = 'y';
      render_graph();
    });
    await settle(2500);
    assert.equal((await labels()).y, `Mixed units / ${expectMs} ms`);
  });

  describe('after Clear Graphs', () => {
    let L;
    // clear_graphs replaces renderGraph outright, which is how the labels were lost before.
    before(async () => {
      await s.page.evaluate(() => clear_graphs());
      await settle(2500);
      L = await labels();
    });

    it('keeps the x label', () => assert.equal(L.x, `Time (s), ${expectMs} ms buckets`));
    it('keeps a y label on the blank row', () => assert.equal(L.y, `Packets / ${expectMs} ms`));
    it('rebuilds the table to exactly one row', async () =>
      assert.equal(await s.page.$$eval('#capture_graph_table tr', rs => rs.length), 1));
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
