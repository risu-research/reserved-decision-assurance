"""Explicit, simulated human signoff: hold -> local signoff -> recheck."""
import csv,json,tempfile
from pathlib import Path
import scheduler_rights as s
import choice_assurance as a
ROOT=Path(__file__).resolve().parent
CATEGORIES=('approval_then_execute','approval_then_revocation','approval_then_resource_change','approval_then_human_choice')
def trial(group,i):
 with tempfile.TemporaryDirectory() as t:
  db=Path(t)/'db.sqlite';s.initialize(db)
  balance=10+(i%4);reserve=balance-4;cost=4 if group=='approval_then_resource_change' else 3
  s.create_contract(db,'c',balance,reserve)
  spec=a.spec_for('c','j','INTRINSIC')
  assert a.schedule_assured(db,spec,cost)
  assert a.assured_dispatch(db,spec)['decision']=='HOLD_FOR_HUMAN'
  a.record_simulated_human_signoff(db,spec)
  if group=='approval_then_revocation':s.revoke(db,'c')
  elif group=='approval_then_resource_change':assert s.reserve_preparation(db,'c',1)
  elif group=='approval_then_human_choice':assert s.choose_b(db,'c')
  decision=a.assured_dispatch(db,spec)['decision']
  r=a.make_receipt(db,spec)
  assert a.verify_receipt(db,r)['valid_for_current_local_observation']
  return {'scenario':group,'variant':i,'decision':decision,'executed':int(s.job(db,'j')['status']=='EXECUTED'),
          'choice_still_feasible':int(s.contract(db,'c')['balance']>=reserve),
          'local_approval_record':r['claims']['local_human_signoff_record'],
          'true_human_authenticated':0}
def main():
 rows=[trial(g,i) for g in CATEGORIES for i in range(15)]
 summary={'data_type':'SCRIPTED_SIMULATED_HUMAN_SIGNOFF','trials':len(rows),
    'by_class':{g:{'n':15,'outcomes':{d:sum(r['scenario']==g and r['decision']==d for r in rows) for d in ('DELEGATE','DENY','HOLD_FOR_HUMAN')}} for g in CATEGORIES},
    'limitation':'Signoff injected by trusted local test controller; no actual user identity, comprehension, or decision quality tested.'}
 out=ROOT/'results';out.mkdir(exist_ok=True)
 with (out/'signoff_trials.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 (out/'signoff_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
