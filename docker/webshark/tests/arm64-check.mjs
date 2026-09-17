// Manual smoke check against an arm64 box, which nothing in CI can reach. Deliberately not a
// *.test.mjs file: its assertions duplicate the suites, and they only mean anything when the
// host is arm64.
//
//   WEBSHARK_URL=http://host:8085 node arm64-check.mjs
import { closeSession, openSession, settle, shot } from './harness.mjs';

const HOST = process.env.WEBSHARK_URL;
if (!HOST) {
  console.error('set WEBSHARK_URL to the arm64 host, e.g. http://host:8085');
  process.exit(2);
}
const fails = [];
const check = (name, cond, detail = '') => {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`);
  if (!cond) fails.push(name);
};

const s = await openSession({ width: 1700, height: 1200 });
const { page } = s;

await page.goto(`${HOST}/webshark/index.html`, { waitUntil: 'networkidle2', timeout: 60000 });
check('page title present', (await page.title()).length > 0, `"${await page.title()}"`);

// The four RMW presets this image adds over stock webshark.
for (const id of ['preset_spdp', 'preset_sedp', 'preset_zenoh_declare', 'preset_retransmit']) {
  const el = await page.$(`#${id}`);
  check(`${id} rendered`, !!el, el ? await page.$eval(`#${id}`, e => `"${e.textContent.trim()}"`) : 'missing');
}
check('display_filter rendered', !!(await page.$('#display_filter')));
check('preset mode radios rendered',
  !!(await page.$('#preset_mode_list')) && !!(await page.$('#preset_mode_rate')));

// Open a capture the way a user does: click an entry in the file list.
const opened = await page.evaluate(() => {
  const link = [...document.querySelectorAll('a')].find(a => /\.pcap/i.test(a.textContent || ''));
  if (!link) return null;
  link.click();
  return link.textContent.trim();
});
check('capture opened from file list', !!opened, opened || 'no .pcap link found');
await settle(8000);

// Packet-list mode: a preset must push its filter into the filter box.
await page.click('#preset_spdp');
await settle(3000);
const spdpFilter = await page.$eval('#display_filter', e => e.value);
check('SPDP preset applies its filter', spdpFilter.includes('rtps.sm.wrEntityId'), `"${spdpFilter}"`);

await page.click('#preset_zenoh_declare');
await settle(3000);
const zenohFilter = await page.$eval('#display_filter', e => e.value);
check('Zenoh Declare preset applies its filter', zenohFilter.includes('declare_key_expr'), `"${zenohFilter}"`);

// Rate-graph mode: the preset should add a named series rather than filtering the list.
// name_graph_row puts the preset name in the first cell of #capture_graph_table and on
// graph.rmwName, not into any input value.
await page.click('#preset_mode_rate');
await page.click('#preset_retransmit');
await settle(6000);
const graph = await page.evaluate(() => {
  const table = document.getElementById('capture_graph_table');
  const graphs = (window.g_webshark_iograph && window.g_webshark_iograph.graphs) || [];
  return {
    open: document.getElementById('report_graph')?.style.display === 'block',
    rowNames: table ? [...table.rows].map(r => (r.cells[0]?.textContent || '').trim()) : [],
    rmwNames: graphs.map(g => g.rmwName).filter(Boolean),
    filters: graphs.map(g => g.filter && g.filter.value).filter(Boolean),
  };
});
check('rate-graph panel opened', graph.open);
check('Retransmits preset names a graph row',
  graph.rowNames.some(n => /retransmit/i.test(n)) || graph.rmwNames.some(n => /retransmit/i.test(n)),
  JSON.stringify({ rowNames: graph.rowNames, rmwNames: graph.rmwNames }));
check('graph row carries the preset filter',
  graph.filters.some(f => /acknack_analysis|tcp\.analysis\.retransmission/.test(f)),
  JSON.stringify(graph.filters));

await shot(page, 'arm64-ui.png');
check('no console or page errors', s.errors.length === 0, s.errors.slice(0, 3).join(' | '));

await closeSession(s);
console.log(`\n${fails.length === 0 ? 'ALL CHECKS PASSED' : 'FAILED: ' + fails.join(', ')}`);
process.exit(fails.length === 0 ? 0 : 1);
