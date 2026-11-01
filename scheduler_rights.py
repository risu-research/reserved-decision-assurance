"""Offline durable scheduled-job evaluation under an explicitly reserved human choice.

All actions, clock readings and SQL operations are local. This is an executable
research reference, not a production OS access-control mechanism. No LLM/API.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager, closing
import json
import os
import sqlite3
import time

POLICIES = ('admission_only', 'dispatch_guard', 'global_equivalent')
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS contracts (
 id TEXT PRIMARY KEY,
 balance INTEGER NOT NULL CHECK(balance>=0),
 reserve_b INTEGER NOT NULL CHECK(reserve_b>=0),
 decision TEXT NOT NULL DEFAULT 'PENDING' CHECK(decision IN ('PENDING','B','FULFILLED','BROKEN')),
 permission_on INTEGER NOT NULL DEFAULT 1 CHECK(permission_on IN (0,1)),
 permission_epoch INTEGER NOT NULL DEFAULT 0 CHECK(permission_epoch>=0)
);
CREATE TABLE IF NOT EXISTS scheduled_jobs (
 id TEXT PRIMARY KEY,
 contract_id TEXT NOT NULL REFERENCES contracts(id),
 cost INTEGER NOT NULL CHECK(cost>=0),
 due_ns INTEGER NOT NULL,
 admitted_epoch INTEGER NOT NULL,
 policy TEXT NOT NULL CHECK(policy IN ('admission_only','dispatch_guard','global_equivalent')),
 status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK(status IN ('SCHEDULED','EXECUTED','DENIED')),
 result TEXT NOT NULL DEFAULT 'WAITING',
 execution_count INTEGER NOT NULL DEFAULT 0 CHECK(execution_count IN (0,1))
);
CREATE TABLE IF NOT EXISTS log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 contract_id TEXT NOT NULL,
 job_id TEXT,
 kind TEXT NOT NULL,
 detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS job_due_idx ON scheduled_jobs(status,due_ns,id);
"""

def connect(path):
    con=sqlite3.connect(str(path),isolation_level=None,timeout=15)
    con.execute('PRAGMA busy_timeout=15000')
    con.execute('PRAGMA foreign_keys=ON')
    return con

@contextmanager
def transaction(path):
    con=connect(path)
    try:
        con.execute('BEGIN IMMEDIATE')
        yield con
        con.execute('COMMIT')
    except BaseException:
        if con.in_transaction: con.execute('ROLLBACK')
        raise
    finally: con.close()

def initialize(path):
    con=connect(path)
    try: con.executescript(SCHEMA)
    finally: con.close()

def positive_int(n):
    if isinstance(n,bool) or not isinstance(n,int) or n<0: raise ValueError('nonnegative int required')
    return n

def text_id(x):
    if not isinstance(x,str) or not (1<=len(x)<=80) or not all(c.isalnum() or c in '-_' for c in x):
        raise ValueError('IDs must be 1..80 letters/numbers/_/-')
    return x

def emit(con, cid, kind, detail, jid=None):
    con.execute('INSERT INTO log(contract_id,job_id,kind,detail) VALUES (?,?,?,?)',
                (cid,jid,kind,json.dumps(detail,sort_keys=True)))

def create_contract(path,cid,balance,reserve):
    text_id(cid); positive_int(balance); positive_int(reserve)
    if balance<reserve: raise ValueError('reserved choice initially impossible')
    with transaction(path) as c:
        c.execute('INSERT INTO contracts(id,balance,reserve_b) VALUES (?,?,?)',(cid,balance,reserve))
        emit(c,cid,'CREATE',{'balance':balance,'reserve':reserve})

def contract(path,cid):
    with closing(connect(path)) as c:
        r=c.execute('SELECT balance,reserve_b,decision,permission_on,permission_epoch FROM contracts WHERE id=?',(cid,)).fetchone()
    if r is None:raise KeyError(cid)
    return dict(zip(('balance','reserve_b','decision','permission_on','permission_epoch'),r))

def job(path,jid):
    with closing(connect(path)) as c:
        r=c.execute('SELECT contract_id,cost,due_ns,admitted_epoch,policy,status,result,execution_count FROM scheduled_jobs WHERE id=?',(jid,)).fetchone()
    if r is None:raise KeyError(jid)
    return dict(zip(('contract_id','cost','due_ns','admitted_epoch','policy','status','result','execution_count'),r))

def reserve_preparation(path,cid,cost):
    """Another guarded direct action occurs between enqueue and due time."""
    positive_int(cost)
    with transaction(path) as c:
        r=c.execute('SELECT balance,reserve_b,decision,permission_on FROM contracts WHERE id=?',(cid,)).fetchone()
        if r is None: raise KeyError(cid)
        bal,need,choice,permission=r
        ok=bool(permission and choice=='PENDING' and bal-cost>=need)
        if ok:c.execute('UPDATE contracts SET balance=? WHERE id=?',(bal-cost,cid))
        emit(c,cid,'INTERIM_PREP',{'cost':cost,'allowed':ok,'balance_before':bal})
        return ok

