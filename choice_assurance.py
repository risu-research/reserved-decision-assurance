"""Human-Empowerment-oriented offline assurance profile v0.5.

Everything is local. A trusted caller supplies a versioned, normative decision
contract; the SQLite dispatcher is the mandatory enforcement path for the demo.
Receipts are independently RECOMPUTABLE snapshots, not signed attestations.
"""
from __future__ import annotations
import argparse, hashlib, json, os, time, tempfile, sqlite3
from pathlib import Path
from contextlib import closing
import scheduler_rights as s
from audit import audit_contract
from file_adapter import path_for

PROFILE='reserved-decision-assurance/0.5'
BASES={'DELEGABLE','INSTRUMENTAL','INTRINSIC','IRREVERSIBLE'}
KINDS={'SQL_ONLY','LOCAL_FILE'}

def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=True,separators=(',',':')).encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def spec_for(cid,jid,basis='INSTRUMENTAL',kind='SQL_ONLY',expected_sha256=None):
    spec={'schema':PROFILE,'contract_id':cid,'job_id':jid,'human_right_basis':basis,
          'effect_kind':kind,'expected_sha256':expected_sha256,
          'authority_source':'LOCAL_SQLITE_CONTRACT',
          'claim_boundary':['SQLITE_JOB_TRANSITION','LOCAL_FILE_BYTES' if kind=='LOCAL_FILE' else 'SQLITE_BALANCE'],
          'out_of_scope':['REAL_WORLD_AGENT_SAFETY','EXTERNAL_DELIVERY','LEGAL_VALIDITY','ACTUAL_HUMAN_COMPREHENSION']}
    validate(spec)
    return spec

def validate(spec):
    if not isinstance(spec,dict) or spec.get('schema')!=PROFILE:raise ValueError('wrong schema')
    s.text_id(spec['contract_id']);s.text_id(spec['job_id'])
    if spec['human_right_basis'] not in BASES or spec['effect_kind'] not in KINDS:raise ValueError('unknown mode')
    h=spec['expected_sha256']
    if spec['effect_kind']=='LOCAL_FILE' and (not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h)):raise ValueError('expected payload digest required')
    if spec['effect_kind']=='SQL_ONLY' and h is not None:raise ValueError('digest only for files')
    if spec['authority_source']!='LOCAL_SQLITE_CONTRACT':raise ValueError('unknown source')
    return True

def _decide(bal,need,decision,permission,epoch,admit_epoch,cost,status,basis,now_ns,due_ns,approved=False):
    if status!='SCHEDULED':return ('DENY','JOB_NOT_PENDING')
    if due_ns>now_ns:return ('WAIT','NOT_DUE')
    if not permission or epoch!=admit_epoch:return ('DENY','REVOKED_OR_STALE_AUTHORITY')
    if decision!='PENDING':return ('DENY','HUMAN_ALREADY_DECIDED')
    if cost>bal:return ('DENY','INSUFFICIENT_RESOURCES')
    # This normative basis is GIVEN by an external human/policy authority, not inferred.
    if bal-cost<need:return ('HOLD_FOR_HUMAN','CHOICE_WOULD_BECOME_INFEASIBLE')
    if basis in ('INTRINSIC','IRREVERSIBLE') and not approved:
        return ('HOLD_FOR_HUMAN','HUMAN_RETAINED_DECISION')
    return ('DELEGATE','RESERVED_CHOICE_PRESERVED' if need else 'NO_RESERVED_CHOICE')

SPEC_TABLE="""
CREATE TABLE IF NOT EXISTS bound_rights_specs (
 job_id TEXT PRIMARY KEY REFERENCES scheduled_jobs(id),
 contract_id TEXT NOT NULL,
 spec_json TEXT NOT NULL,
 spec_sha256 TEXT NOT NULL
);
"""

APPROVAL_TABLE="""
CREATE TABLE IF NOT EXISTS local_signoffs (
 job_id TEXT PRIMARY KEY REFERENCES scheduled_jobs(id),
 authority_epoch INTEGER NOT NULL,
 source TEXT NOT NULL CHECK(source='SIMULATED_HUMAN_TEST_CONTROLLER')
);
"""

