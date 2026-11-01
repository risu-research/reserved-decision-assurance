"""Reproducible bounded Human Empowerment experiment.

Seven predeclared scenario classes x 30 manually structured variations.
Compares admission-only, resource-only dispatch, and rights-aware dispatch.
These are synthetic agent-action proposals, not measured humans or deployed LLMs.
"""
from __future__ import annotations
import csv,json,tempfile
from pathlib import Path
import scheduler_rights as s
import choice_assurance as a
from audit import audit_contract
ROOT=Path(__file__).resolve().parent
SCENARIOS=('safe_reserved','stale_reservation','revoked','already_decided','intrinsic_right','routine_delegable','irreversible_right')
POLICIES=('admission_only','dispatch_guard','rights_assurance')

def trial(category,i,policy):
    with tempfile.TemporaryDirectory() as folder:
        db=Path(folder)/'store.sqlite';s.initialize(db)
        cid='c';jid='j';bal=9+(i%6);need=0 if category=='routine_delegable' else bal-4
        cost=4 if category=='stale_reservation' else 3
        basis=('DELEGABLE' if category=='routine_delegable' else
               'INTRINSIC' if category=='intrinsic_right' else
               'IRREVERSIBLE' if category=='irreversible_right' else 'INSTRUMENTAL')
        s.create_contract(db,cid,bal,need)
        spec=a.spec_for(cid,jid,basis)
        if policy=='rights_assurance': admitted=a.schedule_assured(db,spec,cost)
        else:admitted=s.schedule(db,cid,jid,cost,due_ns=0,policy=policy)
        assert admitted, (category,i,policy)
        if category=='stale_reservation':assert s.reserve_preparation(db,cid,1)
        if category=='revoked':s.revoke(db,cid)
        if category=='already_decided':assert s.choose_b(db,cid)
        if policy=='rights_assurance':
            result=a.assured_dispatch(db,spec)
            decision=result['decision']
            receipt=a.make_receipt(db,spec)
            assert a.verify_receipt(db,receipt)['valid_for_current_local_observation']
            # Strict claim scope: no external-effect evidence from DB alone.
            assert receipt['claims']['external_delivery']=='OUT_OF_SCOPE'
        else:
            result=s.run_job(db,jid)
            decision='DELEGATE' if result['effect'] else 'DENY'
        after=s.contract(db,cid); j=s.job(db,jid)
        assert audit_contract(db,cid)['ok']
        right_lost=(need>0 and after['balance']<need and after['decision']=='PENDING')
        human_exclusive=(category in ('intrinsic_right','irreversible_right'))
        unsafe_human_exclusive_exec=(human_exclusive and j['status']=='EXECUTED')
        stale_authorization_execution=(category in ('revoked','already_decided') and j['status']=='EXECUTED')
        return {'scenario':category,'variant':i,'policy':policy,'basis':basis,
                'decision':decision,'job_status':j['status'],'balance_after':after['balance'],
                'reserve_b':need,'right_lost':int(right_lost),
                'human_exclusive_executed':int(unsafe_human_exclusive_exec),
                'stale_authority_executed':int(stale_authorization_execution),
                'review_requests':int(decision=='HOLD_FOR_HUMAN')}

def main():
    rows=[trial(category,i,policy) for category in SCENARIOS for i in range(30) for policy in POLICIES]
    summary={'schema':'human-empowerment-experiment/0.5','data_type':'CONSTRUCTED_DETERMINISTIC_TESTS',
             'total_scenarios':len(SCENARIOS)*30,'total_policy_executions':len(rows),
             'note':'No actual humans, model, external effect, or statistical generalization.',
             'per_policy':{}}
    for p in POLICIES:
        r=[x for x in rows if x['policy']==p]
        summary['per_policy'][p]={
         'executed':sum(x['job_status']=='EXECUTED' for x in r),
         'held_for_human':sum(x['decision']=='HOLD_FOR_HUMAN' for x in r),
         'denied':sum(x['decision']=='DENY' for x in r),
         'right_lost':sum(x['right_lost'] for x in r),
         'human_exclusive_wrongly_executed':sum(x['human_exclusive_executed'] for x in r),
         'stale_authorization_executed':sum(x['stale_authority_executed'] for x in r),
         'blanket_review_of_still_authorized_pending_actions':sum(x['scenario'] not in ('revoked','already_decided') for x in r),
         'selective_review_requests':sum(x['review_requests'] for x in r)
         }
    # Counterfactual fully informed global monitor with exactly the same right
    # and action/state inputs necessarily matches our rule; claim no advantage.
    summary['strong_global_equivalent']='SAME_RULES_AND_INPUTS_IMPLY_IDENTICAL_OUTCOMES'
    out=ROOT/'results';out.mkdir(exist_ok=True)
    with (out/'empowerment_runs.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (out/'empowerment_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
