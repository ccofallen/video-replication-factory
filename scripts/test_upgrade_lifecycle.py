"""Revision allocation and source-extension preservation use local byte fixtures."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

try:
    import upgrade_lifecycle as lifecycle
except ModuleNotFoundError:
    lifecycle = None


class UpgradeLifecycle(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(lifecycle, 'Source-preserving upgrade lifecycle is missing')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sha = hashlib.sha256(b'first source').hexdigest()
        self.other_sha = hashlib.sha256(b'other source').hexdigest()
        self.slug = 'r2va-video-' + self.sha[:12]
        self.registry = {'schema_version': 1, 'sources': {}}

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def skill(self, revision=1, source=None, extra=None):
        name = self.slug + (f'-v{revision}' if revision > 1 else '')
        path = self.root / name; path.mkdir(exist_ok=True)
        self.write(path / 'manifest.json', {'name': name, 'source_sha256': source or self.sha,
                                            'status': 'draft', 'template_revision': revision,
                                            **(extra or {})})
        return path

    def evidence_skill(self, folder='old'):
        path = self.root / folder; path.mkdir()
        self.write(path / 'manifest.json', {'source_sha256': self.sha, 'source_capabilities': {
            'required_capabilities': ['source-guard'], 'files': ['scripts/source_entry.py'],
            'entrypoint': 'scripts/source_entry.py',
            'contract_initializer': 'scripts/source_entry.py:init_run',
            'guards': ['scripts/source_entry.py:guard']}})
        self.write(path / 'assets/evidence/physical-source.json', {'source_sha256': self.sha, 'products': {}})
        (path / 'scripts').mkdir()
        (path / 'scripts/source_entry.py').write_text('source-specific entry and guards')
        return path

    def test_first_revision_preserves_unsuffixed_legacy_slug_without_writing(self):
        root = self.root / 'missing-install-root'
        result = lifecycle.allocate_revision(root, self.sha, self.registry)
        self.assertEqual(result, {'name': self.slug, 'template_revision': 1})
        self.assertFalse(root.exists())
        self.assertEqual(self.registry, {'schema_version': 1, 'sources': {}})

    def test_deleted_highest_revision_in_history_and_tombstone_is_never_reused(self):
        self.registry['sources'][self.sha] = {'name': self.slug + '-v4', 'status': 'ready',
            'previous_versions': [self.slug, self.slug + '-v6'],
            'versions': [{'name': self.slug + '-v8', 'template_revision': 8}],
            'tombstones': [{'name': self.slug + '-v11', 'reason': 'User removed old install'}]}
        self.assertEqual(lifecycle.allocate_revision(self.root, self.sha, self.registry),
                         {'name': self.slug + '-v12', 'template_revision': 12})
        records = lifecycle.list_versions(self.root, self.sha, self.registry)
        self.assertEqual([r['template_revision'] for r in records], [1, 4, 6, 8, 11])
        self.assertTrue(records[-1]['removed'])
        self.assertFalse(records[-1]['installed'])

    def test_installed_orphan_versions_and_persisted_high_water_mark_are_included(self):
        self.skill(9)
        self.registry['sources'][self.sha] = {'name': self.slug + '-v3', 'max_revision': 15}
        self.assertEqual(lifecycle.allocate_revision(self.root, self.sha, self.registry)['template_revision'], 16)
        rows = lifecycle.list_versions(self.root, self.sha, self.registry)
        self.assertTrue(next(r for r in rows if r['template_revision'] == 9)['installed'])

    def test_global_source_scoped_history_and_removals_do_not_affect_other_source(self):
        self.registry.update(history=[{'source_sha256': self.sha, 'name': self.slug + '-v10'}],
            tombstones=[{'source_sha256': self.sha, 'name': self.slug + '-v12'},
                        {'source_sha256': self.other_sha, 'name': 'r2va-video-' + self.other_sha[:12] + '-v99'}])
        self.assertEqual(lifecycle.allocate_revision(self.root, self.sha, self.registry)['template_revision'], 13)

    def test_wrong_source_directory_cannot_claim_source_revision_or_be_overwritten(self):
        self.skill(1, source=self.other_sha)
        result = lifecycle.allocate_revision(self.root, self.sha, self.registry)
        self.assertEqual(result['name'], 'r2va-video-' + self.sha[:24])
        self.assertEqual(result['template_revision'], 1)

    def test_version_listing_reads_default_registry_without_mutating_it(self):
        self.registry['sources'][self.sha] = {'name': self.slug + '-v7', 'previous_versions': [self.slug]}
        path = self.root / '.video-factory-registry.json'; self.write(path, self.registry)
        before = path.read_bytes()
        rows = lifecycle.list_versions(self.root, self.sha)
        self.assertEqual([r['template_revision'] for r in rows], [1, 7])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_version_metadata_does_not_confuse_runtime_factory_and_template_versions(self):
        value = lifecycle.version_metadata('1.8.0', 5, 'current-runtime-sha',
                                             ['source-guard'], runtime_version='3')
        self.assertEqual(value['factory_version'], '1.8.0')
        self.assertEqual(value['template_revision'], 5)
        self.assertEqual(value['runtime_version'], '3')
        self.assertEqual(value['runtime_digest'], 'current-runtime-sha')
        with self.assertRaises(ValueError): lifecycle.version_metadata('1.8.0', 0, 'digest')

    def test_capability_lists_and_version_high_water_records_are_validated(self):
        with self.assertRaisesRegex(ValueError, 'capabilit'):
            lifecycle.version_metadata('1.8.0', 5, 'digest', 'not-a-list')
        self.registry['sources'][self.sha] = {'name': self.slug, 'max_revision': '5'}
        updated = lifecycle.record_version(self.registry, self.sha,
                     {'name': self.slug + '-v6', 'template_revision': 6, 'status': 'draft'})
        self.assertEqual(updated['sources'][self.sha]['max_revision'], 6)

    def test_recording_removal_keeps_revision_and_does_not_delete_installed_directory(self):
        skill = self.skill(6)
        self.registry['sources'][self.sha] = {'name': skill.name, 'status': 'ready', 'previous_versions': []}
        before = copy.deepcopy(self.registry)
        recorded = lifecycle.record_removal(self.registry, self.sha, skill.name, 'Requested retirement', removed_at='2026-11-09')
        self.assertEqual(self.registry, before)
        self.assertTrue(skill.exists())
        self.assertEqual(recorded['sources'][self.sha]['max_revision'], 6)
        self.assertEqual(lifecycle.allocate_revision(self.root, self.sha, recorded)['template_revision'], 7)
        self.assertEqual(recorded['sources'][self.sha]['tombstones'][0]['reason'], 'Requested retirement')

    def test_registering_new_version_preserves_history_and_replay_is_idempotent(self):
        self.registry['sources'][self.sha] = {'name': self.slug, 'status': 'draft', 'previous_versions': []}
        record = {'name': self.slug + '-v2', 'template_revision': 2, 'status': 'ready'}
        updated = lifecycle.record_version(self.registry, self.sha, record)
        self.assertEqual(updated['sources'][self.sha]['previous_versions'], [self.slug])
        self.assertEqual(lifecycle.record_version(updated, self.sha, record), updated)
        self.assertEqual(self.registry['sources'][self.sha]['name'], self.slug)
        with self.assertRaisesRegex(ValueError, 'revision|reuse'):
            lifecycle.record_version(updated, self.sha, {'name': self.slug, 'status': 'draft'})

    def test_source_contract_binds_evidence_extensions_and_capabilities(self):
        old = self.evidence_skill()
        contract = lifecycle.source_contract(old)
        self.assertEqual(contract['source_sha256'], self.sha)
        self.assertEqual(contract['required_capabilities'], ['scoped-physical-contract', 'source-guard'])
        self.assertEqual(contract['source_extensions']['scripts/source_entry.py'],
                         hashlib.sha256(b'source-specific entry and guards').hexdigest())
        self.assertIn('assets/evidence/physical-source.json', contract['source_evidence'])
        self.assertEqual(contract['source_capabilities']['entrypoint'], 'scripts/source_entry.py')

    def test_generic_guard_provider_may_upgrade_without_dropping_declared_guards(self):
        old = self.evidence_skill()
        value = json.loads((old / 'manifest.json').read_text())
        value['source_capabilities']['files'] = []
        self.write(old / 'manifest.json', value)
        contract = lifecycle.source_contract(old)
        self.assertEqual(contract['source_extensions'], {})
        (old / 'scripts/source_entry.py').write_text('upgraded generic guard provider')
        lifecycle.verify_source_contract(old, contract, ['scoped-physical-contract', 'source-guard'])
        value['source_capabilities'].pop('guards')
        self.write(old / 'manifest.json', value)
        with self.assertRaisesRegex(ValueError, 'source_capabilities'):
            lifecycle.verify_source_contract(old, contract, ['scoped-physical-contract', 'source-guard'])

    def test_equivalent_list_and_object_capabilities_upgrade_without_dropping_requirements(self):
        old = self.evidence_skill()
        value = json.loads((old / 'manifest.json').read_text())
        value['source_capabilities'] = ['source-guard']
        self.write(old / 'manifest.json', value)
        before = lifecycle.source_contract(old)
        value['source_capabilities'] = {'required_capabilities': ['source-guard'], 'files': []}
        self.write(old / 'manifest.json', value)
        lifecycle.verify_source_contract(old, before, ['scoped-physical-contract', 'source-guard'])
        object_before = lifecycle.source_contract(old)
        value['source_capabilities'] = ['source-guard']
        self.write(old / 'manifest.json', value)
        lifecycle.verify_source_contract(old, object_before, ['scoped-physical-contract', 'source-guard'])
        value['source_capabilities'] = []
        self.write(old / 'manifest.json', value)
        with self.assertRaisesRegex(ValueError, 'capabilit'):
            lifecycle.verify_source_contract(old, object_before, ['scoped-physical-contract', 'source-guard'])

    def test_upgrade_rejects_dropped_capability_changed_evidence_or_missing_extension(self):
        old = self.evidence_skill(); contract = lifecycle.source_contract(old)
        caps = ['scoped-physical-contract', 'source-guard']
        lifecycle.verify_source_contract(old, contract, caps)
        with self.assertRaisesRegex(ValueError, 'capabilit'):
            lifecycle.verify_source_contract(old, contract, ['source-guard'])
        evidence = old / 'assets/evidence/physical-source.json'; original = evidence.read_bytes()
        evidence.write_bytes(b'changed source facts')
        with self.assertRaisesRegex(ValueError, 'evidence|source'):
            lifecycle.verify_source_contract(old, contract, caps)
        evidence.write_bytes(original)
        (old / 'scripts/source_entry.py').unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            lifecycle.verify_source_contract(old, contract, caps)

    def test_source_extension_path_cannot_escape_candidate_package(self):
        old = self.evidence_skill()
        value = json.loads((old / 'manifest.json').read_text())
        value['source_capabilities']['files'] = ['../private.py']
        self.write(old / 'manifest.json', value)
        with self.assertRaisesRegex(ValueError, 'path|contained|relative'):
            lifecycle.source_contract(old)

    def test_source_capability_list_and_entry_descriptors_cannot_be_malformed(self):
        old = self.evidence_skill()
        value = json.loads((old / 'manifest.json').read_text())
        value['required_capabilities'] = 'scoped-physical-contract'
        self.write(old / 'manifest.json', value)
        with self.assertRaisesRegex(ValueError, 'capabilit'):
            lifecycle.source_contract(old)
        value.pop('required_capabilities')
        value['source_capabilities']['entrypoint'] = True
        self.write(old / 'manifest.json', value)
        with self.assertRaisesRegex(ValueError, 'entry|path'):
            lifecycle.source_contract(old)


if __name__ == '__main__': unittest.main(verbosity=2)
