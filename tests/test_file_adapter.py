import subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import scheduler_rights as s
import file_adapter as f
class TestFileEffect(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'db.sqlite';self.out=Path(self.tmp.name)/'output'
        s.initialize(self.db);s.create_contract(self.db,'c',10,6)
        self.assertTrue(s.schedule(self.db,'c','j',3,due_ns=0))
    def child(self,crash):
        return subprocess.run([sys.executable,str(ROOT/'file_adapter.py'),str(self.db),'j',str(self.out),'--crash',crash],
                              capture_output=True,text=True,timeout=10)
    def test_revoked_no_file(self):
        s.revoke(self.db,'c')
        r=f.dispatch_file(self.db,'j',self.out,b'offline-message')
        self.assertEqual(r['job_status'],'DENIED')
        self.assertFalse(f.path_for(self.out,'j').exists())
    def test_db_committed_file_missing_is_unknown(self):
        self.assertEqual(self.child('after_db_before_file').returncode,82)
        self.assertEqual(s.job(self.db,'j')['status'],'EXECUTED')
        self.assertEqual(f.observe(self.out,'j',b'offline-message')['local_file'],'UNKNOWN')
    def test_file_written_ack_lost_locally_verifiable(self):
        self.assertEqual(self.child('after_file_before_ack').returncode,83)
        self.assertEqual(s.job(self.db,'j')['status'],'EXECUTED')
        self.assertEqual(f.observe(self.out,'j',b'offline-message')['local_file'],'VERIFIED_LOCAL_BYTES')
    def test_tampered_file_unknown(self):
        r=f.dispatch_file(self.db,'j',self.out,b'offline-message')
        self.assertEqual(r['local_file'],'VERIFIED_LOCAL_BYTES')
        f.path_for(self.out,'j').write_bytes(b'altered')
        self.assertEqual(f.observe(self.out,'j',b'offline-message')['local_file'],'UNKNOWN')
if __name__=='__main__':unittest.main()
