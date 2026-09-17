// A dangling table-of-contents anchor is invisible until someone clicks it on stage, so the
// guide's own links are checked against its own headings here.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { HOST, closeSession, openCapture, openSession, shot } from './harness.mjs';

describe('guide', () => {
  let s, text;

  before(async () => {
    s = await openSession({ width: 1400, height: 1200 });
    await s.page.goto(`${HOST}/webshark/guide.html`, { waitUntil: 'networkidle2', timeout: 60000 });
    text = await s.page.evaluate(() => document.body.innerText);
  });
  after(async () => {
    await shot(s.page, 'guide.png');
    await closeSession(s);
  });

  it('resolves every table-of-contents anchor', async () => {
    const dangling = await s.page.evaluate(() =>
      [...document.querySelectorAll('#toc a')]
        .map(a => a.getAttribute('href'))
        .filter(h => h && h.startsWith('#') && !document.getElementById(h.slice(1))));
    assert.deepEqual(dangling, []);
  });

  it('carries the glossary and links to it from the contents', async () => {
    assert.ok(await s.page.$('#glossary'), 'no #glossary heading');
    assert.ok(await s.page.$('#toc a[href="#glossary"]'), 'no glossary entry in the contents');
  });

  for (const [name, needle] of [
    ['the Zenoh join symptom (5.10)', 'A Zenoh node never joins the network'],
    ['the slow-capture symptom (5.11)', 'The capture is slow to open'],
    ['the failed-capture-tool symptom (5.12)', 'The capture tool itself failed'],
    ['the tshark equivalents of the presets', 'The presets as tshark commands'],
    ['the Zenoh field reference', 'zenoh.body.init_ack.zid'],
    ['the Y axis labels row in Appendix A', 'Y axis labels'],
    ['the colouring rules row in Appendix A', 'ROS 2 colouring rules'],
    // Both are silent failures on a real robot: a bridged container records the wrong network,
    // and a TTY-less exec leaves tshark running after Ctrl-C with no pkill in the image.
    ['the on-robot capture path', 'When Webshark runs on the robot itself'],
    ['why the capture container needs host networking', 'network_mode: host'],
    ['that the capture exec needs a TTY to be stoppable', 'is not optional'],
  ]) it(`documents ${name}`, () => assert.ok(text.includes(needle), `missing: ${needle}`));

  it('claims both architectures the image builds for', () => {
    assert.ok(text.includes('amd64 and arm64 Linux'));
    assert.ok(!text.includes('x86_64 Linux'), 'still claims x86_64 only');
  });

  it('defines a substantial term list in the glossary', async () => {
    const rows = await s.page.evaluate(() => {
      const h = document.getElementById('glossary');
      let n = h.nextElementSibling, c = 0;
      while (n && n.tagName !== 'FOOTER') { c += n.querySelectorAll('table tr').length; n = n.nextElementSibling; }
      return c;
    });
    assert.ok(rows > 50, `${rows} rows including headers`);
  });

  it('fits the viewport without horizontal overflow', async () => {
    const overflows = await s.page.evaluate(() =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth);
    assert.equal(overflows, false);
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});

// The two places the viewer points at the guide. Discoverability is the whole point of them, so
// these assert on prominence rather than on the link resolving.
describe('the viewer points at the guide', () => {
  let s;

  before(async () => { s = await openSession({ width: 1400, height: 1000 }); });
  after(async () => { await closeSession(s); });

  describe('the toolbar button, once a capture is open', () => {
    let button;
    before(async () => {
      await openCapture(s.page, 'healthy-fastdds.pcap.gz');
      button = await s.page.evaluate(() => {
        const a = document.getElementById('toolbar_guide');
        if (!a) return null;
        const cs = getComputedStyle(a);
        const bar = getComputedStyle(document.getElementById('user_toolbar'));
        return {
          href: a.getAttribute('href'), target: a.getAttribute('target'),
          text: a.textContent.trim(), title: a.title,
          background: cs.backgroundColor, barBackground: bar.backgroundColor,
          underlined: cs.textDecorationLine !== 'none',
          visible: a.getClientRects().length > 0,
          left: a.getBoundingClientRect().left,
          barWidth: document.getElementById('user_toolbar').getBoundingClientRect().width,
        };
      });
    });

    it('exists and is rendered', () => assert.ok(button && button.visible, JSON.stringify(button)));
    it('opens the guide in its own tab', () =>
      assert.deepEqual([button.href, button.target], ['guide.html', '_blank']));
    it('carries a filled background rather than being another toolbar link', () => {
      assert.notEqual(button.background, button.barBackground);
      assert.notEqual(button.background, 'rgba(0, 0, 0, 0)');
    });
    it('is a button and not underlined text', () => assert.equal(button.underlined, false));
    it('sits in the left third of the toolbar, early in reading order', () =>
      assert.ok(button.left < button.barWidth / 3, `${button.left} of ${button.barWidth}`));
    it('keeps its explanatory tooltip', () => assert.match(button.title, /Field guide/));
  });

  describe('the file list, before anything is open', () => {
    let hint;
    before(async () => {
      await s.page.goto(`${HOST}/webshark/index.html`, { waitUntil: 'networkidle2', timeout: 60000 });
      await s.page.waitForFunction(
        () => document.getElementById('files_view').style.display !== 'none', { timeout: 30000 });
      hint = await s.page.evaluate(() => {
        const p = document.getElementById('files_guide_hint');
        const a = p && p.querySelector('a');
        return p && {
          visible: p.getClientRects().length > 0,
          text: p.textContent.replace(/\s+/g, ' ').trim(),
          href: a && a.getAttribute('href'),
          aboveTheFilter: p.getBoundingClientRect().top
            < document.getElementById('files_filter').getBoundingClientRect().top,
        };
      });
    });

    it('shows a pointer to the guide', () => assert.ok(hint && hint.visible, JSON.stringify(hint)));
    it('puts it above the file filter, where the eye lands first', () =>
      assert.equal(hint.aboveTheFilter, true));
    it('links to the guide', () => assert.equal(hint.href, 'guide.html'));
    // Wireshark is not what is on screen, and webshark is not a name anyone arrives knowing.
    it('names neither Wireshark nor webshark in the prompt', () => {
      assert.ok(!/wireshark/i.test(hint.text), hint.text);
      assert.ok(!/webshark/i.test(hint.text), hint.text);
    });
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
