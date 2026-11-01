"""Conservative evidence claims for local DB and file effects, no API or LLM."""
import hashlib,json,tempfile
from pathlib import Path
import scheduler_rights as s
import choice_assurance as a
ROOT=Path(__file__).resolve().parent

def run():
 with tempfile.TemporaryDirectory() as t:
  base=Path(t);db=base/'store.sqlite';out=base/'out'
  s.initialize(db);s.create_contract(db,'c',10,6)
  payload=b'human-empowerment-offline-evidence-pilot'
  spec=a.spec_for('c','j','INSTRUMENTAL','LOCAL_FILE',hashlib.sha256(payload).hexdigest())
  assert a.schedule_assured(db,spec,3)
  result=a.assured_dispatch(db,spec)
  assert result['decision']=='DELEGATE'
  missing=a.make_receipt(db,spec,out)
  assert missing['claims']['local_file_effect']=='UNKNOWN_FILE_ABSENT'
  a.publish_local_bytes(out,'j',payload)
  present=a.make_receipt(db,spec,out)
  assert present['claims']['local_file_effect']=='VERIFIED_LOCAL_BYTES'
  assert a.verify_receipt(db,present,out)['valid_for_current_local_observation']
  a.publish_local_bytes(out,'j',b'changed-content')
  contradicted=a.make_receipt(db,spec,out)
  assert contradicted['claims']['local_file_effect']=='CONTRADICTED_FILE_CONTENT'
  assert not a.verify_receipt(db,present,out)['valid_for_current_local_observation']
  tampered=json.loads(json.dumps(missing));tampered['claims']['external_delivery']='VERIFIED'
  assert not a.verify_receipt(db,tampered,out)['valid_for_current_local_observation']
  # Claim boundaries: SQL_COMMITTED does not prove file existence; observed
  # file bytes do not prove third-party delivery or actual human understanding.
  results={'schema':a.PROFILE,'data_type':'LOCAL_REEXECUTABLE_OBSERVATIONS',
    'outcomes':{
     'sql_committed_file_absent':missing['claims'],
     'local_file_digest_verified':present['claims'],
     'local_file_digest_contradicted':contradicted['claims'],
     'prior_receipt_after_changed_file':a.verify_receipt(db,present,out),
     'fabricated_external_delivery_claim':a.verify_receipt(db,tampered,out)},
    'receipt_examples':{'missing':missing,'present':present,'contradicted':contradicted},
    'limitations':['No external service/recipient','No signature/trusted timestamps',
                   'Local files can preexist, so hash is not causal attribution',
                   'No human subjects or evidence of comprehension']}
  outdir=ROOT/'results';outdir.mkdir(exist_ok=True)
  (outdir/'evidence_probes.json').write_text(json.dumps(results,indent=2,sort_keys=True)+'\n')
  return {'sql_committed_file_absent':missing['claims']['local_file_effect'],
          'local_file_verified':present['claims']['local_file_effect'],
          'tampered_file':contradicted['claims']['local_file_effect'],
          'stale_receipt_rejected':not a.verify_receipt(db,present,out)['valid_for_current_local_observation']}
if __name__=='__main__':print(json.dumps(run(),indent=2))
