// A plain click on a frame-tree field's glyph has to apply that filter in place. Upstream's
// handler opens a 500x1000 popup and re-reads the whole capture instead, which is what these
// are guarding against.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { clickElement, closeSession, fieldGlyph, openCapture, openSession, selectRow, settle }
  from './harness.mjs';

const CAP = 'healthy-cyclone-discovery.pcap.gz';

describe('apply as filter', () => {
  let s, frameRequests = [], newTargets = [];

  const state = () => s.page.evaluate(() => ({
    box: document.getElementById('display_filter').value,
    applied: g_webshark.filter,
    rows: [...document.querySelectorAll('#packet_list_frames tr')]
      .map(tr => tr.querySelectorAll('td')[0]?.textContent),
    url: window.location.href,
  }));
  const waitForFilter = f => s.page.waitForFunction(
    want => g_webshark.filter === want, { timeout: 20000 }, f).catch(() => {});
  const appliedFilters = () =>
    frameRequests.map(u => (u.split('filter=')[1] || '').split('&')[0]);

  before(async () => {
    s = await openSession();
    s.page.on('request', r => {
      if (r.url().includes('req=frames')) frameRequests.push(decodeURIComponent(r.url()));
    });
    s.browser.on('targetcreated', t => { if (t.type() === 'page') newTargets.push(t); });
  });
  after(async () => { await closeSession(s); });

  describe('a plain click', () => {
    let before_, after_;

    before(async () => {
      await openCapture(s.page, CAP);
      before_ = await state();
      await selectRow(s.page, 3);
      frameRequests = []; newTargets = [];
      const [glyph] = await fieldGlyph(s.page, f => f === 'frame.number == 4');
      assert.ok(glyph, 'the tree offers no frame.number glyph to click');
      await clickElement(s.page, glyph);
      await waitForFilter('frame.number == 4');
      await settle(2500);
      after_ = await state();
    });

    it('applies the filter to the session', () => assert.equal(after_.applied, 'frame.number == 4'));
    it('puts it in the display filter box', () => assert.equal(after_.box, 'frame.number == 4'));
    it('narrows the packet list to the one frame', () => assert.deepEqual(after_.rows, ['4']));
    it('narrowed from a wider list', () => assert.ok(before_.rows.length > 1, `${before_.rows.length} rows`));
    it('sends a filtered frames request', () =>
      assert.ok(frameRequests.some(u => u.includes('filter=frame.number == 4')), appliedFilters().join(' | ')));
    it('opens no tab or popup', () => assert.equal(newTargets.length, 0));
    it('does not navigate the page', () => assert.equal(after_.url, before_.url));
  });

  describe('a second click', () => {
    let second;

    // 450 is frame 4's length. Row 0 is frame 4 here, not frame 1: the first click narrowed the
    // list to frame.number == 4, so the only row left is the one this selects. Any field would
    // do; the point is that the second filter replaces the first rather than stacking on it.
    before(async () => {
      await selectRow(s.page, 0);
      frameRequests = [];
      const [glyph] = await fieldGlyph(s.page, f => f === 'frame.len == 450');
      assert.ok(glyph, 'the tree offers no frame.len glyph to click');
      await clickElement(s.page, glyph);
      await waitForFilter('frame.len == 450');
      await settle(2000);
      second = await state();
    });

    it('replaces the first filter', () => assert.equal(second.applied, 'frame.len == 450'));
    it('follows in the display filter box', () => assert.equal(second.box, 'frame.len == 450'));
    // Row count says nothing here: the list is virtualised, so it renders the same window size
    // whatever the filter. The refetch is what proves the list is not still on frame.number.
    it('refetches on the second filter and not the first', () => {
      assert.ok(frameRequests.some(u => u.includes('filter=frame.len == 450')), appliedFilters().join(' | '));
      assert.ok(!frameRequests.some(u => u.includes('filter=frame.number == 4')), appliedFilters().join(' | '));
    });
  });

  describe('a modifier-click', () => {
    let modified;

    before(async () => {
      await openCapture(s.page, CAP);
      await selectRow(s.page, 3);
      frameRequests = []; newTargets = [];
      const [glyph] = await fieldGlyph(s.page, f => f === 'frame.number == 4');
      await clickElement(s.page, glyph, { ctrl: true });
      await settle(3000);
      modified = await state();
    });
    after(async () => {
      for (const t of newTargets) { const p = await t.page(); if (p) await p.close().catch(() => {}); }
    });

    it('opens a tab', () => assert.equal(newTargets.length, 1));
    it('leaves this page unfiltered', () => assert.ok(!modified.applied, JSON.stringify(modified.applied)));
    it('leaves the display filter box empty', () => assert.equal(modified.box, ''));
  });

  describe('a framenum link', () => {
    let link, result;

    // On the fragment fixture, because a framenum link only exists where one frame references
    // another. Discovery traffic references nothing, so healthy-cyclone-discovery has none;
    // fragment-loss is full of them, one per IP fragment pointing at its reassembly frame.
    before(async () => {
      await openCapture(s.page, 'fragment-loss.pcap.gz');
      for (const row of [0, 1, 2, 5, 10, 20]) {
        await selectRow(s.page, row);
        for (const h of await s.page.$$('#ws_packet_detail_view a[href]')) {
          const p = await h.evaluate(a => ({
            filter: new URL(a.href).searchParams.get('filter'),
            frame: new URL(a.href).searchParams.get('frame'),
          }));
          if (p.frame && !p.filter) { link = h; break; }
        }
        if (link) break;
      }
      if (link) {
        newTargets = [];
        await clickElement(s.page, link);
        await settle(2500);
        result = await state();
      }
    });

    it('exists in the fragment fixture', () => assert.ok(link, 'no framenum link found in 6 rows'));
    it('sets no display filter, because it carries frame= and not filter=', () => {
      assert.ok(!result.applied, JSON.stringify(result.applied));
      assert.equal(result.box, '');
    });
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