def schedule_assured(db,spec,cost,due_ns=0):
    """Atomically admit a job AND pin the source-of-authority contract profile.

    Trust assumption: caller is the human/policy authority, not an unauthenticated
    model. Real identity verification and digital signature are out of scope.
    """
    validate(spec);s.positive_int(cost)
    with closing(s.connect(db)) as conn:conn.executescript(SPEC_TABLE+APPROVAL_TABLE)
    with s.transaction(db) as c:
        cid=spec['contract_id'];jid=spec['job_id']
        row=c.execute('SELECT balance,reserve_b,decision,permission_on,permission_epoch FROM contracts WHERE id=?',(cid,)).fetchone()
        if row is None:raise KeyError(cid)
        bal,need,choice,permitted,epoch=row
        if spec['human_right_basis']=='DELEGABLE' and need!=0:raise ValueError('delegable job cannot erase an existing reserved B right')
        accepted=bool(permitted and choice=='PENDING' and bal-cost>=need)
        if not accepted:return False
        c.execute('INSERT INTO scheduled_jobs(id,contract_id,cost,due_ns,admitted_epoch,policy) VALUES (?,?,?,?,?,?)',(jid,cid,cost,due_ns,epoch,'dispatch_guard'))
        c.execute('INSERT INTO bound_rights_specs(job_id,contract_id,spec_json,spec_sha256) VALUES (?,?,?,?)',
                  (jid,cid,canonical(spec).decode(),digest(spec)))
        s.emit(c,cid,'SCHEDULE',{'job_id':jid,'accepted':True,'cost':cost,'policy':'dispatch_guard','due_ns':due_ns},jid)
        return True

def _bound(c,spec):
    row=c.execute('SELECT spec_json,spec_sha256,contract_id FROM bound_rights_specs WHERE job_id=?',(spec['job_id'],)).fetchone()
    if not row:return False
    data,hash_value,contract_id=row
    return contract_id==spec['contract_id'] and data==canonical(spec).decode() and hash_value==digest(spec)

def _approved(c,jid,epoch):
    row=c.execute('SELECT authority_epoch,source FROM local_signoffs WHERE job_id=?',(jid,)).fetchone()
    return bool(row and row[0]==epoch and row[1]=='SIMULATED_HUMAN_TEST_CONTROLLER')

def record_simulated_human_signoff(db,spec):
    # NOT identity authenticated. Local experimenter's action via trusted Python caller.
    validate(spec)
    if spec['human_right_basis'] not in ('INTRINSIC','IRREVERSIBLE'):raise ValueError('signoff not needed')
    with s.transaction(db) as c:
        if not _bound(c,spec):raise ValueError('unbound contract')
        row=c.execute('SELECT j.cost,j.admitted_epoch,j.status,k.balance,k.reserve_b,k.decision,k.permission_on,k.permission_epoch FROM scheduled_jobs j JOIN contracts k ON j.contract_id=k.id WHERE j.id=?',(spec['job_id'],)).fetchone()
        cost,admit,status,bal,need,choice,permitted,epoch=row
        if status!='SCHEDULED' or not permitted or admit!=epoch or choice!='PENDING' or bal-cost<need:
            raise ValueError('no valid signoff for this current state')
        c.execute('INSERT OR REPLACE INTO local_signoffs(job_id,authority_epoch,source) VALUES (?,?,?)',
                  (spec['job_id'],epoch,'SIMULATED_HUMAN_TEST_CONTROLLER'))
        s.emit(c,spec['contract_id'],'HUMAN_SIGNOFF',{'job':spec['job_id'],'epoch':epoch,
             'source':'SIMULATED_HUMAN_TEST_CONTROLLER'},spec['job_id'])
        return {'recorded':True,'source':'SIMULATED_HUMAN_TEST_CONTROLLER','epoch':epoch}

def _is_bound(db,spec):
    try:
        with closing(s.connect(db)) as c:return _bound(c,spec)
    except sqlite3.OperationalError:return False

def preflight(db,spec,now_ns=None):
    """Diagnostic only. Do NOT execute based on this: state can change afterwards."""
    validate(spec)
    if now_ns is None:now_ns=time.time_ns()
    if not _is_bound(db,spec):return {'decision':'UNKNOWN','reason':'UNBOUND_OR_CHANGED_SPEC','enforcement':'DIAGNOSTIC_ONLY'}
    j=s.job(db,spec['job_id'])
    if j['contract_id']!=spec['contract_id']:raise ValueError('job/contract mismatch')
    c=s.contract(db,spec['contract_id'])
    if not audit_contract(db,spec['contract_id'])['ok']:
        return {'decision':'UNKNOWN','reason':'LOCAL_LEDGER_MISMATCH','enforcement':'DIAGNOSTIC_ONLY'}
    with closing(s.connect(db)) as conn:approved=_approved(conn,spec['job_id'],c['permission_epoch'])
    decision,reason=_decide(c['balance'],c['reserve_b'],c['decision'],c['permission_on'],c['permission_epoch'],j['admitted_epoch'],j['cost'],j['status'],spec['human_right_basis'],now_ns,j['due_ns'],approved)
    return {'decision':decision,'reason':reason,'enforcement':'DIAGNOSTIC_ONLY','subject':spec['job_id']}

