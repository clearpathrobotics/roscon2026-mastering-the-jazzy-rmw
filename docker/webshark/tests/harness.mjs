// What every suite needs before it can assert anything.
import { existsSync, rmSync, writeFileSync } from 'node:fs';
import puppeteer from 'puppeteer-core';

export const HOST = process.env.WEBSHARK_URL || 'http://localhost:8085';

// puppeteer-core ships no browser of its own. /usr/bin/chromium is the development box;
// google-chrome is what the GitHub runner image provides.
const BROWSERS = [
  process.env.CHROME_PATH,
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
].filter(Boolean);

export function browserPath() {
  const found = BROWSERS.find(p => existsSync(p));
  if (!found)
    throw new Error(`no browser executable found. Looked at: ${BROWSERS.join(', ')}. `
      + 'Install chromium or set CHROME_PATH.');
  return found;
}

export const launchBrowser = () => puppeteer.launch({
  executablePath: browserPath(), headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1800,1200'],
});

// global-setup.mjs launches one browser and publishes its endpoint, so a full run shares a
// single instance across the fourteen files. Running one file on its own finds no endpoint and
// launches its own, which is what keeps `node --test dissect.test.mjs` working.
//
// Each file gets its own browser context, because the page keeps hidden columns and saved graph
// rows in localStorage, which one shared context would leak from file to file.
export async function openSession({ width = 1800, height = 1200 } = {}) {
  const endpoint = process.env.WEBSHARK_BROWSER_WS;
  const browser = endpoint
    ? await puppeteer.connect({ browserWSEndpoint: endpoint })
    : await launchBrowser();
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width, height });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  return { browser, context, page, errors, shared: !!endpoint };
}

export async function closeSession(s) {
  if (!s) return;
  await s.context.close().catch(() => {});
  if (s.shared) await s.browser.disconnect();
  else await s.browser.close().catch(() => {});
}

export const settle = ms => new Promise(r => setTimeout(r, ms));

export const sharkd = async params => {
  const r = await fetch(`${HOST}/webshark/json?${new URLSearchParams(params)}`);
  return r.json();
};

// req=intervals carries a frames total for the filter and answers 0 as 0. req=frames cannot:
// it rejects skip=0 outright, so an empty result and a single match look the same. Counting
// rendered rows is not an option either, because the packet list is virtualised.
export const countFrames = async (capture, filter) => {
  const j = await sharkd({ req: 'intervals', capture, filter });
  if (typeof j.frames !== 'number') throw new Error(`${filter}: ${JSON.stringify(j)}`);
  return j.frames;
};

// The directory the viewer serves, for the one suite that has to create and delete a capture
// while the page is open. CI bind-mounts docker/webshark/captures; the lab2 overlay points the
// same container at lab2-on-the-wire/captures instead. Both usually exist and hold the same
// fixtures, so presence proves nothing: write a probe file into each and let sharkd say which
// one it can actually see. A name it cannot find is the one case that answers err.
export async function capturesDir() {
  const candidates = [
    process.env.WEBSHARK_CAPTURES,
    new URL('../captures/', import.meta.url).pathname,
    new URL('../../../lab2-on-the-wire/captures/', import.meta.url).pathname,
  ].filter(Boolean);

  for (const [i, dir] of candidates.entries()) {
    if (!existsSync(dir)) continue;
    const probe = `harness-probe-${process.pid}-${i}.pcap`;
    writeFileSync(`${dir}/${probe}`, Buffer.alloc(64));
    const seen = !(await sharkd({ req: 'status', capture: probe })).err;
    rmSync(`${dir}/${probe}`, { force: true });
    if (seen) return dir;
  }
  throw new Error(`no captures directory reaches the viewer. Tried: ${candidates.join(', ')}. `
    + 'Set WEBSHARK_CAPTURES to the directory mounted at /captures.');
}

export const captureUrl = (file, params = {}) => {
  const q = new URLSearchParams({ file, ...params });
  return `${HOST}/webshark/index.html?${q}`;
};

// minCells is how many rendered cells count as loaded. 20 suits the fixtures that fill a
// screen; the small ones need a lower bar.
export async function openCapture(page, file, params = {}, minCells = 20) {
  await page.goto(captureUrl(file, params), { waitUntil: 'networkidle2', timeout: 90000 });
  await page.waitForFunction(
    n => document.querySelectorAll('#packet_list_frames tr td').length > n,
    { timeout: 60000 }, minCells);
}

export const shot = (page, name, opts = {}) =>
  page.screenshot({ path: new URL(`./${name}`, import.meta.url).pathname, ...opts });

// Subtrees render collapsed and a collapsed field's glyph has a zero-size rect, so nothing is
// clickable until the protocol nodes are open. Expand off each node's own expanded flag rather
// than clicking every expander: webshark_tree_on_click toggles, and it remembers state in
// sessionStorage, so a blind pass closes a tree that a previous row already opened.
export async function selectRow(page, n) {
  await page.evaluate(i => document.querySelectorAll('#packet_list_frames tr')[i].click(), n);
  await page.waitForFunction(
    () => document.querySelectorAll('#ws_packet_detail_view a[href]').length > 5, { timeout: 20000 });
  await page.evaluate(() => {
    for (var pass = 0; pass < 5; pass++)
      [...document.querySelectorAll('#ws_packet_detail_view li')].forEach(li => {
        const exp = li.querySelector(':scope > .tree_expander');
        if (exp && li.data_ws_subtree && !li.data_ws_subtree.expanded
            && exp.getBoundingClientRect().width > 0)
          exp.click();
      });
  });
  await settle(600);
}

// The glyph is a 12px <img> inside an <a> floated right in the tree. Returns the img handle
// and the filter its anchor carries.
export async function fieldGlyph(page, match) {
  for (const h of await page.$$('#ws_packet_detail_view a[href] img')) {
    const f = await h.evaluate(i => new URL(i.parentNode.href).searchParams.get('filter'));
    if (f && match(f)) return [h, f];
  }
  return [null, null];
}

// The <a> itself has no clickable box, so drive the img, and scroll it in first: the tree pane
// is only 350px tall.
export async function clickElement(page, handle, { ctrl = false } = {}) {
  await handle.evaluate(el => el.scrollIntoView({ block: 'center' }));
  const box = await handle.boundingBox();
  if (!box) throw new Error('element has no box');
  if (ctrl) await page.keyboard.down('Control');
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  if (ctrl) await page.keyboard.up('Control');
}
