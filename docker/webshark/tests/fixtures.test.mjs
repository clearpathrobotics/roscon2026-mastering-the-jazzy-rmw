// Every committed fixture has to open in the viewer and show the thing it is named for. A
// fixture that only satisfies tshark is not take-home material.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, openCapture, openSession, settle } from './harness.mjs';

// fixture -> [filter to apply, substring every surviving row should carry]
const CASES = {
  'qos-mismatch': ['rtps.param.topicName contains "fixture_qos"', 'fixture_qos'],
  'domain-mismatch': ['udp.dstport == 17900 || udp.dstport == 26650', 'RTPS'],
  'multicast-storm': ['ip.dst == 239.255.0.1', '239.255.0.1'],
  'nothing-on-wire': ['rtps', 'RTPS'],
  'multicast-blocked': ['ip.dst == 239.255.0.1', '239.255.0.1'],
  'node-death': ['rtps.sm.wrEntityId == 0x000100c2', 'RTPS'],
  'fragment-loss': ['rtps.sm.id == 0x16', 'DATA_FRAG'],
  'reliable-vs-besteffort': ['rtps.param.topicName contains "fixture_img"', 'fixture_img'],
  'zenoh-no-router': ['tcp.flags.syn == 1 && tcp.flags.ack == 0', 'TCP'],
  'zenoh-router-killed': ['zenoh.body.close.reason', 'Zenoh'],
};

describe('shipped fixtures', () => {
  let s;

  before(async () => { s = await openSession({ width: 1600, height: 1200 }); });
  after(async () => { await closeSession(s); });

  for (const [name, [filter, expected]] of Object.entries(CASES)) {
    describe(name, () => {
      let badge, rows;

      before(async () => {
        await openCapture(s.page, `${name}.pcap.gz`, {}, 5);
        // The badge names the middleware. It is the one thing a cold user reads first, so a
        // fixture whose badge stays empty looks broken before they have clicked anything.
        await s.page.waitForFunction(
          () => (document.getElementById('toolbar_capture_summary')?.innerText || '').trim().length > 0,
          { timeout: 60000 }).catch(() => {});
        badge = await s.page.evaluate(
          () => (document.getElementById('toolbar_capture_summary')?.innerText || '').trim());
        await s.page.evaluate(f => preset_filter(f), filter);
        await settle(5000);
        rows = await s.page.evaluate(() => [...document.querySelectorAll('#packet_list_frames tr')]
          .map(t => t.innerText.trim()).filter(Boolean));
      });

      it('names its middleware in the badge', () => assert.ok(badge.length > 0, 'badge is empty'));
      it('returns rows for its own filter', () => assert.ok(rows.length > 0, '0 rows'));
      it(`shows ${expected} in the rows that come back`, () => {
        const hits = rows.filter(r => r.includes(expected)).length;
        assert.ok(hits / rows.length > 0.5, `${hits}/${rows.length} rows carry ${JSON.stringify(expected)}`);
      });
    });
  }

  it('logs no page errors across every fixture', () => assert.deepEqual(s.errors, []));
});
