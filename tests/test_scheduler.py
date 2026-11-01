import os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import scheduler_rights as s
from audit import audit_contract

class SchedulerCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'db.sqlite';s.initialize(self.db)
        s.create_contract(self.db,'case',10,6)
    def child(self,*args):
        return subprocess.run([sys.executable,str(ROOT/'scheduler_rights.py'),str(self.db),*args],capture_output=True,text=True,timeout=15)
    def assert_audit(self):
        r=audit_contract(self.db,'case');self.assertTrue(r['ok'],r)
    def test_real_delay_with_worker(self):
        self.assertTrue(s.schedule(self.db,'case','job',3,delay_ms=100))
        r=self.child('worker','--max-wait-ms','250','--poll-ms','5')
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(s.contract(self.db,'case')['balance'],7)
        self.assertEqual(s.job(self.db,'job')['status'],'EXECUTED');self.assert_audit()
    def test_not_due(self):
        s.schedule(self.db,'case','job',3,delay_ms=200)
        self.assertEqual(s.run_job(self.db,'job')['reason'],'NOT_DUE')
        self.assertEqual(s.contract(self.db,'case')['balance'],10)
    def test_restart_persistent_job(self):
        s.schedule(self.db,'case','job',3,delay_ms=800)
        self.assertEqual(self.child('worker','--max-wait-ms','30').returncode,0)
        self.assertEqual(s.job(self.db,'job')['status'],'SCHEDULED')
        self.assertEqual(self.child('worker','--max-wait-ms','1050').returncode,0)
        self.assertEqual(s.job(self.db,'job')['status'],'EXECUTED');self.assert_audit()
    def test_stale_budget_admission_only(self):
        s.schedule(self.db,'case','job',4,policy='admission_only',due_ns=0)
        self.assertTrue(s.reserve_preparation(self.db,'case',2))
        self.assertTrue(s.run_job(self.db,'job')['effect'])
        self.assertEqual(s.contract(self.db,'case')['balance'],4)
        self.assertFalse(s.choose_b(self.db,'case'));self.assert_audit()
    def test_dispatch_guard_rechecks_budget(self):
        s.schedule(self.db,'case','job',4,policy='dispatch_guard',due_ns=0)
        self.assertTrue(s.reserve_preparation(self.db,'case',2))
        self.assertEqual(s.run_job(self.db,'job')['reason'],'RESERVED_CHOICE_WOULD_BE_LOST')
        self.assertTrue(s.choose_b(self.db,'case'));self.assertTrue(s.fulfill_b(self.db,'case'));self.assert_audit()
    def test_equivalent_strong_baseline(self):
        s.schedule(self.db,'case','job',4,policy='global_equivalent',due_ns=0)
        s.reserve_preparation(self.db,'case',2)
        self.assertEqual(s.run_job(self.db,'job')['reason'],'RESERVED_CHOICE_WOULD_BE_LOST')
    def test_stale_revocation_baseline(self):
        s.schedule(self.db,'case','job',3,policy='admission_only',due_ns=0)
        s.revoke(self.db,'case')
        self.assertTrue(s.run_job(self.db,'job')['effect']);self.assert_audit()
    def test_revocation_guard(self):
        s.schedule(self.db,'case','job',3,policy='dispatch_guard',due_ns=0)
        s.revoke(self.db,'case')
        self.assertEqual(s.run_job(self.db,'job')['reason'],'REVOKED_OR_STALE_EPOCH');self.assert_audit()
    def test_decided_baseline_executes(self):
        s.schedule(self.db,'case','job',3,policy='admission_only',due_ns=0)
        self.assertTrue(s.choose_b(self.db,'case'))
        self.assertTrue(s.run_job(self.db,'job')['effect']);self.assert_audit()
    def test_decided_guard_refuses(self):
        s.schedule(self.db,'case','job',3,policy='dispatch_guard',due_ns=0)
        self.assertTrue(s.choose_b(self.db,'case'))
        self.assertEqual(s.run_job(self.db,'job')['reason'],'HUMAN_ALREADY_DECIDED')
        self.assertTrue(s.fulfill_b(self.db,'case'));self.assert_audit()
    def test_no_duplicate_dispatch(self):
        s.schedule(self.db,'case','job',3,due_ns=0)
        self.assertTrue(s.run_job(self.db,'job')['effect'])
        self.assertFalse(s.run_job(self.db,'job')['effect'])
        self.assertEqual(s.job(self.db,'job')['execution_count'],1);self.assert_audit()
    def test_crash_before_commit_rolled_back(self):
        s.schedule(self.db,'case','job',3,due_ns=0)
        r=self.child('run-one','job','--crash','before_commit')
        self.assertEqual(r.returncode,78,r.stderr)
        self.assertEqual(s.job(self.db,'job')['status'],'SCHEDULED')
        self.assertEqual(s.contract(self.db,'case')['balance'],10)
        self.assertEqual(self.child('worker','--max-wait-ms','10').returncode,0)
        self.assertEqual(s.contract(self.db,'case')['balance'],7);self.assert_audit()
    def test_crash_after_commit_no_double_spend(self):
        s.schedule(self.db,'case','job',3,due_ns=0)
        r=self.child('run-one','job','--crash','after_commit')
        self.assertEqual(r.returncode,79,r.stderr)
        self.assertEqual(s.job(self.db,'job')['status'],'EXECUTED')
        self.assertEqual(self.child('worker','--max-wait-ms','10').returncode,0)
        self.assertEqual(s.contract(self.db,'case')['balance'],7)
        self.assertEqual(s.job(self.db,'job')['execution_count'],1);self.assert_audit()
    def test_two_workers_compete(self):
        s.schedule(self.db,'case','job',3,due_ns=0)
        cmds=[[sys.executable,str(ROOT/'scheduler_rights.py'),str(self.db),'run-one','job']]*2
        a=subprocess.Popen(cmds[0],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        b=subprocess.Popen(cmds[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        ao,ae=a.communicate(timeout=15);bo,be=b.communicate(timeout=15)
        self.assertEqual(a.returncode,0,ae);self.assertEqual(b.returncode,0,be)
        self.assertEqual(s.contract(self.db,'case')['balance'],7)
        self.assertEqual(s.job(self.db,'job')['execution_count'],1);self.assert_audit()
    def test_revoke_race_serialization(self):
        s.schedule(self.db,'case','job',3,due_ns=0)
        worker=subprocess.Popen([sys.executable,str(ROOT/'scheduler_rights.py'),str(self.db),'run-one','job'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.assertEqual(self.child('revoke','case').returncode,0)
        _,err=worker.communicate(timeout=15)
        self.assertEqual(worker.returncode,0,err)
        log=s.log_for(self.db,'case')
        relevant=[x['kind'] for x in log if x['kind'] in ('DISPATCH','REVOKE')]
        if relevant[0]=='REVOKE':self.assertEqual(s.job(self.db,'job')['status'],'DENIED')
        else:self.assertEqual(s.job(self.db,'job')['status'],'EXECUTED')
        self.assert_audit()
    def test_direct_sql_bypass_detected_by_audit(self):
        s.schedule(self.db,'case','job',3,due_ns=0)
        with s.transaction(self.db) as c:c.execute('UPDATE contracts SET balance=2 WHERE id=?',('case',))
        self.assertFalse(audit_contract(self.db,'case')['ok'])
    def test_corrupted_log_detected(self):
        s.schedule(self.db,'case','job',3,due_ns=0);s.run_job(self.db,'job')
        with s.transaction(self.db) as c:
            c.execute('UPDATE log SET detail=? WHERE kind=?', ('{"balance":500,"reserve":6}', 'CREATE'))
        self.assertFalse(audit_contract(self.db,'case')['ok'])
    def test_two_admitted_jobs_compete_under_dispatch_guard(self):
        # Both look safe when admitted; jointly they would destroy B.
        s.schedule(self.db,'case','jobA',3,policy='dispatch_guard',due_ns=0)
        s.schedule(self.db,'case','jobB',3,policy='dispatch_guard',due_ns=0)
        cmd=lambda j:[sys.executable,str(ROOT/'scheduler_rights.py'),str(self.db),'run-one',j]
        a=subprocess.Popen(cmd('jobA'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        b=subprocess.Popen(cmd('jobB'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        ao,ae=a.communicate(timeout=15);bo,be=b.communicate(timeout=15)
        self.assertEqual((a.returncode,b.returncode),(0,0),(ae,be))
        self.assertEqual(sorted([s.job(self.db,'jobA')['status'],s.job(self.db,'jobB')['status']]),['DENIED','EXECUTED'])
        self.assertEqual(s.contract(self.db,'case')['balance'],7)
        self.assertTrue(s.choose_b(self.db,'case'));self.assertTrue(s.fulfill_b(self.db,'case'));self.assert_audit()
    def test_two_admitted_jobs_baseline_loses_choice(self):
        s.schedule(self.db,'case','jobA',3,policy='admission_only',due_ns=0)
        s.schedule(self.db,'case','jobB',3,policy='admission_only',due_ns=0)
        self.assertTrue(s.run_job(self.db,'jobA')['effect'])
        self.assertTrue(s.run_job(self.db,'jobB')['effect'])
        self.assertEqual(s.contract(self.db,'case')['balance'],4)
        self.assertFalse(s.choose_b(self.db,'case'));self.assert_audit()
    def test_validation(self):
        with self.assertRaises(ValueError):s.schedule(self.db,'case','job',-3)
        with self.assertRaises(ValueError):s.schedule(self.db,'case','job',3,policy='unknown')
        with self.assertRaises(ValueError):s.schedule(self.db,'case','../escape',3)
if __name__=='__main__':unittest.main()
