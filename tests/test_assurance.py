import copy,hashlib,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import scheduler_rights as s
import choice_assurance as a

class AssuranceTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
  self.d=Path(t.name);self.db=self.d/'jobs.db';s.initialize(self.db)
  s.create_contract(self.db,'case',10,6)
 def spec(self,basis='INSTRUMENTAL',kind='SQL_ONLY',sha=None):
  return a.spec_for('case','job',basis,kind,sha)
 def enqueue(self,cost=3,policy='dispatch_guard',basis='INSTRUMENTAL',kind='SQL_ONLY',sha=None):
  if policy=='dispatch_guard':
   self.assertTrue(a.schedule_assured(self.db,self.spec(basis,kind,sha),cost,due_ns=0))
  else:
   self.assertTrue(s.schedule(self.db,'case','job',cost,policy=policy,due_ns=0))
   # Deliberately weak comparison: pinned label but baseline never enforces it.
   with closing(s.connect(self.db)) as c:c.execute(a.SPEC_TABLE)
   x=self.spec()
   with s.transaction(self.db) as c:
    c.execute('INSERT INTO bound_rights_specs(job_id,contract_id,spec_json,spec_sha256) VALUES (?,?,?,?)',
              ('job','case',a.canonical(x).decode(),a.digest(x)))
 def test_preflight_is_advisory_guard_is_atomic(self):
  self.enqueue(4);x=self.spec()
  self.assertEqual(a.preflight(self.db,x)['decision'],'DELEGATE')
  self.assertTrue(s.reserve_preparation(self.db,'case',2))
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'HOLD_FOR_HUMAN')
  self.assertEqual(s.job(self.db,'job')['status'],'SCHEDULED')
  self.assertEqual(a.make_receipt(self.db,x)['claims']['sqlite_effect'],'NO_DB_EFFECT_RECORDED')
 def test_delegation_preserves_choice(self):
  self.enqueue(3);x=self.spec()
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'DELEGATE')
  r=a.make_receipt(self.db,x)
  self.assertEqual(r['claims']['authority_at_dispatch'],'VALID_AT_DISPATCH')
  self.assertEqual(r['claims']['reserved_choice_at_dispatch'],'PRESERVED_AT_DISPATCH')
  self.assertEqual(r['claims']['sqlite_effect'],'VERIFIED_SQLITE_TRANSITION')
  self.assertTrue(a.verify_receipt(self.db,r)['valid_for_current_local_observation'])
  self.assertTrue(s.choose_b(self.db,'case'));self.assertTrue(s.fulfill_b(self.db,'case'))
 def test_revoke_is_denied(self):
  self.enqueue();x=self.spec();s.revoke(self.db,'case')
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'DENY')
  self.assertEqual(s.job(self.db,'job')['status'],'DENIED')
 def test_human_already_decided_is_denied(self):
  self.enqueue();x=self.spec();self.assertTrue(s.choose_b(self.db,'case'))
  self.assertEqual(a.assured_dispatch(self.db,x)['reason'],'HUMAN_ALREADY_DECIDED')
 def test_intrinsic_right_requires_review_even_if_resources_safe(self):
  self.enqueue(basis='INTRINSIC');x=self.spec('INTRINSIC')
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'HOLD_FOR_HUMAN')
  self.assertEqual(s.contract(self.db,'case')['balance'],10)
  self.assertEqual(a.make_receipt(self.db,x)['claims']['normative_basis'],'INTRINSIC')
 def test_delegable_zero_reserve_no_review(self):
  s.create_contract(self.db,'routine',10,0)
  self.assertTrue(a.schedule_assured(self.db,a.spec_for('routine','routine_job','DELEGABLE'),4,due_ns=0))
  x=a.spec_for('routine','routine_job','DELEGABLE')
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'DELEGATE')
  self.assertEqual(s.contract(self.db,'routine')['balance'],6)
 def test_admission_baseline_is_detected_as_hollow(self):
  self.enqueue(4,policy='admission_only');s.reserve_preparation(self.db,'case',2)
  self.assertTrue(s.run_job(self.db,'job')['effect'])
  r=a.make_receipt(self.db,self.spec())
  self.assertEqual(r['claims']['reserved_choice_at_dispatch'],'LOST_AT_DISPATCH')
  self.assertEqual(r['claims']['sqlite_effect'],'VERIFIED_SQLITE_TRANSITION')
 def test_stale_authority_detected_in_baseline(self):
  self.enqueue(policy='admission_only');s.revoke(self.db,'case');s.run_job(self.db,'job')
  r=a.make_receipt(self.db,self.spec())
  self.assertEqual(r['claims']['authority_at_dispatch'],'INVALID_AT_DISPATCH')
 def test_sql_commit_not_file_proof_and_then_file(self):
  payload=b'local example only';h=hashlib.sha256(payload).hexdigest();self.enqueue(basis='INSTRUMENTAL',kind='LOCAL_FILE',sha=h)
  x=self.spec('INSTRUMENTAL','LOCAL_FILE',h)
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'DELEGATE')
  receipt1=a.make_receipt(self.db,x,self.d)
  self.assertEqual(receipt1['claims']['sqlite_effect'],'VERIFIED_SQLITE_TRANSITION')
  self.assertEqual(receipt1['claims']['local_file_effect'],'UNKNOWN_FILE_ABSENT')
  a.publish_local_bytes(self.d,'job',payload)
  receipt2=a.make_receipt(self.db,x,self.d)
  self.assertEqual(receipt2['claims']['local_file_effect'],'VERIFIED_LOCAL_BYTES')
  self.assertFalse(a.verify_receipt(self.db,receipt1,self.d)['valid_for_current_local_observation'])
  self.assertTrue(a.verify_receipt(self.db,receipt2,self.d)['valid_for_current_local_observation'])
 def test_corrupt_file_contradiction_and_stale_receipt(self):
  payload=b'ok';self.enqueue(basis='INSTRUMENTAL',kind='LOCAL_FILE',sha=hashlib.sha256(payload).hexdigest());x=self.spec('INSTRUMENTAL','LOCAL_FILE',hashlib.sha256(payload).hexdigest())
  a.assured_dispatch(self.db,x)
  a.publish_local_bytes(self.d,'job',payload)
  r=a.make_receipt(self.db,x,self.d)
  a.publish_local_bytes(self.d,'job',b'wrong')
  self.assertEqual(a.make_receipt(self.db,x,self.d)['claims']['local_file_effect'],'CONTRADICTED_FILE_CONTENT')
  self.assertFalse(a.verify_receipt(self.db,r,self.d)['valid_for_current_local_observation'])
 def test_receipt_mutation_rejected(self):
  self.enqueue();x=self.spec();a.assured_dispatch(self.db,x)
  r=a.make_receipt(self.db,x)
  broken=copy.deepcopy(r);broken['claims']['external_delivery']='VERIFIED'
  self.assertFalse(a.verify_receipt(self.db,broken)['valid_for_current_local_observation'])
 def test_contract_id_mismatch_rejected(self):
  self.enqueue();x=self.spec();x['contract_id']='wrong'
  with self.assertRaises(ValueError):a.assured_dispatch(self.db,x)
 def test_two_jobs_separate_process_one_guarded_effect(self):
  self.enqueue(3)
  self.assertTrue(a.schedule_assured(self.db,a.spec_for('case','job2'),3,due_ns=0))
  run=lambda j:[sys.executable,str(ROOT/'choice_assurance.py'),str(self.db),'case',j,'--op','dispatch']
  p=subprocess.Popen(run('job'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  q=subprocess.Popen(run('job2'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  r1,err1=p.communicate(timeout=15);r2,err2=q.communicate(timeout=15)
  self.assertEqual((p.returncode,q.returncode),(0,0),(err1,err2))
  self.assertEqual(s.contract(self.db,'case')['balance'],7)
  self.assertEqual(sorted([s.job(self.db,'job')['status'],s.job(self.db,'job2')['status']]),['EXECUTED','SCHEDULED'])
 def test_ledger_inconsistency_cannot_support_claim(self):
  self.enqueue();x=self.spec();a.assured_dispatch(self.db,x)
  with s.transaction(self.db) as c:c.execute('UPDATE contracts SET balance=2 WHERE id=?',('case',))
  r=a.make_receipt(self.db,x)
  self.assertEqual(r['claims']['sqlite_effect'],'UNKNOWN_LEDGER_INCONSISTENT')
 def test_changed_decision_basis_refused_at_dispatch(self):
  self.enqueue();changed=self.spec('DELEGABLE')
  with self.assertRaises(ValueError):a.assured_dispatch(self.db,changed)
  self.assertEqual(s.job(self.db,'job')['status'],'SCHEDULED')
  self.assertEqual(a.preflight(self.db,changed)['decision'],'UNKNOWN')
 def test_delegable_contract_with_existing_reserved_right_refused(self):
  with self.assertRaises(ValueError):a.schedule_assured(self.db,self.spec('DELEGABLE'),2)
 def test_hold_then_simulated_signoff_then_execute(self):
  self.enqueue(basis='INTRINSIC');x=self.spec('INTRINSIC')
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'HOLD_FOR_HUMAN')
  rec=a.record_simulated_human_signoff(self.db,x)
  self.assertEqual(rec['source'],'SIMULATED_HUMAN_TEST_CONTROLLER')
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'DELEGATE')
  receipt=a.make_receipt(self.db,x)
  self.assertEqual(receipt['claims']['local_human_signoff_record'],'RECORDED_TEST_CONTROLLER')
  self.assertTrue(s.choose_b(self.db,'case'))
 def test_signoff_stale_after_revocation(self):
  self.enqueue(basis='INTRINSIC');x=self.spec('INTRINSIC')
  a.record_simulated_human_signoff(self.db,x)
  s.revoke(self.db,'case')
  self.assertEqual(a.assured_dispatch(self.db,x)['decision'],'DENY')
 def test_signoff_cannot_release_reserved_budget(self):
  self.enqueue(cost=4,basis='INTRINSIC');x=self.spec('INTRINSIC')
  s.reserve_preparation(self.db,'case',2)
  with self.assertRaises(ValueError):a.record_simulated_human_signoff(self.db,x)
 def test_out_of_scope_never_verified(self):
  self.enqueue();x=self.spec();a.assured_dispatch(self.db,x)
  r=a.make_receipt(self.db,x)
  self.assertEqual(r['claims']['external_delivery'],'OUT_OF_SCOPE')
  self.assertEqual(r['claims']['actual_human_understanding'],'OUT_OF_SCOPE')
if __name__=='__main__':unittest.main()
