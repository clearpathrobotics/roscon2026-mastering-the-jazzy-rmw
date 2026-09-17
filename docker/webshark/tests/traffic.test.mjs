// Warnings is the only Traffic button that dims, and it dims off the capture's expert info, so
// the two fixtures here are chosen for having none and having some.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { HOST, closeSession, openCapture, openSession, settle, shot } from './harness.mjs';

const BUTTONS = ['talkers', 'conversations', 'warnings', 'protocols'];
const FASTDDS = 'healthy-fastdds.pcap.gz';
const ZENOH = 'healthy-zenoh.pcap.gz';

describe('traffic row', () => {
  let s;

  before(async () => { s = await openSession({ width: 1700, height: 1200 }); });
  after(async () => {
    await openCapture(s.page, FASTDDS);
    await settle(4000);
    await shot(s.page, 'traffic-row.png', { clip: { x: 0, y: 0, width: 1700, height: 230 } });
    await closeSession(s);
  });

  for (const [file, description, hasExpert] of [
    [FASTDDS, 'Fast DDS, no expert info', false],
    [ZENOH, 'Zenoh, 59 expert frames', true],
  ]) {
    describe(description, () => {
      let state;
      before(async () => {
        await openCapture(s.page, file, {}, 3);
        await settle(4000);   // the badge and the dim probes are serial
        state = await s.page.evaluate(ids => ids.map(i => {
          const e = document.getElementById('traffic_' + i);
          return e ? { id: i, dim: e.classList.contains('rmw-preset-dim'), tip: (e.title || '').length } : null;
        }), BUTTONS);
      });

      it('renders all four buttons with tooltips', () =>
        assert.ok(state.every(b => b && b.tip > 40), JSON.stringify(state)));

      it(`${hasExpert ? 'leaves Warnings live' : 'dims Warnings'}`, () =>
        assert.equal(state.find(b => b.id === 'warnings').dim, !hasExpert));

      it('never dims the other three', () =>
        assert.ok(state.filter(b => b.id !== 'warnings').every(b => !b.dim), JSON.stringify(state)));
    });
  }

  describe('each button\'s tap', () => {
    // The vendored bundle ships this string in the tap toolbar, which every tap view renders.
    const PLACEHOLDER = 'Placeholder for taps toolbar';
    const openTap = async (tap, file) => {
      await s.page.goto(`${HOST}/webshark/index.html?file=${file}&tap=${encodeURIComponent(tap)}`,
        { waitUntil: 'networkidle2', timeout: 60000 });
      await settle(3500);
      return s.page.evaluate(() => document.body.innerText);
    };

    for (const [tap, file] of [
      ['endpt:IPv4', FASTDDS], ['conv:UDP', FASTDDS], ['phs', FASTDDS], ['expert', ZENOH],
    ]) {
      it(`${tap} renders a table, with no placeholder left over`, async () => {
        const text = await openTap(tap, file);
        const rows = await s.page.$$eval('#ws_tap_table table tr', t => t.length);
        assert.ok(rows > 1, `${rows} rows`);
        assert.ok(!text.includes(PLACEHOLDER), `${tap} still shows the placeholder`);
      });
    }

    // expert on Fast DDS is the only empty tap view, which is where the placeholder would show.
    it('keeps the placeholder out of an expert view with nothing to show', async () => {
      const text = await openTap('expert', FASTDDS);
      assert.ok(!text.includes(PLACEHOLDER), 'placeholder survives in the empty expert view');
    });
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
