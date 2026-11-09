"""Offline policy boundaries: real local bytes, no visual verdicts synthesized."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).with_name('production_policy.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


class ProductionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RUNTIME.is_file(), 'production policy implementation missing')
        spec = importlib.util.spec_from_file_location('production_policy', RUNTIME)
        self.p = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.p)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.a = {'window_id': 'a', 'source_interval': [0, 10], 'role_slots': ['A']}
        self.b = {'window_id': 'b', 'source_interval': [10, 20], 'role_slots': ['B']}
        write(self.root / 'plan.json', {'windows': [self.a, self.b]})
        for name in ('art.png', 'person.png', 'out.mp4'):
            (self.root / name).write_bytes(name.encode())
        self.policy = {'schema_version': 1, 'stages': [], 'artwork_masters': [], 'visible_identity': []}
        self.entry = {'window_id': 'a', 'input_digest': 'input-a'}

    def save(self):
        write(self.root / 'production-policy.json', self.policy)

    def stage(self):
        return {'id': 'art-preview', 'scope': {'window_ids': ['a']},
                'user_request': {'actor': 'user', 'source_message': 'user asks to review artwork first'},
                'assets': [{'path': 'art.png', 'sha256': sha(b'art.png')}],
                'approval': {'status': 'pending'}}

    def approve(self, stage, actor='user'):
        stage['approval'] = {'status': 'approved', 'actor': actor,
                             'source_message': 'current explicit approval',
                             'contract_digest': self.p.digest(self.p.stage_contract(self.root, stage))}

    def master(self):
        return {'id': 'label', 'path': 'art.png', 'sha256': sha(b'art.png'),
                'product': 'box', 'panel': 'lid', 'scope': {'window_ids': ['a']},
                'strictness': 'exact', 'source_message': 'user requires exact master',
                'characteristics': {'letters': 'red ABC'}, 'anchors': {'print': 'inside lid border'},
                'state_correspondences': {'folded': 'print stays on lid'}}

    def visible(self):
        return {'id': 'actor-a', 'role': 'A', 'scope': {'window_ids': ['a']},
                'references': [{'path': 'person.png', 'sha256': sha(b'person.png'),
                                'coverage': ['wrist', 'sleeve'],
                                'attributes': {'wrist': 'broad wrist', 'sleeve': 'checked cuff'}}],
                'source_visible_parts': ['wrist', 'sleeve']}

    def candidate(self):
        scope = self.p.scoped_contract(self.root, self.a)
        return {'output_path': 'out.mp4', 'input_digest': 'input-a',
                'policy': {'contract_digest': self.p.digest(scope), 'file_sha256': sha(b'out.mp4'),
                           'input_digest': 'input-a', 'artwork': {}, 'visible_identity': {}}}

    def test_absent_policy_is_legacy_noop_and_init_never_marks_passed(self):
        self.assertIsNone(self.p.scoped_contract(self.root, self.a))
        self.p.submission_guard(self.root, self.entry)
        self.p.candidate_guard(self.root, self.a, {}, self.entry)
        self.p.final_guard(self.root, {})
        self.p.init_run(self.root)
        state = json.loads((self.root / 'delivery_state.json').read_text())
        self.assertEqual('pending', state['user_acceptance']['status'])
        self.assertEqual([], state['known_issues'])
        self.assertIsNone(self.p.scoped_contract(self.root, self.a))

    def test_unused_stage_without_user_request_does_not_create_gate(self):
        unused = self.stage()
        unused.pop('user_request')
        self.policy['stages'] = [unused]
        self.save()
        self.p.submission_guard(self.root, self.entry)

    def test_requested_stage_blocks_partial_rejected_and_missing_approval(self):
        stage = self.stage()
        self.policy['stages'] = [stage]
        for status in ('pending', 'partial', 'rejected'):
            stage['approval'] = {'status': status}
            self.save()
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.p.submission_guard(self.root, self.entry)
        self.approve(stage)
        self.save()
        self.p.submission_guard(self.root, self.entry)

    def test_stage_approval_binds_actual_sha_scope_and_real_user_message(self):
        stage = self.stage()
        self.policy['stages'] = [stage]
        self.approve(stage)
        self.save()
        self.p.submission_guard(self.root, self.entry)
        for mutate in ('message', 'scope', 'bytes'):
            saved = copy.deepcopy(stage)
            if mutate == 'message': stage['approval']['source_message'] = ''
            if mutate == 'scope': stage['scope'] = {'window_ids': ['a', 'b']}
            if mutate == 'bytes': (self.root / 'art.png').write_bytes(b'changed')
            self.save()
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.p.submission_guard(self.root, self.entry)
            stage.clear(); stage.update(saved)
            (self.root / 'art.png').write_bytes(b'art.png')

    def test_codex_approval_requires_explicit_user_delegation_with_matching_scope(self):
        stage = self.stage(); self.policy['stages'] = [stage]
        self.approve(stage, 'codex'); self.save()
        with self.assertRaises(ValueError): self.p.submission_guard(self.root, self.entry)
        stage['approval']['delegation'] = {'actor': 'user', 'source_message': 'delegate art-preview a',
                                           'scope': {'window_ids': ['b']}, 'stage_ids': ['art-preview']}
        self.save()
        with self.assertRaises(ValueError): self.p.submission_guard(self.root, self.entry)
        stage['approval']['delegation']['scope'] = {'window_ids': ['a']}
        self.save(); self.p.submission_guard(self.root, self.entry)
        stage['approval']['delegation']['stage_ids'] = ['music-preview']; self.save()
        with self.assertRaises(ValueError): self.p.submission_guard(self.root, self.entry)

    def test_unrelated_stage_changes_do_not_invalidate_other_window_digest(self):
        stage = self.stage(); self.policy['stages'] = [stage]; self.save()
        before = self.p.scoped_contract(self.root, self.b)
        stage['assets'] = []; self.save()
        self.assertEqual(before, self.p.scoped_contract(self.root, self.b))
        self.p.submission_guard(self.root, {'window_id': 'b'})

    def test_product_scope_cannot_silently_disappear_without_product_window_mapping(self):
        stage = self.stage(); stage['scope'] = {'products': ['box']}
        self.policy['stages'] = [stage]; self.save()
        with self.assertRaises(ValueError): self.p.submission_guard(self.root, self.entry)
        self.a['products'] = ['box']; self.b['products'] = ['another']
        write(self.root / 'plan.json', {'windows': [self.a, self.b]})
        with self.assertRaises(ValueError): self.p.submission_guard(self.root, self.entry)
        self.p.submission_guard(self.root, {'window_id': 'b'})

    def test_artwork_missing_declared_features_is_a_validation_failure(self):
        master = self.master(); master.pop('anchors')
        self.policy['artwork_masters'] = [master]; self.save()
        with self.assertRaises(ValueError): self.p.scoped_contract(self.root, self.a)

    def test_visible_identity_contract_cannot_review_another_windows_role(self):
        self.policy['visible_identity'] = [self.visible()]; self.save()
        self.a['role_slots'] = ['B']
        with self.assertRaises(ValueError): self.p.scoped_contract(self.root, self.a)

    def test_approval_progress_does_not_invalidate_generation_contract(self):
        stage = self.stage(); self.policy['stages'] = [stage]; self.save()
        before = self.p.scoped_contract(self.root, self.a)
        self.approve(stage); self.save()
        self.assertEqual(before, self.p.scoped_contract(self.root, self.a))

    def test_artwork_and_identity_review_progress_do_not_invalidate_generation(self):
        master, visible = self.master(), self.visible()
        self.policy['artwork_masters'] = [master]; self.policy['visible_identity'] = [visible]; self.save()
        before = self.p.scoped_contract(self.root, self.a)
        master['review'] = {'status': 'failed', 'observations': 'new review progress'}
        visible['review'] = {'status': 'pending'}
        self.save()
        self.assertEqual(before, self.p.scoped_contract(self.root, self.a))

    def test_artwork_requires_actual_master_bytes_and_exact_declared_review(self):
        master = self.master(); self.policy['artwork_masters'] = [master]; self.save()
        record = self.candidate()
        with self.assertRaises(ValueError): self.p.candidate_guard(self.root, self.a, record, self.entry)
        observation = {'status': 'passed', 'strictness': 'exact', 'master_sha256': sha(b'art.png'),
                       'observations': {key: {k: 'Observed exact ' + v for k, v in master[key].items()}
                                        for key in ('characteristics', 'anchors', 'state_correspondences')}}
        record['policy']['artwork']['label'] = observation
        self.p.candidate_guard(self.root, self.a, record, self.entry)
        observation['strictness'] = 'approximate'
        with self.assertRaises(ValueError): self.p.candidate_guard(self.root, self.a, record, self.entry)
        observation['strictness'] = 'exact'; (self.root / 'art.png').write_bytes(b'new master')
        with self.assertRaises(ValueError): self.p.candidate_guard(self.root, self.a, record, self.entry)

    def test_artwork_pending_or_failed_is_not_promoted_by_record_fields(self):
        master = self.master(); self.policy['artwork_masters'] = [master]; self.save()
        for status in ('pending', 'failed'):
            record = self.candidate(); record['policy']['artwork']['label'] = {
                'status': status, 'strictness': 'exact', 'master_sha256': sha(b'art.png'),
                'observations': {key: {k: 'Observed unresolved distortion' for k in master[key]}
                                 for key in ('characteristics', 'anchors', 'state_correspondences')}}
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.p.candidate_guard(self.root, self.a, record, self.entry)

    def test_identity_reviews_use_current_attributes_and_visible_parts(self):
        visible = self.visible(); self.policy['visible_identity'] = [visible]; self.save()
        record = self.candidate()
        observation = {'status': 'passed', 'reference_digest': self.p.digest(
            self.p.scoped_contract(self.root, self.a)['visible_identity'][0]['references']),
            'parts': {part: {'status': 'passed', 'observations': 'Observed ' + attribute,
                             'reference_attributes': [attribute]}
                      for part, attribute in visible['references'][0]['attributes'].items()}}
        record['policy']['visible_identity']['actor-a'] = observation
        with self.assertRaises(ValueError): self.p.candidate_guard(self.root, self.a, record, self.entry)
        observation['parts']['face'] = {'status': 'not_assessable', 'observations': 'Face outside source frame'}
        self.p.candidate_guard(self.root, self.a, record, self.entry)
        observation['parts']['wrist']['reference_attributes'] = ['generic slim feminine wrist']
        with self.assertRaises(ValueError): self.p.candidate_guard(self.root, self.a, record, self.entry)
        observation['parts']['wrist']['reference_attributes'] = ['broad wrist']
        del observation['parts']['sleeve']
        with self.assertRaises(ValueError): self.p.candidate_guard(self.root, self.a, record, self.entry)

    def test_face_outside_source_frame_is_not_assessable_never_passed(self):
        visible = self.visible(); self.policy['visible_identity'] = [visible]; self.save()
        record = self.candidate()
        record['policy']['visible_identity']['actor-a'] = {'status': 'passed',
            'reference_digest': self.p.digest(self.p.scoped_contract(self.root, self.a)['visible_identity'][0]['references']),
            'parts': {part: {'status': 'passed', 'observations': 'Observed current part',
                             'reference_attributes': [attribute]}
                      for part, attribute in visible['references'][0]['attributes'].items()}}
        observation = record['policy']['visible_identity']['actor-a']
        observation['parts']['face'] = {'status': 'passed', 'observations': 'Face likeness accepted'}
        with self.assertRaises(ValueError): self.p.candidate_guard(self.root, self.a, record, self.entry)
        observation['parts']['face'] = {'status': 'not_assessable', 'observations': 'Face outside source frame'}
        self.p.candidate_guard(self.root, self.a, record, self.entry)

    def state(self):
        return {'schema_version': 1, 'output_sha256': sha(b'out.mp4'),
                'preview': {'status': 'ready', 'output_sha256': sha(b'out.mp4')},
                'known_issues': [], 'exceptions': [],
                'user_acceptance': {'status': 'final', 'actor': 'user', 'source_message': 'user final accepts',
                                    'output_sha256': sha(b'out.mp4')}}

    def test_final_requires_current_file_and_distinguishes_provisional_from_final(self):
        self.save(); state = self.state(); write(self.root / 'delivery_state.json', state)
        self.p.final_guard(self.root, {'output_path': 'out.mp4'})
        state['user_acceptance']['status'] = 'provisional'; write(self.root / 'delivery_state.json', state)
        with self.assertRaises(ValueError): self.p.final_guard(self.root, {'output_path': 'out.mp4'})
        state['user_acceptance']['status'] = 'final'; write(self.root / 'delivery_state.json', state)
        (self.root / 'out.mp4').write_bytes(b'changed final')
        with self.assertRaises(ValueError): self.p.final_guard(self.root, {'output_path': 'out.mp4'})

    def test_hard_issue_exception_requires_real_user_exact_issue_and_current_output(self):
        self.save(); state = self.state()
        state['known_issues'] = [{'id': 'warp', 'severity': 'hard', 'status': 'open',
                                  'description': 'Exact logo is distorted', 'output_sha256': sha(b'out.mp4')}]
        write(self.root / 'delivery_state.json', state)
        with self.assertRaises(ValueError): self.p.final_guard(self.root, {'output_path': 'out.mp4'})
        exception = {'issue_id': 'warp', 'status': 'accepted', 'actor': 'user',
                     'source_message': 'user accepts this logo issue in current final', 'output_sha256': sha(b'out.mp4'),
                     'issue_digest': self.p.digest(state['known_issues'][0])}
        state['exceptions'] = [exception]
        for key, invalid in (('issue_id', 'another'), ('actor', 'codex'), ('source_message', ''), ('output_sha256', 'old')):
            original = exception[key]; exception[key] = invalid; write(self.root / 'delivery_state.json', state)
            with self.subTest(key=key), self.assertRaises(ValueError): self.p.final_guard(self.root, {'output_path': 'out.mp4'})
            exception[key] = original
        write(self.root / 'delivery_state.json', state)
        self.p.final_guard(self.root, {'output_path': 'out.mp4'})
        state['known_issues'][0]['description'] = 'A new, different artwork failure under same ID'
        write(self.root / 'delivery_state.json', state)
        with self.assertRaises(ValueError): self.p.final_guard(self.root, {'output_path': 'out.mp4'})

    def test_delivery_state_enforces_final_acceptance_without_optional_policy(self):
        state = self.state(); write(self.root / 'delivery_state.json', state)
        self.p.final_guard(self.root, {'output_path': 'out.mp4'})
        state['user_acceptance']['status'] = 'provisional'
        write(self.root / 'delivery_state.json', state)
        with self.assertRaises(ValueError): self.p.final_guard(self.root, {'output_path': 'out.mp4'})
        state['user_acceptance']['status'] = 'final'
        state['known_issues'] = [{'id': 'logo', 'severity': 'hard', 'status': 'open',
                                 'description': 'Exact artwork requirement still failed', 'output_sha256': sha(b'out.mp4')}]
        write(self.root / 'delivery_state.json', state)
        with self.assertRaises(ValueError): self.p.final_guard(self.root, {'output_path': 'out.mp4'})

    def test_pending_unified_state_cannot_be_bypassed_by_absent_optional_stages(self):
        self.p.init_run(self.root)
        self.assertFalse((self.root / 'production-policy.json').exists())
        with self.assertRaises(ValueError): self.p.final_guard(self.root, {'output_path': 'out.mp4'})

    def test_init_preserves_existing_state_and_policy_reviews(self):
        self.save(); state = self.state(); write(self.root / 'delivery_state.json', state)
        before = (self.root / 'delivery_state.json').read_bytes()
        self.p.init_run(self.root)
        self.assertEqual(before, (self.root / 'delivery_state.json').read_bytes())


if __name__ == '__main__': unittest.main()
