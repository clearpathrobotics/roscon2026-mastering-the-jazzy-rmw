// Regenerates guide.html's screenshots from the running container, so they can be retaken
// whenever the UI changes rather than reverse-engineered from the images.
//
//   docker compose -f webshark.yml up -d webshark
//   npm i puppeteer-core
//   node guide-screenshots.mjs ./guide-assets
//
// Needs chromium on the host; this was written against /usr/bin/chromium. It prints the
// legend contents, y2 tick count and filter border it observed, so a run that silently
// captured the wrong state is visible in the output rather than only in the images.
import puppeteer from 'puppeteer-core';
import fs from 'fs';

const BASE = 'http://localhost:8085/webshark/index.html';
const CYCLONE = 'sedp_cyclone_bounce_20260819223138.pcap';
const OUT = process.argv[2];
fs.mkdirSync(OUT, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: '/usr/bin/chromium', headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1700,1400'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1700, height: 1400, deviceScaleFactor: 2 });
const errs = [];
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
page.on('pageerror', e => errs.push('pageerror: ' + e.message));

const shot = async (sel, name) => {
  const el = await page.$(sel);
  if (!el) { console.log(`  MISS  ${name}  (${sel})`); return false; }
  const box = await el.boundingBox();
  if (!box || box.width < 5 || box.height < 5) { console.log(`  EMPTY ${name}  ${JSON.stringify(box)}`); return false; }
  await el.screenshot({ path: `${OUT}/${name}.png` });
  console.log(`  ok    ${name}.png  ${Math.round(box.width)}x${Math.round(box.height)}`);
  return true;
};
// Wrap a set of live elements in a temp container so the shot is cropped to them
// rather than to whatever wide toolbar row happens to contain them.
const group = (sels, id) => page.evaluate((sels, id) => {
  const els = sels.map(s => document.querySelector(s)).filter(Boolean);
  if (!els.length) return false;
  const wrap = document.createElement('div');
  wrap.id = id;
  wrap.style.cssText = 'display:inline-block;padding:8px;background:#fff;';
  els[0].parentNode.insertBefore(wrap, els[0]);
  els.forEach(e => wrap.appendChild(e));
  return true;
}, sels, id);
const wait = ms => new Promise(r => setTimeout(r, ms));

// ---- file list ----
await page.goto('http://localhost:8085/webshark/', { waitUntil: 'networkidle2', timeout: 90000 });
await page.waitForSelector('#capture_files tr', { timeout: 60000 });
await shot('#capture_files_view', 'filelist');

// ---- open a capture ----
await page.goto(`${BASE}?file=${CYCLONE}`, { waitUntil: 'networkidle2', timeout: 120000 });
await page.waitForFunction(
  () => document.getElementById('toolbar_capture_description')?.textContent.trim().length > 0,
  { timeout: 120000 });
await page.waitForFunction(
  () => document.getElementById('toolbar_capture_summary')?.textContent.trim().length > 0,
  { timeout: 120000 });
await wait(1500);
console.log('  badge text:', JSON.stringify(await page.evaluate(() =>
  document.getElementById('toolbar_capture_summary').textContent.trim())));

// ---- three panes, before any DOM surgery ----
await page.waitForSelector('#packet_list_frames tr', { timeout: 90000 });
await page.evaluate(() => document.querySelector('#packet_list_frames tr')?.click());
await wait(3000);
const detailLen = await page.evaluate(() => document.getElementById('ws_packet_detail_view').textContent.trim().length);
const bytesLen = await page.evaluate(() => document.getElementById('ws_bytes_dump').textContent.trim().length);
console.log(`  detail pane chars=${detailLen}  bytes pane chars=${bytesLen}`);
const clip = await page.evaluate(() => {
  const ids = ['ws_packet_list_view', 'ws_packet_detail_view', 'ws_packet_bytes_view'];
  const rs = ids.map(i => document.getElementById(i).getBoundingClientRect());
  const x = Math.min(...rs.map(r => r.left)), y = Math.min(...rs.map(r => r.top));
  return { x: x - 4, y: y + window.scrollY - 4,
           width: Math.max(...rs.map(r => r.right)) - x + 8,
           height: Math.max(...rs.map(r => r.bottom)) - y + 8 };
});
await page.screenshot({ path: `${OUT}/panes.png`, clip, captureBeyondViewport: true });
console.log(`  ok    panes.png  ${Math.round(clip.width)}x${Math.round(clip.height)}`);

// ---- badge ----
if (await group(['#toolbar_capture_description', '#toolbar_capture_summary'], 'shot_badge'))
  await shot('#shot_badge', 'badge');

// ---- graph: two presets overlaid, second on Y2 ----
await page.evaluate(() => document.getElementById('preset_mode_rate').click());
await page.evaluate(() => document.getElementById('preset_spdp').click());
await wait(4500);
await page.evaluate(() => document.getElementById('preset_retransmit').click());
await wait(4500);
await page.evaluate(() => {
  const rows = document.querySelectorAll('#capture_graph_table tr');
  const last = rows[rows.length - 1];
  const sel = last?.cells[last.cells.length - 1]?.querySelector('select');
  if (sel) sel.value = 'y2';
  render_graph();
});
await wait(5000);
console.log('  legend:', JSON.stringify(await page.evaluate(() =>
  [...document.querySelectorAll('#capture_graph .c3-legend-item text')].map(t => t.textContent))));
console.log('  y2 ticks:', await page.evaluate(() =>
  document.querySelectorAll('#capture_graph .c3-axis-y2 .tick').length));
await shot('#report_graph', 'graph');

// ---- preset row ----
await page.evaluate(() => {
  const rows = [...document.querySelectorAll('#toolbar_capture > div[style*="float: left"] > div')];
  const hit = rows.filter(d => /RMW presets|Discovery|Repair/.test(d.textContent));
  if (!hit.length) return;
  const wrap = document.createElement('div');
  wrap.id = 'shot_presets';
  wrap.style.cssText = 'display:inline-block;padding:8px;background:#fff;';
  hit[0].parentNode.insertBefore(wrap, hit[0]);
  hit.forEach(d => wrap.appendChild(d));
});
await shot('#shot_presets', 'presets');

// ---- filter error ----
await page.evaluate(() => { const f = document.getElementById('display_filter'); f.value = 'rtps.sm.nosuchfield == 1'; set_filter(f.value); });
await wait(4000);
console.log('  filter border:', await page.evaluate(() =>
  getComputedStyle(document.getElementById('display_filter')).border));
if (await group(['#display_filter'], 'shot_filter')) await shot('#shot_filter', 'filtererror');

console.log('\nconsole errors:', errs.length ? errs.slice(0, 5) : 'none');
await browser.close();
