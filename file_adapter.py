"""Deliberately non-transactional scheduled local-file effect adapter.

Shows that SQLite execution status is NOT proof that a separate filesystem
publication happened. Simple file evidence; not external delivery or production.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from scheduler_rights import run_job,job

def path_for(outdir,jid):
    if not jid or not all(c.isalnum() or c in '_-' for c in jid):raise ValueError('invalid job ID')
    return Path(outdir)/(jid+'.txt')

def observe(outdir,jid,payload):
    target=path_for(outdir,jid)
    if not target.is_file():return {'local_file':'UNKNOWN','reason':'NO_FILE_EVIDENCE'}
    if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(payload).digest():
        return {'local_file':'UNKNOWN','reason':'CONTENT_MISMATCH'}
    return {'local_file':'VERIFIED_LOCAL_BYTES','reason':'HASH_MATCHES_TRUSTED_INPUT'}

def dispatch_file(db,jid,outdir,payload,crash=None):
    if crash not in (None,'after_db_before_file','after_file_before_ack'):raise ValueError(crash)
    if not isinstance(payload,bytes):raise ValueError('bytes expected')
    # SQL effect and filesystem effect are deliberately NOT atomic together.
    r=run_job(db,jid)
    if not r['effect']:
        if r['reason']=='ALREADY_TERMINAL':return dict(job_status=job(db,jid)['status'],**observe(outdir,jid,payload))
        return {'job_status':r['status'],'local_file':'NOT_ATTEMPTED','reason':r['reason']}
    if crash=='after_db_before_file':os._exit(82)
    target=path_for(outdir,jid)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=str(target.parent),prefix='.temp-')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(name,target)
        # fsync directory for POSIX durability when possible; not a guarantee across all filesystems.
        if os.name=='posix':
            folderfd=os.open(str(target.parent),os.O_RDONLY)
            try:os.fsync(folderfd)
            finally:os.close(folderfd)
    finally:
        if os.path.exists(name):os.unlink(name)
    if crash=='after_file_before_ack':os._exit(83)
    return dict(job_status='EXECUTED',**observe(outdir,jid,payload))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('db');p.add_argument('job');p.add_argument('outdir');
    p.add_argument('--payload',default='offline-message');p.add_argument('--crash',choices=('after_db_before_file','after_file_before_ack'))
    a=p.parse_args()
    print(json.dumps(dispatch_file(a.db,a.job,a.outdir,a.payload.encode(),a.crash),indent=2))
