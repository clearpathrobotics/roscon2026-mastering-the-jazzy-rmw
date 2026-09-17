// The count beside the filter box reads cached_columns.length off a fetchColumns hook rather
// than issuing its own request, so it is only correct as long as upstream keeps setting that
// length from the intervals response. Assert it against sharkd's own answer, not a constant.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, countFrames, openCapture, openSession, settle, sharkd, shot } from './harness.mjs';

const FILE = 'healthy-cyclone-discovery.pcap.gz';
const SPDP = 'rtps.sm.wrEntityId == 0x000100c2';

describe('displayed-frame count', () => {
  let s, total, unfiltered, spdp, empty, cleared, scrolled;

  const read = () => s.page.evaluate(() => {
    const e = document.getElementById('display_filter_count');
    return { text: e.textContent, color: getComputedStyle(e).color };
  });
  const apply = async filter => {
    await s.page.evaluate(f => preset_filter(f), filter);
    await settle(2500);
    return read();
  };

  before(async () => {
    s = await openSession();
    total = (await sharkd({ req: 'status', capture: FILE })).frames;
    await openCapture(s.page, FILE);
    await settle(2500);
    unfiltered = await read();
    spdp = await apply(SPDP);
    empty = await apply('zenoh');
    cleared = await apply('');
    await apply(SPDP);
    // fetchColumns runs again on scroll with load_first false, which carries no new total.
    await s.page.evaluate(() => {
      const t = document.getElementById('packet_list_frames');
      if (t && t.parentNode) t.parentNode.scrollTop = 4000;
    });
    await settle(2500);
    scrolled = await read();
  });
  after(async () => {
    await shot(s.page, 'filtercount.png', { clip: { x: 0, y: 0, width: 1100, height: 60 } });
    await closeSession(s);
  });

  it('stays blank while no filter is set', () => assert.equal(unfiltered.text, ''));

  it('agrees with sharkd on a filter that matches', async () =>
    assert.equal(spdp.text, `${await countFrames(FILE, SPDP)} of ${total} displayed`));

  it('says zero rather than going blank when nothing matches', () =>
    assert.equal(empty.text, `0 of ${total} displayed`));

  it('reddens on zero, because that is the case being mistaken for a fault', () =>
    assert.equal(empty.color, 'rgb(170, 0, 0)'));

  it('goes back to blank when the filter is cleared', () => assert.equal(cleared.text, ''));

  it('survives a scroll', async () =>
    assert.equal(scrolled.text, `${await countFrames(FILE, SPDP)} of ${total} displayed`));

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