def schedule(path,cid,jid,cost,delay_ms=0,policy='dispatch_guard',due_ns=None):
    text_id(cid); text_id(jid); positive_int(cost); positive_int(delay_ms)
    if policy not in POLICIES: raise ValueError(policy)
    if due_ns is None: due_ns=time.time_ns()+delay_ms*1000000
    with transaction(path) as c:
        r=c.execute('SELECT balance,reserve_b,decision,permission_on,permission_epoch FROM contracts WHERE id=?',(cid,)).fetchone()
        if r is None:raise KeyError(cid)
        bal,need,decision,permission,epoch=r
        accepted=bool(permission and decision=='PENDING' and bal-cost>=need)
        if accepted:
            c.execute('INSERT INTO scheduled_jobs(id,contract_id,cost,due_ns,admitted_epoch,policy) VALUES (?,?,?,?,?,?)',
                      (jid,cid,cost,due_ns,epoch,policy))
        emit(c,cid,'SCHEDULE',{'job_id':jid,'accepted':accepted,'cost':cost,'policy':policy,'due_ns':due_ns},jid)
        return accepted

def revoke(path,cid):
    with transaction(path) as c:
        row=c.execute('SELECT permission_epoch FROM contracts WHERE id=?',(cid,)).fetchone()
        if row is None:raise KeyError(cid)
        c.execute('UPDATE contracts SET permission_on=0,permission_epoch=permission_epoch+1 WHERE id=?',(cid,))
        emit(c,cid,'REVOKE',{'new_epoch':row[0]+1})
    return row[0]+1

def choose_b(path,cid):
    with transaction(path) as c:
        r=c.execute('SELECT balance,reserve_b,decision FROM contracts WHERE id=?',(cid,)).fetchone()
        if r is None:raise KeyError(cid)
        bal,need,decision=r
        good=decision=='PENDING' and bal>=need
        if good: c.execute('UPDATE contracts SET decision=? WHERE id=?',('B',cid))
        emit(c,cid,'HUMAN_CHOICE_B',{'accepted':good,'balance':bal,'need':need})
        return good

def fulfill_b(path,cid):
    with transaction(path) as c:
        r=c.execute('SELECT balance,reserve_b,decision FROM contracts WHERE id=?',(cid,)).fetchone()
        if r is None:raise KeyError(cid)
        bal,need,choice=r
        if choice!='B':raise ValueError('human has not selected B')
        success=bal>=need
        c.execute('UPDATE contracts SET balance=?,decision=? WHERE id=?',
                  (bal-need if success else bal, 'FULFILLED' if success else 'BROKEN',cid))
        emit(c,cid,'FULFILL_B',{'success':success,'balance':bal,'required':need})
        return success

def run_job(path,jid,now_ns=None,crash=None):
    """Dispatch-time gate and effect are within same SQLite write transaction.

    crash='before_commit' injects os._exit(78) after DB changes, before COMMIT;
    crash='after_commit' injects os._exit(79) after COMMIT, before CLI ACK.
    Call crashes ONLY from a child process.
    """
    if crash not in (None,'before_commit','after_commit'):raise ValueError(crash)
    if now_ns is None:now_ns=time.time_ns()
    c=connect(path)
    did_commit=False
    try:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('''SELECT j.contract_id,j.cost,j.due_ns,j.admitted_epoch,j.policy,j.status,
                            k.balance,k.reserve_b,k.decision,k.permission_on,k.permission_epoch
                            FROM scheduled_jobs j JOIN contracts k ON j.contract_id=k.id
                            WHERE j.id=?''',(jid,)).fetchone()
        if row is None:raise KeyError(jid)
        cid,cost,due,admit_epoch,policy,status,bal,need,choice,permission,epoch=row
        if status!='SCHEDULED':
            c.execute('COMMIT');did_commit=True
            return {'job':jid,'status':status,'effect':False,'reason':'ALREADY_TERMINAL'}
        if due>now_ns:
            c.execute('COMMIT');did_commit=True
            return {'job':jid,'status':status,'effect':False,'reason':'NOT_DUE'}
        # Admission-only models stale authorization: it rechecks only affordability.
        # Dispatch_guard and global_equivalent enforce the same strong invariant.
        if cost>bal: reason='INSUFFICIENT_BALANCE'
        elif policy=='admission_only': reason='APPROVED_AT_ADMISSION'
        elif epoch!=admit_epoch or not permission:reason='REVOKED_OR_STALE_EPOCH'
        elif choice!='PENDING':reason='HUMAN_ALREADY_DECIDED'
        elif bal-cost<need:reason='RESERVED_CHOICE_WOULD_BE_LOST'
        else:reason='DISPATCH_GUARD_PASSED'
        allow=reason in ('APPROVED_AT_ADMISSION','DISPATCH_GUARD_PASSED')
        if allow:c.execute('UPDATE contracts SET balance=? WHERE id=?',(bal-cost,cid))
        c.execute('UPDATE scheduled_jobs SET status=?,result=?,execution_count=execution_count+? WHERE id=?',
                  ('EXECUTED' if allow else 'DENIED',reason,1 if allow else 0,jid))
        emit(c,cid,'DISPATCH',{'job':jid,'effect':allow,'reason':reason,'before':bal,
                              'after':bal-cost if allow else bal,'decision_at_dispatch':choice,
                              'epoch':epoch,'admitted_epoch':admit_epoch},jid)
        if crash=='before_commit':os._exit(78)
        c.execute('COMMIT');did_commit=True
        if crash=='after_commit':os._exit(79)
        return {'job':jid,'status':'EXECUTED' if allow else 'DENIED','effect':allow,'reason':reason}
    except BaseException:
        if c.in_transaction: c.execute('ROLLBACK')
        raise
    finally:
        c.close()

