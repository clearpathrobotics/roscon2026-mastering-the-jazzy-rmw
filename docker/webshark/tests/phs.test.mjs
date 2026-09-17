// The Protocol Hierarchy table, row for row against sharkd's own req=tap&tap0=phs JSON. The
// two taps that already worked are re-checked here because phs shares the ?tap= dispatch.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { HOST, closeSession, openSession, settle, sharkd, shot } from './harness.mjs';

const FILE = 'healthy-cyclone.pcap.gz';

describe('protocol hierarchy tap', () => {
  let s, expected, rows;

  const open = async tap => {
    await s.page.goto(`${HOST}/webshark/index.html?file=${FILE}&tap=${encodeURIComponent(tap)}`,
      { waitUntil: 'networkidle2', timeout: 60000 });
    await settle(4000);
  };
  const tapHtmlLength = sel => s.page.$eval(sel, e => e.innerHTML.length);

  before(async () => {
    const truth = await sharkd({ req: 'tap', tap0: 'phs', capture: FILE });
    expected = [];
    (function walk(protos, level) {
      for (const p of protos || []) {
        expected.push({ proto: p.proto, frames: p.frames, bytes: p.bytes, level });
        walk(p.protos, level + 1);
      }
    })(truth.taps[0].protos, 0);

    s = await openSession({ width: 1700, height: 1200 });
    await open('phs');
    rows = await s.page.$$eval('#ws_tap_table table tr',
      trs => trs.map(tr => [...tr.children].map(td => td.textContent)));
  });
  after(async () => { await closeSession(s); });

  it('shows the tap toolbar', async () =>
    assert.equal(await s.page.$eval('#toolbar_tap', e => getComputedStyle(e).display), 'block'));

  it('renders the phs header', () =>
    assert.deepEqual(rows[0], ['Protocol', 'Frames', '% Frames', 'Bytes', '% Bytes']));

  it('renders one row per protocol node sharkd reports', () =>
    assert.equal(rows.length - 1, expected.length));

  it('matches sharkd on every name, count and indent', async () => {
    const mismatched = [];
    const body = rows.slice(1);
    for (let i = 0; i < Math.min(body.length, expected.length); i++) {
      const e = expected[i];
      const [name, frames, pctFrames, bytes] = body[i];
      if (name.trim() !== e.proto || Number(frames) !== e.frames || Number(bytes) !== e.bytes)
        mismatched.push(`row ${i}: got ${JSON.stringify(body[i])} want ${e.proto}/${e.frames}/${e.bytes}`);
      if (name.length - name.trimStart().length !== e.level * 4)
        mismatched.push(`row ${i}: indent ${name.length - name.trimStart().length} want ${e.level * 4}`);
      if (!/^\d+\.\d\d%$/.test(pctFrames)) mismatched.push(`row ${i}: percentage "${pctFrames}"`);
    }
    assert.deepEqual(mismatched, []);
    await shot(s.page, 'phs-ui.png');
  });

  it('nests rtps four levels in, under udp', () => {
    const rtps = rows.slice(1).filter(r => r[0].trim() === 'rtps');
    assert.ok(rtps.some(r => r[0].length - r[0].trimStart().length === 16),
      rtps.map(r => JSON.stringify(r)).join(''));
  });

  it('still renders the expert tap', async () => {
    await open('expert');
    assert.ok(await tapHtmlLength('#ws_tap_table') > 1000);
  });

  it('still renders the conv:IPv4 tap and its graph', async () => {
    await open('conv:IPv4');
    assert.ok(await tapHtmlLength('#ws_tap_table') > 1000, 'table empty');
    assert.ok(await tapHtmlLength('#ws_tap_graph') > 100, 'graph empty');
  });

  it('renders both taps when they are combined as phs;expert', async () => {
    await open('phs;expert');
    const text = await s.page.$eval('#ws_tap_table', e => e.textContent);
    assert.match(text, /Protocol Hierarchy Statistics/);
    assert.match(text, /Expert/i);
  });

  it('offers Protocol Hierarchy in the Statistics menu', async () => {
    await s.page.goto(`${HOST}/webshark/index.html?file=${FILE}`,
      { waitUntil: 'networkidle2', timeout: 60000 });
    await settle(6000);
    const href = await s.page.$eval('#menu_tap_phs', a => a.getAttribute('href')).catch(() => null);
    assert.match(String(href), /tap=phs/);
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
