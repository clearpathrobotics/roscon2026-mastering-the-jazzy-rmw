#!/usr/bin/env python3
"""Exercise the real sweep entrypoint with an isolated Docker/Compose boundary."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json,os,pathlib,sys,time
p=pathlib.Path(os.environ['FIXTURE_STATE']); state=json.loads(p.read_text())
a=sys.argv[1:]; mode=os.environ.get('FIXTURE_MODE','')
with open(os.environ['FIXTURE_LOG'],'a') as f: f.write(json.dumps(a)+'\n')
def save(): p.write_text(json.dumps(state))
def out(v): print(v if isinstance(v,str) else json.dumps(v))
if a[0]=='ps':
    if '--filter' in a:
        name=a[a.index('--filter')+1].split('=',1)[1].strip('^$/')
        out('\n'.join(i for i,c in state['containers'].items() if c['name']==name))
    else: out('\n'.join(state['containers']))
elif a[0]=='inspect':
    c=state['containers'].get(a[-1])
    if c is None: sys.exit(1)
    if '--format' in a and 'NetworkSettings' in a[a.index('--format')+1]:
        suffix=int(c['name'].rsplit('-',1)[-1])+10 if c['service']=='fleet' else 2
        out('172.30.0.'+str(suffix)+'|sha256:fixture')
    elif '--format' in a and 'State.Running' in a[a.index('--format')+1]:
        out('true')
    else: out('/'+c['name'] if '--format' in a else c)
elif a[0]=='rm':
    if mode=='cleanup_fail': sys.exit(1)
    for i in a[2:]: state['containers'].pop(i,None)
    save()
elif a[0]=='stats': out('1.0%')
elif a[0]=='compose':
    if 'ps' in a:
        if mode=='enumeration_fail' and state.get('started'): sys.exit(1)
        out('\n'.join(i for i,c in state['containers'].items() if c['service']==a[-1]))
    elif 'up' in a:
        services=[x for x in a if x in ('ros2-cyclone','ros2-cyclone-b','ros2-fastdds','ros2-fastdds-b','fleet','zenoh-router','lab4-receiver')]
        for service in services:
            scale_arg=next((x for x in a if x.startswith('fleet=')), 'fleet=1')
            count=int(scale_arg.split('=',1)[1]) if service=='fleet' else 1
            if mode=='wrong_scale': count=1
            for n in range(count):
                i='owned-'+service+'-'+str(n)
                state['containers'][i]={'name':service+'-'+str(n) if service=='fleet' else service,'service':service,'profile':'none','rate':''}
                state['started']=True; save()
                if mode=='startup_fail' and 'cyclone' in service:
                    print('injected partial startup failure',file=sys.stderr); sys.exit(7)
    else: sys.exit(0)
elif a[0]=='cp':
    if ':' in a[-1]:
        pass
    else:
        pathlib.Path(a[-1]).write_text(json.dumps({'sensor_drop_pct':1,'control_p99_ms':2,'state_freshness_ms':3,'throughput_mbps':4}))
elif a[0]=='exec':
    command=' '.join(a)
    if 'class_probe.py' in command:
        state['probe_done']=True; save()
        if mode in ('signal','probe_timeout'):
            pathlib.Path(os.environ['FIXTURE_MARKER']).write_text(str(os.getpid()))
            if mode=='probe_timeout': sys.exit(124)
            time.sleep(30)
        if mode=='probe_fail': print('probe failed',file=sys.stderr); sys.exit(9)
        if mode=='malformed': out('not json'); sys.exit(0)
        values={k:v for k,v in zip(('sensor_drop_pct','control_p99_ms','state_freshness_ms','throughput_mbps'),(1,2,3,4))}
        if mode=='missing_metric': values['control_p99_ms']=None
        if mode=='nonfinite': values['control_p99_ms']=float('nan')
        out(values)
    elif 'service_bench.py' in command: out('1 2 3 4')
    elif 'comparison.py' in command or 'pugh.py' in command or 'plot_comparison.py' in command:
        if mode=='report_fail': sys.exit(4)
    elif 'tc -j' in command or 'ip -j' in command:
        if mode=='state_unavailable': sys.exit(1)
        target=state['containers'].get(a[1],{})
        profile=target.get('profile','none'); impaired=profile!='none'
        bad_ingress=mode=='partial_ingress' or (mode=='post_mismatch' and state.get('probe_done'))
        eth={'ifname':'eth0','flags':['UP']}; ifb={'ifname':'ifb0','flags':['UP']}
        delay,jitter,loss={'heavy':(.030,.010,.05),'healthy':(.005,.001,.002),'constrained':(.05,.015,.01)}.get(profile,(0,0,0))
        rate=float(target.get('rate','0').removesuffix('mbit') or 0)*1e6/8
        if mode=='rate_mismatch': rate=1
        options={'delay':{'delay':delay,'jitter':jitter},'loss-gemodel':{'p':loss,'r':1-loss,'1-h':1,'1-k':0}}
        if rate: options['rate']={'rate':rate}
        q={'kind':'netem','root':True,'options':options} if impaired else {'kind':'noqueue','root':True}
        if 'ip -j' in command: out([eth,ifb] if impaired and not bad_ingress else [eth])
        elif 'filter' in command: out([{'kind':'u32','options':{'actions':[{'kind':'mirred','direction':'egress','mirred_action':'redirect','to_dev':'ifb0'}]}}] if impaired and not bad_ingress else [])
        elif 'dev eth0' in command: out([q])
        else: out([dict(q,dev='eth0'),dict(q,dev='ifb0')] if impaired and not bad_ingress else [dict(q,dev='eth0')])
'''
NETEM = r'''#!/usr/bin/env bash
python3 - "$1" "$2" <<'INNER'
import json,os,sys
p=os.environ['FIXTURE_STATE']; d=json.load(open(p)); target=d['containers'][sys.argv[2]]; target['profile']='none' if sys.argv[1]=='clear' else sys.argv[1]; target['rate']=os.environ.get('LINK_RATE',''); json.dump(d,open(p,'w'))
print('fixture shaping target '+sys.argv[2])
INNER
'''
PUBSUB = '''#!/usr/bin/env bash
if [[ "${FIXTURE_MODE:-}" == pubsub_fail ]]; then echo 'pubsub failure' >&2; exit 8; fi
sleep 0.2
echo '1 2 1000'
'''


class RunnerFixtureTests(unittest.TestCase):
    def run_case(self, mode='', template='B', scenario='S0', rmws='cyclone,fastdds', sig=None, extra=()):
        with tempfile.TemporaryDirectory() as td:
            tmp=Path(td)
            containers={'core':{'name':'ubuntu-headless','service':'ubuntu-headless'},'unrelated':{'name':'other-fleet-1','service':'external'}}
            if mode=='conflict': containers['stopped']={'name':'foreign-name','service':'fleet'}
            (tmp/'state').write_text(json.dumps({'containers':containers}))
            for name,content in [('docker',FAKE_DOCKER),('netem',NETEM),('pubsub.sh',PUBSUB)]:
                (tmp/name).write_text(content); (tmp/name).chmod(0o755)
            (tmp/'bag').mkdir(); (tmp/'bag/recording.mcap').write_bytes(b'fixture')
            metadata={'rosbag2_bagfile_information':{'storage_identifier':'mcap','relative_file_paths':['recording.mcap'],'duration':{'nanoseconds':1_000_000_000},'topics_with_message_count':[{'topic_metadata':{'name':'/cmd_vel','type':'geometry_msgs/msg/Twist'},'message_count':4}]}}
            (tmp/'bag/metadata.yaml').write_text(json.dumps(metadata))
            env=dict(os.environ,LAB4_DOCKER_BIN=str(tmp/'docker'),LAB4_NETEM_HELPER=str(tmp/'netem'),LAB4_BENCH_DIR=str(tmp),LAB4_CAPTURE_ROOT=str(tmp/'captures'),LAB4_STARTUP_WAIT='0',LAB4_SERVICE_WAIT='0',LAB4_REPLAY_WAIT='0',FIXTURE_STATE=str(tmp/'state'),FIXTURE_LOG=str(tmp/'log'),FIXTURE_MARKER=str(tmp/'marker'),FIXTURE_MODE=mode)
            cmd=['bash',str(HERE/'run_sweep.sh'),'--template',template,'--scenario',scenario,'--rmw',rmws,'--duration','1','--bag',str(tmp/'bag'),*extra]
            proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                if sig:
                    deadline=time.monotonic()+15
                    while not (tmp/'marker').exists() and proc.poll() is None and time.monotonic()<deadline: time.sleep(.02)
                    self.assertTrue((tmp/'marker').exists(),'probe did not start')
                    os.kill(proc.pid,sig)
                stdout,stderr=proc.communicate(timeout=25)
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGKILL); proc.communicate()
            rows=[]; artifacts={}
            for path in (tmp/'captures').glob('*/results.jsonl'): rows += [json.loads(line) for line in path.read_text().splitlines()]
            for path in (tmp/'captures').glob('*/*'):
                if path.is_file(): artifacts[path.name]=path.read_text()
            state=json.loads((tmp/'state').read_text())
            logs=[json.loads(line) for line in (tmp/'log').read_text().splitlines()] if (tmp/'log').exists() else []
            if sig:
                child=int((tmp/'marker').read_text())
                stat=Path(f'/proc/{child}/stat')
                self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z','owned probe still running')
            return proc.returncode,rows,state,logs,artifacts,stderr

    def assert_clean(self,state):
        self.assertEqual(set(state['containers']),{'core','unrelated'})

    def test_success_and_exact_cleanup(self):
        for template in ('A','B'):
            with self.subTest(template=template):
                rc,rows,state,logs,artifacts,err=self.run_case(template=template)
                self.assertEqual(rc,0,err); self.assertEqual([r['status'] for r in rows],['ok','ok']); self.assert_clean(state)
                self.assertTrue(all(r['scale']==(2 if template=='A' else 3) for r in rows))
                self.assertTrue(all(r['artifacts']['cleanup_verified'] for r in rows))
                self.assertTrue(all(any(k.endswith('.result.json') for k in artifacts) for _ in rows))
                self.assertFalse(any('down' in a or '--remove-orphans' in a for a in logs))
                if template == 'A':
                    self.assertTrue(all(r['metrics']['state_freshness_ms'] is None for r in rows))
                    self.assertTrue(all(r['template_a_metrics']['pubsub_latency_mean_ms'] == 1.0 for r in rows))
                else:
                    self.assertTrue(any(a[0] == 'stats' and 'lab4-receiver' in a[-1] for a in logs))

    def test_partial_startup_and_continuation(self):
        rc,rows,state,logs,artifacts,err=self.run_case('startup_fail',template='A')
        self.assertNotEqual(rc,0); self.assertEqual([r['status'] for r in rows],['failed','ok']); self.assert_clean(state)
        self.assertIn('workload_exit_7', rows[0]['reasons'])
        self.assertTrue(any('injected partial startup' in v for v in artifacts.values()))

    def test_probe_failures_and_missing_metrics(self):
        for mode in ('probe_fail','probe_timeout','malformed','nonfinite','wrong_scale'):
            with self.subTest(mode=mode):
                rc,rows,state,*_=self.run_case(mode)
                self.assertNotEqual(rc,0); self.assertEqual(len(rows),2); self.assertTrue(all(r['status']=='failed' for r in rows)); self.assert_clean(state)
                if mode == 'probe_timeout':
                    self.assertTrue(all('workload_exit_124' in r['reasons'] for r in rows))
        rc,rows,state,*_=self.run_case('missing_metric')
        self.assertEqual(rc,0); self.assertTrue(all(r['status']=='ok' and not r['metric_availability']['control_p99_ms'] for r in rows)); self.assert_clean(state)

    def test_shaping_before_after_and_rate(self):
        for mode,scenario in (('', 'S2'),('', 'S3'),('partial_ingress','S2'),('post_mismatch','S2'),('rate_mismatch','S3'),('state_unavailable','S0')):
            with self.subTest(mode=mode,scenario=scenario):
                rc,rows,state,logs,artifacts,err=self.run_case(mode,scenario=scenario)
                self.assertEqual(rc==0,mode=='',err)
                self.assertTrue(all(r['status']==('invalid' if mode else 'ok') for r in rows)); self.assert_clean(state)
                evidence=[json.loads(line) for name,body in artifacts.items() if name.endswith('.shaping.jsonl') for line in body.splitlines()]
                self.assertGreaterEqual(len(evidence),6)
                if not mode: self.assertTrue(all(e['validation']['valid'] for e in evidence))

    def test_preserves_stopped_conflict(self):
        rc,rows,state,logs,*_=self.run_case('conflict')
        self.assertNotEqual(rc,0); self.assertEqual(set(state['containers']),{'core','unrelated','stopped'})
        self.assertFalse(any('up' in a for a in logs))

    def test_signals_stop_next_cell_and_reap_probe(self):
        for sig in (signal.SIGINT,signal.SIGTERM):
            with self.subTest(sig=sig):
                rc,rows,state,*_=self.run_case('signal',sig=sig)
                self.assertNotEqual(rc,0); self.assertEqual(len(rows),1); self.assertEqual(rows[0]['status'],'interrupted'); self.assert_clean(state)

    def test_cleanup_failure_stops_sweep(self):
        rc,rows,state,*_=self.run_case('cleanup_fail')
        self.assertNotEqual(rc,0); self.assertEqual(len(rows),1); self.assertIn('cleanup_failed',rows[0]['reasons'])

    def test_report_failure_propagates(self):
        rc,rows,state,*_=self.run_case('report_fail')
        self.assertNotEqual(rc,0); self.assertTrue(all(r['status']=='ok' for r in rows)); self.assert_clean(state)

    def test_preflight_no_docker(self):
        for args in (('--template',''),('--template','Q'),('--rmw','nope'),('--rmw','cyclone,'),('--duration','0'),('--msg','bad'),('--template','A','--scenario','S2'),('--template','A','--rmw','zenoh-lowlat')):
            with self.subTest(args=args):
                rc,rows,state,logs,*_=self.run_case(extra=args)
                self.assertEqual(rc,2); self.assertFalse(rows); self.assertFalse(logs); self.assert_clean(state)


if __name__=='__main__': unittest.main()
