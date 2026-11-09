"""Offline publication guard regressions; fixtures never contain real secrets."""
import hashlib, json, unittest, subprocess, tempfile, sys
from pathlib import Path
import verify_publish as guard

def fixture():
    files={'SKILL.md':('---\nname: '+guard.EXPECTED_SKILL+'\n---\nBased on '+guard.UPSTREAM_REPO).encode(),
           'README.md':('Based on '+guard.UPSTREAM_REPO).encode(),
           'ORIGIN.md':('Based on '+guard.UPSTREAM_REPO).encode(),
           'meta.json':json.dumps({'name':guard.EXPECTED_SKILL,'version':'fixture'}).encode()}
    files['manifest.json']=json.dumps({'name':guard.EXPECTED_SKILL,'version':'fixture',
        'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}}).encode()
    files['publish-policy.json']=json.dumps({'skill':guard.EXPECTED_SKILL,'repository':guard.EXPECTED_REPO,
        'runtime_files':['SKILL.md','README.md','ORIGIN.md','meta.json','manifest.json'],
        'upstream':{'url':guard.UPSTREAM_REPO,'attribution_files':['README.md','SKILL.md','ORIGIN.md']},
        'repository_files':['publish-policy.json']}).encode()
    return files

class PublishGuard(unittest.TestCase):
    def test_new_user_repository_is_the_exact_allowed_publish_target(self):
        self.assertTrue(guard.remote_ok('https://github.com/ccofallen/video-replication-factory.git'))
        self.assertTrue(guard.remote_ok('git@github.com:ccofallen/video-replication-factory'))

    def test_original_upstream_is_attribution_only_not_a_push_target(self):
        self.assertFalse(guard.remote_ok('https://github.com/T8mars/video-replacement-skill-factory-T8'))

    def test_missing_attribution_is_blocked_even_with_current_manifest_hashes(self):
        files=fixture()
        policy=json.loads(files['publish-policy.json'])
        policy['upstream']={'url':'https://github.com/T8mars/video-replacement-skill-factory-T8',
            'attribution_files':['README.md','SKILL.md','ORIGIN.md']}
        files['publish-policy.json']=json.dumps(policy).encode()
        files['README.md']=b'Renamed project without source attribution'
        files['ORIGIN.md']=b'No upstream recorded'
        policy['runtime_files']+=['README.md','ORIGIN.md']
        files['publish-policy.json']=json.dumps(policy).encode()
        manifest=json.loads(files['manifest.json'])
        for name in ('README.md','ORIGIN.md'):manifest['files'][name]=hashlib.sha256(files[name]).hexdigest()
        files['manifest.json']=json.dumps(manifest).encode()
        self.assertTrue(any('upstream attribution' in item for item in guard.check_tree(files)))

    def test_clean_factory_passes(self):
        self.assertEqual(guard.check_tree(fixture()),[])
    def test_roadmap_any_case_and_directory_blocked(self):
        for name in ('ROADMAP.MD','roadmap.md','docs/RoAdMaP.Md'):
            self.assertTrue(guard.check_payload(name,b'planning'))
    def test_private_git_binary_and_live_ledger_sidecars_blocked(self):
        for name in ('.git/config','tools/ffmpeg.exe','lib/codec.dll','tasks.sqlite-wal','tasks.db-shm','local.pfx'):
            self.assertTrue(guard.check_payload(name,b'fixture'),name)
    def test_key_file_and_embedded_known_value_blocked(self):
        self.assertTrue(guard.check_payload('private/api_key.txt',b'fixture'))
        key=b'OFFLINE_ONLY_'+b'Q'*32
        errors=guard.check_payload('README.md',b'example '+key,[key])
        self.assertTrue(errors)
        self.assertNotIn(key.decode(),' '.join(errors))
    def test_token_assignment_is_detected_without_printing_value(self):
        value=b'Z'*32
        errors=guard.check_payload('README.md',b'api_key = "'+value+b'"')
        self.assertTrue(errors)
        self.assertNotIn(value.decode(),' '.join(errors))
    def test_other_skill_media_and_unknown_file_blocked(self):
        for name in ('r2va-video-fixture/SKILL.md','other/SKILL.md','assets/source.mp4'):
            self.assertTrue(guard.check_payload(name,b'fixture'))
        files=fixture();files['other-project.txt']=b'fixture'
        self.assertTrue(guard.check_tree(files))
    def test_changed_runtime_signature_blocked(self):
        files=fixture();files['SKILL.md']+=b'changed'
        self.assertTrue(guard.check_tree(files))
    def test_wrong_remote_and_identity_blocked(self):
        self.assertFalse(guard.remote_ok('https://github.com/T8mars/other-project'))
        self.assertTrue(guard.remote_ok(guard.EXPECTED_REPO+'.git'))
        files=fixture();files['SKILL.md']=b'name: unrelated-skill\n'
        self.assertTrue(guard.check_tree(files))

    def test_runtime_whitelist_requires_complete_manifest(self):
        files=fixture();policy=json.loads(files['publish-policy.json'])
        policy['runtime_files'].append('EXTRA.md');files['EXTRA.md']=b'public tool guidance'
        files['publish-policy.json']=json.dumps(policy).encode()
        self.assertTrue(any('coverage' in error for error in guard.check_tree(files)))

    def outgoing_fixture(self, forbidden_name, data):
        with tempfile.TemporaryDirectory(prefix='factory-publish-history-') as directory:
            root=Path(directory).resolve()
            def git(*args):
                result=subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True)
                return result.stdout.decode().strip()
            git('init','-b','main');git('config','user.name','Offline fixture');git('config','user.email','fixture@example.invalid')
            git('config','core.autocrlf','false');git('remote','add','origin',guard.EXPECTED_REPO+'.git')
            safe=fixture()
            for name,content in safe.items():(root/name).write_bytes(content)
            git('add','--',*safe);git('commit','-m','Safe base')
            base=git('rev-parse','HEAD');path=root/forbidden_name;path.parent.mkdir(parents=True,exist_ok=True)
            previous=path.read_bytes() if path.exists() else None
            path.write_bytes(data)
            git('add','--',forbidden_name);git('commit','-m','Forbidden intermediate fixture')
            if previous is None:path.unlink()
            else:path.write_bytes(previous)
            git('add','-u','--',forbidden_name);git('commit','-m','Clean final fixture')
            head=git('rev-parse','HEAD')
            # The final revision by itself is clean; the outgoing history is not.
            command=[sys.executable,'-B','-X','utf8',str(Path(guard.__file__).resolve())]
            final=subprocess.run([*command,'--revision','HEAD'],cwd=root,capture_output=True,text=True)
            self.assertEqual(final.returncode,0,final.stderr)
            pending=f'refs/heads/main {head} refs/heads/main {base}\n'
            result=subprocess.run([*command,'--pre-push','origin',guard.EXPECTED_REPO+'.git'],input=pending,
                cwd=root,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            return result.stderr

    def test_outgoing_history_rejects_removed_roadmap(self):
        error=self.outgoing_fixture('notes/RoAdMaP.Md',b'local planning fixture')
        self.assertIn('forbidden publication path',error)

    def test_outgoing_history_rejects_removed_credential_assignment(self):
        # Construct a fake value, never an actual user credential.
        value=b'OFFLINE_ONLY_'+b'Z'*32
        error=self.outgoing_fixture('README.md',b'api_key = "'+value+b'"')
        self.assertIn('possible credential',error);self.assertNotIn(value.decode(),error)

if __name__=='__main__':
    unittest.main(verbosity=2)
