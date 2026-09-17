// Hiding a column means hiding it in three places at once, since the packet list keeps a real
// header, a fake header and the body rows in step.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, openCapture, openSession, settle, shot } from './harness.mjs';

const FILE = 'healthy-fastdds.pcap.gz';
const COLUMNS = ['No.', 'Time', 'Delta', 'Source', 'SPort', 'Destination', 'DPort',
                 'Protocol', 'Length', 'Info'];

describe('column visibility', () => {
  let s;

  // Counts only cells the browser actually lays out, which is what display:none changes.
  const visible = () => s.page.evaluate(() => {
    const shown = els => [...els].filter(e => e.offsetParent !== null || e.getClientRects().length > 0).length;
    const firstRow = [...document.querySelectorAll('#packet_list_frames tr')].find(tr => tr.querySelectorAll('td').length);
    return {
      realHeader: shown(document.querySelectorAll('#packet_list_header th')),
      fakeHeader: shown(document.querySelectorAll('#packet_list_header_fake th')),
      bodyCells: firstRow ? shown(firstRow.querySelectorAll('td')) : -1,
      headerText: [...document.querySelectorAll('#packet_list_header th')]
        .filter(t => t.getClientRects().length > 0).map(t => t.textContent.trim()),
    };
  });

  before(async () => {
    s = await openSession();
    await openCapture(s.page, FILE);
  });
  after(async () => {
    await shot(s.page, 'colvis.png', { clip: { x: 0, y: 0, width: 1800, height: 700 } });
    await closeSession(s);
  });

  it('builds one checkbox per real column', async () => {
    const labels = await s.page.$$eval('#column_menu label', ls => ls.map(l => l.textContent.trim()));
    assert.deepEqual(labels, COLUMNS);
  });

  // Columns has to stay last, after Misc. index.html keeps the Guide link outside ul.menul to
  // hold this at six.
  it('puts Columns last in the menu bar, after Misc', async () => {
    const menu = await s.page.evaluate(() =>
      [...document.querySelectorAll('ul.menul > li > a')].map(a => a.childNodes[0].textContent.trim()));
    assert.equal(menu.length, 6, JSON.stringify(menu));
    assert.deepEqual(menu.slice(4), ['Misc', 'Columns']);
  });

  it('starts with all ten visible in both headers and the body', async () => {
    const v = await visible();
    assert.deepEqual([v.realHeader, v.fakeHeader, v.bodyCells], [10, 10, 10]);
  });

  it('hides SPort and DPort everywhere at once', async () => {
    await s.page.evaluate(() => {
      const boxes = document.querySelectorAll('#column_menu input');
      boxes[4].click();   // SPort
      boxes[6].click();   // DPort
    });
    const v = await visible();
    assert.deepEqual([v.realHeader, v.fakeHeader, v.bodyCells], [8, 8, 8]);
    assert.deepEqual(v.headerText,
      ['No.', 'Time', 'Delta', 'Source', 'Destination', 'Protocol', 'Length', 'Info']);
  });

  // class="packet_list" is also on #capture_graph_table's table, so an unscoped rule hits it.
  it('leaves the Advanced Graph table at full width', async () => {
    await s.page.evaluate(() => { document.getElementById('capture_interval_adv').click(); });
    await s.page.waitForFunction(
      () => document.getElementById('report_graph').style.display === 'block', { timeout: 10000 });
    const graph = await s.page.evaluate(() => {
      const tbody = document.getElementById('capture_graph_table');
      const tr = tbody.querySelector('tr');
      return {
        heads: [...tbody.closest('table').querySelectorAll('thead th')]
          .filter(th => th.getClientRects().length > 0).length,
        cells: tr ? [...tr.querySelectorAll('td')].filter(td => td.getClientRects().length > 0).length : -1,
      };
    });
    assert.deepEqual(graph, { heads: 7, cells: 7 });
  });

  it('survives Clusterize rebuilding rows on scroll', async () => {
    await s.page.evaluate(() => { document.getElementById('ws_packet_list_view_scroll').scrollTop = 40000; });
    await settle(1200);
    assert.equal((await visible()).bodyCells, 8);
  });

  it('survives a reload, menu state included', async () => {
    await openCapture(s.page, FILE);
    const v = await visible();
    assert.deepEqual([v.realHeader, v.bodyCells], [8, 8]);
    const checked = await s.page.$$eval('#column_menu input', bs => bs.map(b => b.checked));
    assert.deepEqual(checked, [true, true, true, true, false, true, false, true, true, true]);
  });

  it('refuses to hide the last column standing', async () => {
    const guard = await s.page.evaluate(() => {
      const boxes = [...document.querySelectorAll('#column_menu input')];
      boxes.forEach(b => { if (b.checked) b.click(); });
      return {
        stillChecked: boxes.filter(b => b.checked).length,
        visibleTh: [...document.querySelectorAll('#packet_list_header th')]
          .filter(t => t.getClientRects().length > 0).length,
      };
    });
    assert.deepEqual(guard, { stillChecked: 1, visibleTh: 1 });
  });

  it('restores every column when they are ticked back on', async () => {
    await s.page.evaluate(() => {
      document.querySelectorAll('#column_menu input').forEach(b => { if (!b.checked) b.click(); });
    });
    const v = await visible();
    assert.deepEqual([v.realHeader, v.fakeHeader, v.bodyCells], [10, 10, 10]);
  });

  // Runs last of the mutating cases, because it needs all ten columns back to measure against.
  it('widens Info when Delta, SPort and DPort are hidden', async () => {
    const infoWidthBefore = await s.page.evaluate(() => {
      const th = [...document.querySelectorAll('#packet_list_header th')];
      return th[th.length - 1].getBoundingClientRect().width;
    });
    await s.page.evaluate(() => {
      for (const fmt of ['Delta', 'SPort', 'DPort']) {
        const lab = [...document.querySelectorAll('#column_menu label')].find(l => l.textContent.trim() === fmt);
        const inp = lab && lab.querySelector('input');
        if (inp && inp.checked) inp.click();
      }
    });
    await settle(800);
    const after_ = await s.page.evaluate(() => {
      const vis = [...document.querySelectorAll('#packet_list_header th')]
        .filter(t => getComputedStyle(t).display !== 'none');
      return { visible: vis.length, infoWidth: vis[vis.length - 1].getBoundingClientRect().width };
    });
    assert.equal(after_.visible, 7);
    assert.ok(after_.infoWidth > infoWidthBefore,
      `${Math.round(infoWidthBefore)} -> ${Math.round(after_.infoWidth)}`);
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