def assured_dispatch(db,spec,now_ns=None):
    """Fresh gate, decision, SQLite effect & log in one BEGIN IMMEDIATE transaction.

    HOLD does not consume the job; DENY is terminal; DELEGATE commits one DB debit.
    Complete mediation and a trusted contract source are assumptions.
    """
    validate(spec)
    if now_ns is None:now_ns=time.time_ns()
    with s.transaction(db) as c:
        if not _bound(c,spec):raise ValueError('unbound or altered human-right contract')
        row=c.execute('''SELECT j.contract_id,j.cost,j.due_ns,j.admitted_epoch,j.status,
                     k.balance,k.reserve_b,k.decision,k.permission_on,k.permission_epoch
                     FROM scheduled_jobs j JOIN contracts k ON k.id=j.contract_id
                     WHERE j.id=?''',(spec['job_id'],)).fetchone()
        if row is None:raise KeyError(spec['job_id'])
        cid,cost,due,admit_epoch,status,bal,need,choice,permission,epoch=row
        if cid!=spec['contract_id']:raise ValueError('job/contract mismatch')
        approved=_approved(c,spec['job_id'],epoch)
        decision,reason=_decide(bal,need,choice,permission,epoch,admit_epoch,cost,status,spec['human_right_basis'],now_ns,due,approved)
        if decision in ('HOLD_FOR_HUMAN','WAIT'):
            s.emit(c,cid,'ASSURANCE_HOLD',{'job':spec['job_id'],'reason':reason,'basis':spec['human_right_basis']},spec['job_id'])
        elif decision=='DENY' and status=='SCHEDULED':
            c.execute('UPDATE scheduled_jobs SET status=?,result=? WHERE id=?',('DENIED',reason,spec['job_id']))
            s.emit(c,cid,'DISPATCH',{'job':spec['job_id'],'effect':False,'reason':reason,'before':bal,
                  'after':bal,'decision_at_dispatch':choice,'epoch':epoch,'admitted_epoch':admit_epoch},spec['job_id'])
        elif decision=='DELEGATE':
            c.execute('UPDATE contracts SET balance=? WHERE id=?',(bal-cost,cid))
            c.execute('UPDATE scheduled_jobs SET status=?,result=?,execution_count=execution_count+1 WHERE id=?',('EXECUTED','ASSURANCE_ALLOWED',spec['job_id']))
            s.emit(c,cid,'DISPATCH',{'job':spec['job_id'],'effect':True,'reason':'ASSURANCE_ALLOWED',
                 'before':bal,'after':bal-cost,'decision_at_dispatch':choice,
                 'epoch':epoch,'admitted_epoch':admit_epoch,
                 'human_signoff_recorded':approved},spec['job_id'])
        return {'decision':decision,'reason':reason,'db_effect':decision=='DELEGATE',
                'enforcement':'SAME_SQLITE_WRITE_TRANSACTION','subject':spec['job_id']}

