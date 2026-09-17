// The Fragments preset is scoped to RTPS DATA_FRAG, so a stack that fragments at IP reads zero
// here and that zero is the answer. Both cases need asserting: a filter that only ever matched
// would pass a test written around the non-empty case alone.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, countFrames, openCapture, openSession, settle, shot } from './harness.mjs';

const FRAGMENTING = 'fragment-loss.pcap.gz';   // Cyclone, splits samples with DATA_FRAG
const IP_ONLY = 'healthy-fastdds.pcap.gz';     // Fast DDS, one large datagram the kernel splits
const FILTER = 'rtps.sm.id == 0x16';

describe('Fragments preset', () => {
  let s, applied, onCyclone, onFast, expectedCyclone, expectedFast, tip;

  const clickPreset = async file => {
    await openCapture(s.page, file);
    await settle(2000);
    await s.page.click('#preset_fragments');
    await settle(2500);
    return s.page.evaluate(() => document.getElementById('display_filter').value);
  };

  // Counts come from countFrames, never from the rendered rows, because the packet list is
  // virtualised. The row counts below are only ever asked whether they are zero, which
  // virtualisation does not affect, and that is the half sharkd cannot answer: it says how many
  // frames match, not whether clicking the button put them on screen.
  before(async () => {
    s = await openSession();
    expectedCyclone = await countFrames(FRAGMENTING, FILTER);
    expectedFast = await countFrames(IP_ONLY, FILTER);

    applied = await clickPreset(FRAGMENTING);
    onCyclone = await s.page.evaluate(() =>
      document.querySelectorAll('#packet_list_frames tr').length);
    tip = await s.page.evaluate(() =>
      document.getElementById('preset_fragments').title);

    await clickPreset(IP_ONLY);
    onFast = await s.page.evaluate(() =>
      document.querySelectorAll('#packet_list_frames tr').length);
  });
  after(async () => {
    await shot(s.page, 'fragments.png', { clip: { x: 0, y: 0, width: 1100, height: 260 } });
    await closeSession(s);
  });

  it('puts its filter in the box when clicked', () => {
    assert.equal(applied, FILTER);
  });

  it('matches DATA_FRAG on a stack that fragments in RTPS', () => {
    assert.equal(expectedCyclone, 1505, 'fixture drifted from manifest.tsv');
    assert.ok(onCyclone > 0, 'clicking the preset rendered no rows on a fragmenting capture');
  });

  it('is empty on a stack that fragments at IP instead', () => {
    assert.equal(expectedFast, 0);
    assert.equal(onFast, 0);
  });

  it('carries a tooltip that explains the empty case', () => {
    assert.match(tip, /Zero here means the stack fragments at the IP layer/);
  });

  it('logs no console errors', () => {
    assert.deepEqual(s.errors, []);
  });
});
