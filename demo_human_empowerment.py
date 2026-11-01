"""Minimal offline example of when the human retains control and when to delegate."""
import json,tempfile
from pathlib import Path
import scheduler_rights as s
import choice_assurance as a

def demo():
 with tempfile.TemporaryDirectory() as tmp:
  db=Path(tmp)/'demo.sqlite';s.initialize(db)
  s.create_contract(db,'human',10,6)
  s.create_contract(db,'routine',10,0)
  intrinsic=a.spec_for('human','human_job','INTRINSIC')
  delegable=a.spec_for('routine','routine_job','DELEGABLE')
  a.schedule_assured(db,intrinsic,3)
  a.schedule_assured(db,delegable,3)
  held=a.assured_dispatch(db,intrinsic)
  delegated=a.assured_dispatch(db,delegable)
  simulated_signoff=a.record_simulated_human_signoff(db,intrinsic)
  after_signoff=a.assured_dispatch(db,intrinsic)
  return {'human_reserved_initially':held,'routine_delegation':delegated,
          'simulated_signoff':simulated_signoff,'human_reserved_after_signoff':after_signoff,
          'right_retained':s.choose_b(db,'human'),
          'receipt_human':a.make_receipt(db,intrinsic)['claims'],
          'receipt_routine':a.make_receipt(db,delegable)['claims']}
if __name__=='__main__':print(json.dumps(demo(),indent=2))