def publish_local_bytes(folder,jid,payload):
    """Explicit filesystem effect. Not atomic with SQL; only call on EXECUTED jobs.
    Caller must use trusted expected payload and only local test paths.
    """
    if not isinstance(payload,bytes):raise ValueError('payload must be bytes')
    target=path_for(folder,jid)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,p=tempfile.mkstemp(dir=target.parent,prefix='.staged-')
    try:
        with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(p,target)
        if os.name=='posix':
            fd=os.open(target.parent,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:
        if os.path.exists(p):os.unlink(p)
    return str(target)

def _snapshot(db,cid,jid):
    with closing(s.connect(db)) as c:
        c.execute('BEGIN')
        record=c.execute('SELECT balance,reserve_b,decision,permission_on,permission_epoch FROM contracts WHERE id=?',(cid,)).fetchone()
        job=c.execute('''SELECT contract_id,cost,due_ns,admitted_epoch,policy,status,result,execution_count
                         FROM scheduled_jobs WHERE id=?''',(jid,)).fetchone()
        rows=c.execute('SELECT id,kind,job_id,detail FROM log WHERE contract_id=? ORDER BY id',(cid,)).fetchall()
        c.execute('COMMIT')
    if not record or not job:raise KeyError((cid,jid))
    return {'contract':dict(zip(('balance','reserve_b','decision','permission_on','permission_epoch'),record)),
            'job':dict(zip(('contract_id','cost','due_ns','admitted_epoch','policy','status','result','execution_count'),job)),
            'events':[{'id':i,'kind':kind,'job':jobid,'detail':json.loads(detail)} for i,kind,jobid,detail in rows]}

def _claims(db,spec,outdir):
    x=_snapshot(db,spec['contract_id'],spec['job_id']); c=x['contract'];j=x['job']
    if j['contract_id']!=spec['contract_id']:raise ValueError('contract mismatch')
    ledger=audit_contract(db,spec['contract_id'])
    bound=_is_bound(db,spec)
    dispatch=[e for e in x['events'] if e['kind']=='DISPATCH' and e['job']==spec['job_id']]
    d=dispatch[-1]['detail'] if dispatch else None
    if not ledger['ok'] or not bound:
        auth='UNKNOWN_LEDGER_INCONSISTENT';db_effect='UNKNOWN_LEDGER_INCONSISTENT';right='UNKNOWN_LEDGER_INCONSISTENT'
    else:
        if j['status']=='EXECUTED' and d and d['effect']:
            auth=('VALID_AT_DISPATCH' if d['epoch']==d['admitted_epoch'] and d['decision_at_dispatch']=='PENDING' else 'INVALID_AT_DISPATCH')
            right=('PRESERVED_AT_DISPATCH' if d['after']>=c['reserve_b'] and d['decision_at_dispatch']=='PENDING' else 'LOST_AT_DISPATCH')
            db_effect='VERIFIED_SQLITE_TRANSITION'
        elif j['status']=='DENIED':auth='NOT_AUTHORIZED_FOR_EXECUTION';right='NO_DB_EFFECT_RECORDED';db_effect='NO_DB_EFFECT_RECORDED'
        else:auth='NOT_YET_EXECUTED';right='NOT_YET_EXECUTED';db_effect='NO_DB_EFFECT_RECORDED'
    # Rights basis is a claim BY the contract author, not validated by these runtime observations.
    if spec['effect_kind']=='LOCAL_FILE':
        if outdir is None:local_effect='NOT_OBSERVED'
        else:
            path=path_for(outdir,spec['job_id'])
            if not path.is_file():local_effect='UNKNOWN_FILE_ABSENT'
            else:
                found=hashlib.sha256(path.read_bytes()).hexdigest()
                local_effect='VERIFIED_LOCAL_BYTES' if found==spec['expected_sha256'] else 'CONTRADICTED_FILE_CONTENT'
    else:local_effect='NOT_APPLICABLE'
    return {'normative_basis':spec['human_right_basis'],
            'local_human_signoff_record':('RECORDED_TEST_CONTROLLER' if d and d.get('human_signoff_recorded') else 'NOT_RECORDED'),
            'authority_at_dispatch':auth,
            'reserved_choice_at_dispatch':right,
            'sqlite_effect':db_effect,
            'local_file_effect':local_effect,
            'external_delivery':'OUT_OF_SCOPE',
            'actual_human_understanding':'OUT_OF_SCOPE',
            'trusted_local_ledger':ledger['ok'] and bound},x

def make_receipt(db,spec,outdir=None):
    validate(spec)
    claims,snapshot=_claims(db,spec,outdir)
    obj={'profile':PROFILE,'spec':spec,'subject':spec['job_id'],'claims':claims,
         'evidence':{'sqlite_snapshot_sha256':digest(snapshot),'observation_sources':['LOCAL_SQLITE','LOCAL_FILESYSTEM' if outdir is not None else 'NO_FILESYSTEM_OBSERVATION']},
         'scope_note':'Recomputed local observation, not a signature, external receipt, or legal endorsement.'}
    obj['receipt_sha256']=digest(obj)
    return obj

def verify_receipt(db,receipt,outdir=None):
    """Recheck against *current* local evidence, not just the self-hash."""
    try:
        expected=make_receipt(db,receipt['spec'],outdir)
        return {'valid_for_current_local_observation':expected==receipt,
                'reason':'RECOMPUTED_MATCH' if expected==receipt else 'STALE_TAMPERED_OR_DIFFERENT_EVIDENCE'}
    except (KeyError,ValueError,TypeError,IndexError):return {'valid_for_current_local_observation':False,'reason':'MALFORMED_OR_UNAVAILABLE'}

def main():
    p=argparse.ArgumentParser();p.add_argument('db');p.add_argument('contract');p.add_argument('job');
    p.add_argument('--basis',choices=sorted(BASES),default='INSTRUMENTAL')
    p.add_argument('--effect',choices=sorted(KINDS),default='SQL_ONLY')
    p.add_argument('--sha256');p.add_argument('--outdir');p.add_argument('--op',choices=('preflight','dispatch','receipt'),default='receipt')
    a=p.parse_args(); spec=spec_for(a.contract,a.job,a.basis,a.effect,a.sha256)
    v=preflight(a.db,spec) if a.op=='preflight' else assured_dispatch(a.db,spec) if a.op=='dispatch' else make_receipt(a.db,spec,a.outdir)
    print(json.dumps(v,indent=2))
if __name__=='__main__':main()
