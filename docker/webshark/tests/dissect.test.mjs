// The Dissection buttons write sharkd preferences, so these read dumpconf rather than trusting
// that the button looks pressed.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, openCapture, openSession, settle, sharkd, shot } from './harness.mjs';

// The fragment fixture, not the discovery one: healthy-cyclone-discovery is trimmed to the
// SEDP burst and carries no DATA_FRAG at all.
const FRAG = 'fragment-loss.pcap.gz';
const OTHER = 'healthy-fastdds.pcap.gz';

const pref = async (capture, group, key) =>
  JSON.stringify((await sharkd({ req: 'dumpconf', pref: group, capture })).prefs[key]);

describe('dissection row', () => {
  let s;
  const fragLabels = () => s.page.evaluate(() =>
    [...document.querySelectorAll('#packet_list_frames tr')]
      .map(tr => tr.querySelectorAll('td')[9]?.textContent || '')
      .filter(t => t.includes('[RTPS fragment]')).length);

  before(async () => {
    s = await openSession();
    await openCapture(s.page, FRAG);
  });
  // Clearing the button only sends FALSE to whichever capture is open, and apply_dissect_prefs
  // never sends FALSE on load, so a pref set on FRAG outlives the run unless it is cleared on
  // FRAG's own session. Nothing downstream reads it today, which is exactly why it would rot
  // quietly.
  after(async () => {
    await s.page.evaluate(() => {
      const b = document.getElementById('dissect_userdata');
      if (b.classList.contains('selected')) b.click();
    });
    await settle(2000);
    await shot(s.page, 'dissect.png', { clip: { x: 0, y: 0, width: 1800, height: 560 } });
    await openCapture(s.page, FRAG);
    await s.page.evaluate(() => send_conf('rtps.enable_user_data_dissection', 'FALSE'));
    await settle(2000);
    await closeSession(s);
  });

  it('renders two toggles and a port input', async () => {
    assert.ok(await s.page.evaluate(() =>
      !!document.getElementById('dissect_userdata') && !!document.getElementById('dissect_reassembly')
      && !!document.getElementById('dissect_zenoh_port')));
  });

  it('starts with neither toggle pressed', async () => {
    assert.ok(await s.page.evaluate(() =>
      !document.getElementById('dissect_userdata').classList.contains('selected')
      && !document.getElementById('dissect_reassembly').classList.contains('selected')));
  });

  it('starts with the sharkd reassembly preference off', async () =>
    assert.equal(await pref(FRAG, 'rtps', 'rtps.enable_rtps_reassembly'), '{"b":0}'));

  it('shows no [RTPS fragment] labels before the toggle', async () =>
    assert.equal(await fragLabels(), 0));

  describe('turning Reassembly on', () => {
    let labelled;
    before(async () => {
      await s.page.click('#dissect_reassembly');
      await s.page.waitForFunction(() =>
        [...document.querySelectorAll('#packet_list_frames tr')]
          .some(tr => (tr.querySelectorAll('td')[9]?.textContent || '').includes('[RTPS fragment]')),
      { timeout: 30000 }).catch(() => {});
      labelled = await fragLabels();
    });

    it('presses the button', async () => assert.ok(await s.page.evaluate(() =>
      document.getElementById('dissect_reassembly').classList.contains('selected'))));
    it('flips the sharkd preference on', async () =>
      assert.equal(await pref(FRAG, 'rtps', 'rtps.enable_rtps_reassembly'), '{"b":1}'));
    it('labels fragments in the visible list', () => assert.ok(labelled > 0, `${labelled} rows`));
  });

  describe('turning it back off', () => {
    before(async () => {
      await s.page.click('#dissect_reassembly');
      await settle(2500);
    });

    it('puts the sharkd preference back', async () =>
      assert.equal(await pref(FRAG, 'rtps', 'rtps.enable_rtps_reassembly'), '{"b":0}'));
    it('releases the button', async () => assert.ok(await s.page.evaluate(() =>
      !document.getElementById('dissect_reassembly').classList.contains('selected'))));
  });

  describe('the User data toggle', () => {
    before(async () => {
      await s.page.click('#dissect_userdata');
      await settle(2500);
    });

    it('sets the user data preference', async () =>
      assert.equal(await pref(FRAG, 'rtps', 'rtps.enable_user_data_dissection'), '{"b":1}'));

    it('stays pressed across a reload', async () => {
      await openCapture(s.page, FRAG);
      assert.ok(await s.page.evaluate(() =>
        document.getElementById('dissect_userdata').classList.contains('selected')));
    });

    it('re-applies to the reloaded session', async () => {
      await settle(2500);
      assert.equal(await pref(FRAG, 'rtps', 'rtps.enable_user_data_dissection'), '{"b":1}');
    });

    it('re-applies to a different capture, since preferences are per session', async () => {
      await openCapture(s.page, OTHER);
      await settle(2500);
      assert.equal(await pref(OTHER, 'rtps', 'rtps.enable_user_data_dissection'), '{"b":1}');
    });
  });

  describe('the Zenoh port control', () => {
    const setPort = async value => {
      await s.page.evaluate(v => {
        const i = document.getElementById('dissect_zenoh_port');
        i.value = v;
        i.dispatchEvent(new Event('change'));
      }, value);
      await settle(2500);
    };

    it('sets both Zenoh ports', async () => {
      await setPort('7448');
      assert.equal(await pref(OTHER, 'zenoh', 'zenoh.tcp.port'), '{"u":7448}');
      assert.equal(await pref(OTHER, 'zenoh', 'zenoh.udp.port'), '{"u":7448}');
    });

    it('restores 7447 when blanked', async () => {
      await setPort('');
      assert.equal(await pref(OTHER, 'zenoh', 'zenoh.tcp.port'), '{"u":7447}');
    });
  });

  describe('dimming on an RTPS capture', () => {
    let dim;
    before(async () => {
      // Wire detection runs several async counts behind the badge, so dimming settles late.
      await s.page.waitForFunction(
        () => document.getElementById('preset_zenoh_declare').classList.contains('rmw-preset-dim'),
        { timeout: 60000 });
      dim = await s.page.evaluate(() => ({
        userdata: document.getElementById('dissect_userdata').classList.contains('rmw-preset-dim'),
        reassembly: document.getElementById('dissect_reassembly').classList.contains('rmw-preset-dim'),
        zenohPort: document.getElementById('dissect_zenoh_label').classList.contains('rmw-preset-dim'),
        userdataTip: document.getElementById('dissect_userdata').title,
      }));
    });

    // Reassembly is the only one a matching wire is sufficient for. User data additionally
    // needs a TypeObject in the capture, and this fixture has none, so it dims on the probe.
    it('leaves Reassembly at full strength', () => assert.equal(dim.reassembly, false));
    it('dims User data, because there is no TypeObject to decode against', () =>
      assert.equal(dim.userdata, true));
    it('dims the Zenoh port control', () => assert.equal(dim.zenohPort, true));

    // The premise the User data dimming rests on, taken from sharkd rather than from the page.
    it('agrees with sharkd that the fixture holds no TypeObject', async () => {
      const frames = await sharkd({ req: 'frames', capture: OTHER, filter: 'rtps.type_object_v2', limit: 50 });
      assert.ok(Array.isArray(frames), JSON.stringify(frames));
      assert.equal(frames.length, 0);
    });

    it('names the TypeObject reason in the User data tooltip', () =>
      assert.match(dim.userdataTip, /TypeObject/));
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
