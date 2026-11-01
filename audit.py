"""Independently replay local SQL event ledger and compare against database state.
Only detects ordinary inconsistency; privileged actors can rewrite both DB and log.
"""
import argparse
import json
from contextlib import closing
from scheduler_rights import connect

def audit_contract(db,cid):
    with closing(connect(db)) as c:
        records=c.execute('SELECT kind,job_id,detail FROM log WHERE contract_id=? ORDER BY id',(cid,)).fetchall()
        state=c.execute('SELECT balance,reserve_b,decision,permission_on,permission_epoch FROM contracts WHERE id=?',(cid,)).fetchone()
        jobs=c.execute('SELECT id,status,execution_count,result FROM scheduled_jobs WHERE contract_id=?',(cid,)).fetchall()
    errors=[]
    if not state or not records or records[0][0]!='CREATE':return {'ok':False,'errors':['MISSING_CONTRACT_OR_CREATE']}
    first=json.loads(records[0][2]); balance=first['balance']; epoch=0; permission=1; decision='PENDING'
    seen={}
    for kind,jid,data in records[1:]:
        d=json.loads(data)
        if kind=='INTERIM_PREP':
            if d['balance_before']!=balance:errors.append('INTERIM_BEFORE_MISMATCH')
            if d['allowed']:balance-=d['cost']
        elif kind=='REVOKE':
            epoch+=1;permission=0
            if d['new_epoch']!=epoch:errors.append('EPOCH_MISMATCH')
        elif kind=='HUMAN_CHOICE_B':
            if d['accepted']:decision='B'
        elif kind=='FULFILL_B':
            if d['success']:
                balance-=d['required'];decision='FULFILLED'
            else:decision='BROKEN'
        elif kind=='DISPATCH':
            if jid in seen:errors.append('DUPLICATE_DISPATCH')
            seen[jid]=d
            if d['before']!=balance:errors.append('DISPATCH_BEFORE_MISMATCH')
            if d['effect']:balance-=next((r[1] for r in _jobs_with_cost(db,cid) if r[0]==jid),0)
            if d['after']!=balance:errors.append('DISPATCH_AFTER_MISMATCH')
    if state!=(balance,first['reserve'],decision,permission,epoch):errors.append('FINAL_STATE_MISMATCH')
    for jid,status,execution_count,result in jobs:
        if status=='SCHEDULED' and (execution_count or jid in seen):errors.append('PENDING_JOB_INCONSISTENT')
        if status=='EXECUTED' and (execution_count!=1 or jid not in seen or not seen[jid]['effect']):errors.append('EXECUTED_JOB_INCONSISTENT')
        if status=='DENIED' and (execution_count!=0 or jid not in seen or seen[jid]['effect']):errors.append('DENIED_JOB_INCONSISTENT')
    return {'ok':not errors,'errors':errors,'event_count':len(records),'jobs':len(jobs),'final_balance':balance}

def _jobs_with_cost(db,cid):
    with closing(connect(db)) as c:
        return c.execute('SELECT id,cost FROM scheduled_jobs WHERE contract_id=?',(cid,)).fetchall()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('db');p.add_argument('case');a=p.parse_args()
    print(json.dumps(audit_contract(a.db,a.case),indent=2))
