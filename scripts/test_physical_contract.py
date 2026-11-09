"""Source-neutral physical contracts, using byte fixtures rather than private media."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).with_name('physical_contract.py')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class SourceNeutralPhysicalTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('physical_contract', RUNTIME)
        self.pc = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.pc)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'source.mp4').write_bytes(b'new-source-fixture')
        self.sha = hashlib.sha256(b'new-source-fixture').hexdigest()
        self.source = {'source': {'path': 'source.mp4', 'sha256': self.sha}, 'video': {'frame_count': 3}}
        write(self.root / 'source.json', self.source)
        self.window = {'window_id': 'one', 'source_interval': [0, 3]}
        write(self.root / 'plan.json', {'windows': [self.window]})
        write(self.root / 'job.json', {})
        self.facts = {'schema_version': 1, 'source_sha256': self.sha, 'frame_count': 3,
                      'products': {'new-box': {'source_interval': [0, 3], 'panels': {'lid': 'Observed lid'},
                                               'hinges': ['Observed connected hinge']}}, 'rules': []}

    def facts_at(self, relative='assets/evidence/physical-source.json'):
        path = self.root / relative; write(path, self.facts); return path

    def test_no_matching_facts_means_no_physical_feature_or_contract(self):
        self.assertFalse(self.pc.enabled(self.root))
        self.assertIsNone(self.pc.init_run(self.root))
        self.assertFalse((self.root / 'production-contract.json').exists())

    def test_arbitrary_source_hash_enables_run_owned_evidence(self):
        self.facts_at()
        self.assertTrue(self.pc.enabled(self.root))
        contract = self.pc.init_run(self.root)
        self.assertEqual(self.sha, contract['source_sha256'])
        self.assertEqual(['new-box'], list(contract['products']))
        self.assertEqual([], contract['products']['new-box']['references'])
        current = self.pc.window_contract(self.root, self.window, {})
        self.assertEqual(self.sha, current['source_sha256'])
        self.assertEqual(3, current['products']['new-box']['source_geometry']['source_interval'][1])

    def test_evidence_directory_fallback_reads_current_source_facts(self):
        path = self.facts_at('evidence/physical-source.json')
        self.assertEqual(path, self.pc.current_evidence(self.root))
        self.pc.init_run(self.root)
        self.assertIn('new-box', self.pc.window_contract(self.root, self.window, {})['products'])

    def test_stale_fact_metadata_is_rejected_instead_of_silently_dropping_gates(self):
        self.facts['source_sha256'] = hashlib.sha256(b'other-source').hexdigest(); self.facts_at()
        with self.assertRaises(ValueError): self.pc.enabled(self.root)

    def test_changed_source_bytes_cannot_bypass_current_fact_contract(self):
        self.facts_at(); self.pc.init_run(self.root)
        (self.root / 'source.mp4').write_bytes(b'changed-current-source')
        with self.assertRaises(ValueError): self.pc.window_contract(self.root, self.window, {})

    def test_final_count_comes_from_current_evidence_instead_of_fixed_source(self):
        self.facts_at(); self.pc.init_run(self.root)
        (self.root / 'final.mp4').write_bytes(b'final-three-frames')
        sig = self.pc._signature(self.root, 'final.mp4')
        record = {'output_path': 'final.mp4', 'file_signature': sig, 'composition_digest': 'current',
                  'physical': {'status': 'passed', 'file_signature': sig, 'composition_digest': 'current',
                               'observations': {key: 'Actually observed ' + key for key in self.pc.CRITERIA},
                               'playback': {'status': 'observed', 'method': 'continuous-playback', 'speed': 1,
                                            'intervals': [[0, 3]], 'notes': 'Actually watched all three frames'}}}
        self.pc.final_guard(self.root, record)
        self.source['video']['frame_count'] = 4; write(self.root / 'source.json', self.source)
        with self.assertRaises(ValueError): self.pc.final_guard(self.root, record)

    def test_contract_from_another_source_is_not_reused(self):
        self.facts_at(); self.pc.init_run(self.root)
        path = self.root / 'production-contract.json'; contract = json.loads(path.read_text())
        contract['source_sha256'] = 'previous-source'; write(path, contract)
        with self.assertRaises(ValueError): self.pc.window_contract(self.root, self.window, {})


if __name__ == '__main__': unittest.main()
