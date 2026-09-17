// The red border and the tooltip on a rejected display filter come from the Dockerfile's sed
// patch on the vendored webshark-app.js, which reads data['err']. Nothing but a build-time grep
// guards that patch, so this file is where it gets exercised at runtime.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, openCapture, openSession, settle, shot } from './harness.mjs';

const FILE = 'healthy-fastdds.pcap.gz';

describe('a bad display filter', () => {
  let s, box;

  before(async () => {
    s = await openSession();
    await openCapture(s.page, FILE);
    await s.page.evaluate(() => {
      const i = document.getElementById('display_filter');
      i.value = 'rtps.sm.bogusfield';
      i.dispatchEvent(new Event('input'));
      i.dispatchEvent(new Event('change'));
    });
    await settle(2500);
    box = await s.page.evaluate(() => {
      const i = document.getElementById('display_filter');
      const cs = getComputedStyle(i);
      return { cls: i.className, bg: cs.backgroundColor, border: cs.borderColor, title: i.getAttribute('title') };
    });
  });
  after(async () => {
    await shot(s.page, 'filtererror.png', { clip: { x: 0, y: 0, width: 1800, height: 600 } });
    await closeSession(s);
  });

  it('takes the ws_gui_text_invalid class', () => assert.equal(box.cls, 'ws_gui_text_invalid'));
  it('fills the box with Wireshark red, #ffb0b0', () => assert.equal(box.bg, 'rgb(255, 176, 176)'));
  it('adds the red border our patch draws', () => assert.equal(box.border, 'rgb(255, 0, 0)'));
  it('puts sharkd\'s own reason in a tooltip', () =>
    assert.match(String(box.title), /rtps\.sm\.bogusfield/));
});
