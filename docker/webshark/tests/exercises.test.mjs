// Every count guide section 8's fixture exercises tell a reader to expect, re-derived against
// the running viewer. A re-recorded fixture that shifts a number fails here rather than in
// front of a room. Exercise 7 drives the Reassembly button in the page as well, since its
// claim is that the file does not change and the dissection does.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, countFrames, openCapture, openSession, settle } from './harness.mjs';

const PORTS = 'udp.dstport == 17900 || udp.dstport == 26650';
const TOPIC = 'rtps.param.topicName == "rt/fixture_qos"';
const DEAD = 'tcp.port == 7999';
const FRAG = 'fragment-loss.pcap.gz';

// Two frames in qos-mismatch bundle several endpoints into one announcement and so carry both
// reliability values at once. Excluding the reader entity id leaves the standalone writer
// announcement the exercise tells a reader to find.
const BE_WRITER = `${TOPIC} && rtps.reliability_kind == 0x00000001`
  + ' && rtps.sm.wrEntityId == 0x000003c2 && !(rtps.sm.wrEntityId == 0x000004c2)'
  + ' && ip.src == 172.30.10.11';

const counts = (capture, cases) => {
  for (const [name, filter, want] of cases)
    it(name, async () => assert.equal(await countFrames(capture, filter), want));
};

describe('exercise 6: two captures, the same complaint, two different causes', () => {
  describe('domain-mismatch.pcap.gz', () => counts('domain-mismatch.pcap.gz', [
    ['60 frames on the two domain ports', PORTS, 60],
    ['no ACKNACK once scoped to those ports', `(${PORTS}) && rtps.sm.id == 0x06`, 0],
    ['993 ACKNACK file-wide, the answer the exercise warns about', 'rtps.sm.id == 0x06', 993],
  ]));

  describe('qos-mismatch.pcap.gz', () => counts('qos-mismatch.pcap.gz', [
    ['33 announcements of rt/fixture_qos', TOPIC, 33],
    ['one best-effort writer announcement from 172.30.10.11', BE_WRITER, 1],
    ['thirty reliable reader announcements from 172.30.10.20',
      `${TOPIC} && rtps.sm.wrEntityId == 0x000004c2 && ip.src == 172.30.10.20`, 30],
  ]));
});

describe('exercise 8: the filter that answers a question you did not ask', () => {
  counts('zenoh-no-router.pcap.gz', [
    ['15581 Zenoh frames file-wide', 'zenoh', 15581],
    ['15 frames on the dead port', DEAD, 15],
    ['8 connection attempts', `${DEAD} && tcp.flags.syn == 1 && tcp.flags.ack == 0`, 8],
    ['7 refusals', `${DEAD} && tcp.flags.reset == 1`, 7],
    ['no Zenoh at all on the dead port', `${DEAD} && zenoh`, 0],
  ]);
});

describe('exercise 7: change what the dissector will tell you', () => {
  counts(FRAG, [
    ['1505 DATA_FRAG frames', 'rtps.sm.id == 0x16', 1505],
    ['10944 IP fragments that never complete',
      '(ip.flags.mf == 1 || ip.frag_offset > 0) && !ip.reassembled.length', 10944],
    ['12501 frames in the file', 'frame', 12501],
  ]);

  describe('the Reassembly toggle', () => {
    let s, off, on;

    // The toggle sets a preference on the sharkd session, which outlives this browser, so
    // clear it on the way in and again on the way out. dissect.test.mjs asserts it starts off,
    // and a suite that leaves it on fails a suite that runs after it.
    const setReassembly = async want => {
      const now = await s.page.evaluate(() => g_dissect_on.indexOf('reassembly') !== -1);
      if (now !== want) {
        await s.page.evaluate(() => toggle_dissect('reassembly'));
        await settle(6000);
      }
    };
    // Info is the tenth column in this build. See the columns literal in index.html.
    const infoRows = () => s.page.evaluate(() => [...document.querySelectorAll('#packet_list_frames tr')]
      .map(tr => tr.querySelectorAll('td')[9]?.textContent || '')
      .filter(t => t.includes('DATA_FRAG')).slice(0, 5));

    before(async () => {
      s = await openSession();
      await openCapture(s.page, FRAG);
      await setReassembly(false);
      await s.page.evaluate(() => preset_filter('rtps.sm.id == 0x16'));
      await settle(4000);
      off = await infoRows();
    });
    after(async () => {
      await setReassembly(false);
      await closeSession(s);
    });

    it('starts off', async () => assert.equal(
      await s.page.evaluate(() => g_dissect_on.indexOf('reassembly')), -1));

    it('leaves the Info column reading plain DATA_FRAG', () => {
      assert.ok(off.length > 0, 'no DATA_FRAG rows rendered');
      assert.ok(off.every(t => !t.includes('[RTPS fragment]')), JSON.stringify(off[0]));
    });

    it('turns on when clicked', async () => {
      await setReassembly(true);
      on = await infoRows();
      assert.notEqual(await s.page.evaluate(() => g_dissect_on.indexOf('reassembly')), -1);
    });

    it('adds [RTPS fragment] to the Info column', () => {
      assert.ok(on.length > 0, 'no DATA_FRAG rows rendered');
      assert.ok(on.every(t => t.includes('[RTPS fragment]')), JSON.stringify(on[0]));
    });

    it('changed the reading and not the file', () => {
      assert.equal(on.length, off.length);
      assert.deepEqual(on.map(t => t.replace(' [RTPS fragment]', '')), off);
    });

    it('goes back off for whichever suite runs next', async () => {
      await setReassembly(false);
      assert.equal(await s.page.evaluate(() => g_dissect_on.indexOf('reassembly')), -1);
    });

    it('logs no page errors', () => assert.deepEqual(s.errors, []));
  });
});
