"""Binding boundaries use tiny local source/runtime fixtures, never production calls."""
import hashlib
import importlib.util
import json
import tempfile
import shutil
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name('runtime_binding.py')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class RuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'runtime binding implementation missing')
        spec = importlib.util.spec_from_file_location('runtime_binding', MODULE)
        self.rb = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.rb)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.runtime = self.root / 'runtime'; self.project = self.root / 'run'
        self.project.mkdir(); (self.runtime / 'scripts').mkdir(parents=True)
        self.meta = {'name': 'fixture-skill', 'version': '5.0', 'runtime_version': '2',
                     'available_capabilities': list(self.rb.CAPABILITY_FILES)}
        write(self.runtime / 'meta.json', self.meta)
        for source in MODULE.parent.glob('*.py'):
            if not source.name.startswith('test_'): shutil.copy2(source, self.runtime / 'scripts' / source.name)
        (self.project / 'source.mp4').write_bytes(b'source-bytes')
        self.sha = hashlib.sha256(b'source-bytes').hexdigest()
        write(self.project / 'source.json', {'source': {'path': 'source.mp4', 'sha256': self.sha}})

    def bind(self): return self.rb.bind(self.project, self.runtime)

    def test_descriptor_hashes_production_scripts_but_not_test_or_review_progress(self):
        before = self.rb.descriptor(self.runtime)
        self.assertEqual('fixture-skill', before['skill_id'])
        self.assertEqual('5.0', before['factory_version'])
        self.assertIn('scoped-physical-contract', before['available_capabilities'])
        (self.runtime / 'scripts' / 'test_runtime.py').write_text('changed test')
        self.assertEqual(before['runtime_digest'], self.rb.descriptor(self.runtime)['runtime_digest'])
        with (self.runtime / 'scripts' / 'factory.py').open('a') as handle: handle.write('\n# changed production code bytes\n')
        self.assertNotEqual(before['runtime_digest'], self.rb.descriptor(self.runtime)['runtime_digest'])

    def test_bind_records_current_source_skill_actual_root_and_required_capabilities(self):
        self.meta['source_capabilities'] = ['conditional-production-policy']; write(self.runtime / 'meta.json', self.meta)
        binding = self.bind()
        self.assertEqual(self.sha, binding['source_sha256'])
        self.assertEqual(str(self.runtime.resolve()), binding['runtime_root'])
        self.assertIn('conditional-production-policy', binding['required_capabilities'])
        self.rb.guard(self.project, 'prepare', self.runtime)
        self.assertEqual(binding, json.loads((self.project / 'run-runtime.json').read_text()))

    def test_changed_production_bytes_block_each_new_operation_but_not_recovery(self):
        self.bind(); (self.runtime / 'scripts' / 'factory.py').write_text('new version')
        for operation in ('prepare', 'submit', 'review', 'assemble'):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                self.rb.guard(self.project, operation, self.runtime)
        for operation in ('diagnose', 'status', 'recover', 'query', 'download'):
            self.rb.guard(self.project, operation, self.runtime)

    def test_different_runtime_root_and_skill_cannot_silently_replace_binding(self):
        self.bind(); other = self.root / 'other'
        import shutil
        shutil.copytree(self.runtime, other)
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'submit', other)
        self.meta['name'] = 'wrong-skill'; write(self.runtime / 'meta.json', self.meta)
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'prepare', self.runtime)

    def test_changed_actual_source_and_source_metadata_both_block_mutation(self):
        self.bind(); (self.project / 'source.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'prepare', self.runtime)
        write(self.project / 'source.json', {'source': {'path': 'source.mp4', 'sha256': hashlib.sha256(b'changed').hexdigest()}})
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'prepare', self.runtime)

    def test_unbound_legacy_run_needs_explicit_adoption_for_new_operations(self):
        write(self.project / 'queue.json', {'jobs': [{'task_id': 'already-paid-id'}]})
        self.rb.guard(self.project, 'recover', self.runtime)
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'submit', self.runtime)
        with self.assertRaises(ValueError): self.bind()
        binding = self.rb.bind(self.project, self.runtime, adopt=True, source_message='user explicitly adopts current runtime')
        self.assertEqual('user explicitly adopts current runtime', binding['adoption']['source_message'])
        self.rb.guard(self.project, 'prepare', self.runtime)

    def test_unbound_even_simple_run_does_not_silently_authorize_prepare(self):
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'prepare', self.runtime)

    def test_capability_object_and_source_facts_infer_physical_requirement(self):
        self.meta['source_capabilities'] = {'required_capabilities': ['conditional-production-policy'],
            'files': ['assets/source-facts.json'], 'entrypoint': 'scripts/factory.py',
            'contract_initializer': 'scripts/physical_contract.py:init_run',
            'guards': ['scripts/physical_contract.py:input_guard']}
        write(self.runtime / 'meta.json', self.meta); write(self.runtime / 'assets/source-facts.json', {'source': 'facts'})
        write(self.project / 'assets/evidence/physical-source.json', {'source_sha256': self.sha})
        binding = self.bind()
        self.assertIn('scoped-physical-contract', binding['required_capabilities'])
        self.assertIn('conditional-production-policy', binding['required_capabilities'])
        (self.runtime / 'scripts/physical_contract.py').unlink()
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'prepare', self.runtime)

    def test_missing_declared_capability_or_extension_is_not_adopted(self):
        self.meta['source_capabilities'] = ['future-unknown-capability']; write(self.runtime / 'meta.json', self.meta)
        with self.assertRaises(ValueError): self.bind()
        self.meta['source_capabilities'] = {'required_capabilities': [], 'files': ['assets/missing.json']}
        write(self.runtime / 'meta.json', self.meta)
        with self.assertRaises(ValueError): self.bind()

    def test_stale_binding_rebind_requires_explicit_migration_and_preserves_history(self):
        self.bind()
        with (self.runtime / 'scripts/factory.py').open('a') as handle: handle.write('\n# updated runtime version\n')
        with self.assertRaises(ValueError): self.bind()
        changed = self.rb.bind(self.project, self.runtime, adopt=True, source_message='user migrates runtime')
        self.assertEqual(1, len(changed['history']))
        self.rb.guard(self.project, 'prepare', self.runtime)

    def test_dedicated_runtime_for_another_source_is_rejected(self):
        self.meta['source_sha256'] = hashlib.sha256(b'another source').hexdigest(); write(self.runtime / 'meta.json', self.meta)
        with self.assertRaises(ValueError): self.bind()

    def test_source_guard_descriptor_change_is_not_hidden_by_unchanged_provider_bytes(self):
        self.meta['source_capabilities'] = {'required_capabilities': [],
            'guards': ['scripts/physical_contract.py:input_guard']}
        write(self.runtime / 'meta.json', self.meta); self.bind()
        self.meta['source_capabilities']['guards'] = ['scripts/physical_contract.py:final_guard']
        write(self.runtime / 'meta.json', self.meta)
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'prepare', self.runtime)

    def test_files_without_explicit_declarations_do_not_advertise_capabilities(self):
        self.meta.pop('available_capabilities'); write(self.runtime / 'meta.json', self.meta)
        self.assertEqual([], self.rb.descriptor(self.runtime)['available_capabilities'])

    def test_print_only_providers_and_removed_consumer_hooks_do_not_claim_capability(self):
        self.meta['available_capabilities'] = ['scoped-physical-contract']; write(self.runtime / 'meta.json', self.meta)
        (self.runtime / 'scripts/physical_contract.py').write_text('print("no implementation")')
        with self.assertRaises(ValueError): self.rb.descriptor(self.runtime)
        shutil.copy2(MODULE.parent / 'physical_contract.py', self.runtime / 'scripts/physical_contract.py')
        factory = self.runtime / 'scripts/factory.py'
        factory.write_text(factory.read_text().replace('physical_contract.review_guard(', 'physical_contract.disabled_review('))
        with self.assertRaises(ValueError): self.rb.descriptor(self.runtime)

    def test_nonexistent_declared_guard_or_initializer_function_cannot_bind(self):
        for field, value in (('guards', ['scripts/physical_contract.py:missing_guard']),
                             ('contract_initializer', 'scripts/physical_contract.py:missing_init')):
            self.meta['source_capabilities'] = {'required_capabilities': ['scoped-physical-contract'], field: value}
            write(self.runtime / 'meta.json', self.meta)
            with self.subTest(field=field), self.assertRaises(ValueError): self.bind()

    def test_source_extension_bytes_are_bound_even_when_scripts_unchanged(self):
        self.meta['source_capabilities'] = {'required_capabilities': [], 'files': ['assets/contract.json']}
        write(self.runtime / 'meta.json', self.meta); write(self.runtime / 'assets/contract.json', {'panels': 2})
        self.bind(); write(self.runtime / 'assets/contract.json', {'panels': 3})
        with self.assertRaises(ValueError): self.rb.guard(self.project, 'prepare', self.runtime)


if __name__ == '__main__': unittest.main()
