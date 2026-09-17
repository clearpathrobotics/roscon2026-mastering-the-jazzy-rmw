// The ten packet-list columns, checked against what tshark reports for the same frames rather
// than against themselves.
import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { closeSession, openCapture, openSession, shot } from './harness.mjs';

const FILE = 'healthy-fastdds.pcap.gz';
const COLUMNS = ['No.', 'Time', 'Delta', 'Source', 'SPort', 'Destination', 'DPort',
                 'Protocol', 'Length', 'Info'];

describe('packet list columns', () => {
  let s, rows;

  before(async () => {
    s = await openSession();
    await openCapture(s.page, FILE);
    rows = await s.page.$$eval('#packet_list_frames tr',
      trs => trs.slice(0, 3).map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim())));
  });
  after(async () => {
    await shot(s.page, 'columns.png', { clip: { x: 0, y: 0, width: 1800, height: 620 } });
    await closeSession(s);
  });

  it('renders ten headers in the expected order', async () => {
    const headers = await s.page.$$eval('#packet_list_header th', ts => ts.map(t => t.textContent.trim()));
    assert.deepEqual(headers, COLUMNS);
  });

  // tshark for frames 1-3 of healthy-fastdds.pcap.gz, read from the committed fixture:
  //   1 0.000000  (no delta)  172.30.10.12 60511 172.30.10.20 13662
  //   2 0.000052  0.000052    172.30.10.12 60511 239.255.0.1  13650
  //   3 0.011241  0.011189    172.30.10.12 58546 172.30.10.20 13662
  // Microsecond, not the nanosecond of the pre-fixture capture this replaced: the recorder
  // writes -F pcap, matching scripts/workshop. Re-derive from the fixture, never from an older file.
  it('row 2 delta matches tshark', () => assert.equal(rows[1][2], '0.000052'));
  it('row 3 delta matches tshark', () => assert.equal(rows[2][2], '0.011189'));
  it('row 1 carries the source port', () => assert.equal(rows[0][4], '60511'));
  it('row 1 carries the destination port', () => assert.equal(rows[0][6], '13662'));
  it('row 2 is addressed to the discovery multicast group', () => assert.equal(rows[1][5], '239.255.0.1'));
  it('row 2 lands on the domain-25 discovery port', () => assert.equal(rows[1][6], '13650'));

  it('colours more than one row', async () => {
    const bgs = await s.page.$$eval('#packet_list_frames tr',
      trs => trs.map(tr => tr.style.backgroundColor).filter(Boolean));
    assert.ok(new Set(bgs).size > 1, `${new Set(bgs).size} distinct colours`);
  });

  it('applies the discovery blue from the shipped colour rules', async () => {
    const bgs = await s.page.$$eval('#packet_list_frames tr',
      trs => trs.map(tr => tr.style.backgroundColor).filter(Boolean));
    assert.ok(bgs.includes('rgb(218, 234, 255)'), [...new Set(bgs)].slice(0, 6).join(' '));
  });

  it('logs no console or page errors', () => assert.deepEqual(s.errors, []));
});
