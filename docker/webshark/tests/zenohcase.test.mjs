// A Zenoh capture has no RTPS in it at all, so every RTPS control on the page has nothing to
// act on.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, openCapture, openSession, settle, sharkd, shot } from './harness.mjs';

const FILE = 'healthy-zenoh.pcap.gz';

describe('dissection row on a Zenoh capture', () => {
  let s, dim;

  before(async () => {
    s = await openSession();
    await openCapture(s.page, FILE);
    // Wire detection runs four async count() calls behind the badge, so dimming settles late.
    await s.page.waitForFunction(
      () => document.getElementById('preset_spdp').classList.contains('rmw-preset-dim'),
      { timeout: 60000 });
    dim = await s.page.evaluate(() => ({
      spdp: document.getElementById('preset_spdp').classList.contains('rmw-preset-dim'),
      userdata: document.getElementById('dissect_userdata').classList.contains('rmw-preset-dim'),
      reassembly: document.getElementById('dissect_reassembly').classList.contains('rmw-preset-dim'),
    }));
  });
  after(async () => {
    await shot(s.page, 'zenohcase.png', { clip: { x: 0, y: 0, width: 1800, height: 420 } });
    await closeSession(s);
  });

  it('renders the Dissection row', async () =>
    assert.ok(await s.page.evaluate(() => !!document.getElementById('dissect_userdata'))));

  it('dims the RTPS presets', () => assert.equal(dim.spdp, true));

  it('dims the RTPS dissection toggles alongside them', () =>
    assert.deepEqual({ userdata: dim.userdata, reassembly: dim.reassembly },
      { userdata: true, reassembly: true }));

  it('keeps the list populated when an RTPS preference is toggled anyway', async () => {
    const before_ = await s.page.evaluate(() => document.querySelectorAll('#packet_list_frames tr').length);
    await s.page.click('#dissect_reassembly');
    await settle(3000);
    const after_ = await s.page.evaluate(() => document.querySelectorAll('#packet_list_frames tr').length);
    assert.ok(after_ > 5, `${before_} -> ${after_}`);
    await s.page.click('#dissect_reassembly');
    await settle(2000);
  });

  it('applies the Zenoh port on the capture it is for', async () => {
    await s.page.evaluate(() => {
      const i = document.getElementById('dissect_zenoh_port');
      i.value = '7448';
      i.dispatchEvent(new Event('change'));
    });
    await settle(3000);
    const prefs = (await sharkd({ req: 'dumpconf', pref: 'zenoh', capture: FILE })).prefs;
    assert.equal(JSON.stringify(prefs['zenoh.tcp.port']), '{"u":7448}');
    await s.page.evaluate(() => {
      const i = document.getElementById('dissect_zenoh_port');
      i.value = '';
      i.dispatchEvent(new Event('change'));
    });
    await settle(2500);
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