def due_jobs(path,now_ns=None):
    if now_ns is None: now_ns=time.time_ns()
    with closing(connect(path)) as c:
        return [r[0] for r in c.execute('SELECT id FROM scheduled_jobs WHERE status=? AND due_ns<=? ORDER BY due_ns,id',('SCHEDULED',now_ns))]

def dispatch_due(path,now_ns=None):
    return [run_job(path,jid,now_ns=now_ns) for jid in due_jobs(path,now_ns)]

def run_worker(path,max_wait_ms=1500,poll_ms=10,crash=None):
    """A persistent real-time SQLite-backed local timer process.
    The queue survives worker termination. For bounded tests, the poller exits
    at its deadline. This is NOT APScheduler, cron, or a distributed queue.
    """
    positive_int(max_wait_ms);positive_int(poll_ms)
    if poll_ms==0:raise ValueError('poll_ms must be positive')
    until=time.monotonic()+max_wait_ms/1000
    results=[]
    while True:
        for jid in due_jobs(path):results.append(run_job(path,jid,crash=crash))
        if time.monotonic()>=until:break
        time.sleep(min(poll_ms/1000,max(0,until-time.monotonic())))
    return results

def log_for(path,cid):
    with closing(connect(path)) as c:
        return [{'kind':kind,'job':jobid,'detail':json.loads(s)} for kind,jobid,s in
                c.execute('SELECT kind,job_id,detail FROM log WHERE contract_id=? ORDER BY id',(cid,))]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('db'); s=p.add_subparsers(dest='op',required=True)
    s.add_parser('init'); a=s.add_parser('create');a.add_argument('case');a.add_argument('balance',type=int);a.add_argument('reserve',type=int)
    a=s.add_parser('enqueue');a.add_argument('case');a.add_argument('job');a.add_argument('cost',type=int);a.add_argument('delay_ms',type=int);a.add_argument('--policy',choices=POLICIES,default='dispatch_guard')
    a=s.add_parser('interim');a.add_argument('case');a.add_argument('cost',type=int)
    for x in ('revoke','choose-b','fulfill-b','status'):a=s.add_parser(x);a.add_argument('case')
    a=s.add_parser('job');a.add_argument('job')
    a=s.add_parser('run-one');a.add_argument('job');a.add_argument('--crash',choices=('before_commit','after_commit'))
    a=s.add_parser('worker');a.add_argument('--max-wait-ms',type=int,default=1500);a.add_argument('--poll-ms',type=int,default=10);a.add_argument('--crash',choices=('before_commit','after_commit'))
    a=s.add_parser('log');a.add_argument('case')
    a=p.parse_args()
    if a.op=='init':initialize(a.db);result={'created':a.db}
    elif a.op=='create':result=create_contract(a.db,a.case,a.balance,a.reserve) or contract(a.db,a.case)
    elif a.op=='enqueue':result={'accepted':schedule(a.db,a.case,a.job,a.cost,a.delay_ms,a.policy)}
    elif a.op=='interim':result={'allowed':reserve_preparation(a.db,a.case,a.cost)}
    elif a.op=='revoke':result={'epoch':revoke(a.db,a.case)}
    elif a.op=='choose-b':result={'accepted':choose_b(a.db,a.case)}
    elif a.op=='fulfill-b':result={'success':fulfill_b(a.db,a.case)}
    elif a.op=='status':result=contract(a.db,a.case)
    elif a.op=='job':result=job(a.db,a.job)
    elif a.op=='run-one':result=run_job(a.db,a.job,crash=a.crash)
    elif a.op=='worker':result=run_worker(a.db,a.max_wait_ms,a.poll_ms,a.crash)
    elif a.op=='log':result=log_for(a.db,a.case)
    print(json.dumps(result,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
