"""Real tiny decoded media exercise evidence binding; no visual judgments inferred."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
import media

MODULE = Path(__file__).with_name('consistency_review.py')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))


def video(path, count, size=(40, 30)):
    av = media.runtime()
    from PIL import Image, ImageDraw
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('ffv1', rate=9); stream.width, stream.height = size
        stream.pix_fmt = 'bgr0'; stream.codec_context.thread_count = 1
        for index in range(count):
            image = Image.new('RGB', size, (index * 13 % 256, index * 31 % 256, index * 47 % 256))
            ImageDraw.Draw(image).line((index % size[0], 0, size[0] - 1, size[1] - 1), fill='white')
            frame = av.VideoFrame.from_image(image); frame.pts = index; frame.time_base = Fraction(1, 9)
            for packet in stream.encode(frame): output.mux(packet)
        for packet in stream.encode(): output.mux(packet)


class ConsistencyReviewTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'consistency review implementation missing')
        spec = importlib.util.spec_from_file_location('consistency_review', MODULE)
        self.c = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.c)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        video(self.root / 'source.mkv', 12); video(self.root / 'candidate.mkv', 14)
        source_sha = hashlib.sha256((self.root / 'source.mkv').read_bytes()).hexdigest()
        write(self.root / 'source.json', {'source': {'path': 'source.mkv', 'sha256': source_sha}})
        self.check = {'id': 'tracked-print', 'product': 'box', 'panel': 'lid', 'source_interval': [0, 12],
            'criterion': 'artwork', 'rule_ids': ['print-face'], 'local_axes': {'u': 'long edge', 'v': 'short edge', 'normal': 'outward'},
            'forbidden_panels': ['base'], 'states': [
                {'id': 'first', 'source_frame': 2, 'description': 'Observed first mechanism state'},
                {'id': 'middle', 'source_frame': 5, 'description': 'Observed middle mechanism state'},
                {'id': 'last', 'source_frame': 10, 'description': 'Observed final mechanism state'}]}
        self.facts = {'schema_version': 1, 'source_sha256': source_sha, 'frame_count': 12,
            'products': {'box': {'source_interval': [0, 12], 'panels': {'lid': 'lid', 'base': 'base'}}},
            'rules': [{'id': 'print-face', 'product': 'box', 'panel': 'lid', 'source_interval': [0, 12], 'origin': 'source'}],
            'consistency_checks': [self.check]}
        self.window = {'window_id': 'window-one', 'source_interval': [2, 8], 'context_interval': [0, 12]}
        self.entry = {'window_id': 'window-one', 'input_digest': 'current-input'}
        self.record = {'output_path': 'candidate.mkv', 'file_signature': self.c.signature(self.root, 'candidate.mkv'),
            'source_to_output': [1, 3, 5, 7, 9, 11], 'input_digest': 'current-input', 'physical': {}}

    def prepared(self, final=False):
        if final:
            self.record.update(output_path='source.mkv', file_signature=self.c.signature(self.root, 'source.mkv'), composition_digest='current-composition')
        result = self.c.prepare(self.root, self.facts, self.window, self.record, 'review-final' if final else 'review-window', final=final)
        return result

    def observed(self, final=False):
        result = self.prepared(final)
        review = result['review']
        for check in review['checks'].values():
            check.update(status='passed', notes='Synthetic test observations, not a production visual approval')
            for state in check['states'].values(): state.update(status='observed', notes='Synthetic actual-frame review fixture')
            for transition in check['transitions']: transition.update(status='observed', notes='Synthetic continuous transition fixture')
        self.record['physical']['consistency_review'] = review
        return review

    def guard(self): return self.c.review_guard(self.root, self.facts, self.window, self.record, self.entry)

    def test_missing_optional_checks_preserve_legacy_behavior(self):
        self.assertEqual([], self.c.validate_checks({}))
        self.assertEqual([], self.c.scoped_checks({}, [0, 1]))
        self.assertIsNone(self.c.review_guard(self.root, {}, self.window, {}, self.entry))
        self.assertIsNone(self.c.final_guard(self.root, {}, {}))

    def test_schema_rejects_unknown_or_conflicting_source_references(self):
        mutations = [lambda c: c.update(product='unknown'), lambda c: c.update(panel='unknown'),
            lambda c: c.update(criterion='made-up'), lambda c: c.update(rule_ids=['missing']),
            lambda c: c.update(source_interval=[0, 13]), lambda c: c['states'][0].update(source_frame=12),
            lambda c: c['states'][1].update(id='first'), lambda c: c['local_axes'].update(normal=''),
            lambda c: c.update(forbidden_panels=['unknown'])]
        for mutate in mutations:
            facts = copy.deepcopy(self.facts); mutate(facts['consistency_checks'][0])
            with self.subTest(mutation=mutations.index(mutate)), self.assertRaises(ValueError): self.c.validate_checks(facts)
        self.facts['consistency_checks'].append(copy.deepcopy(self.check))
        with self.assertRaises(ValueError): self.c.validate_checks(self.facts)

    def test_rule_must_match_check_product_panel_and_interval(self):
        for change in ({'panel': 'base'}, {'product': 'another'}, {'source_interval': [12, 14]}):
            facts = copy.deepcopy(self.facts); facts['rules'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): self.c.validate_checks(facts)

    def test_owner_scope_filters_states_and_excludes_empty_owner_checks(self):
        context = self.c.scoped_checks(self.facts, [0, 12])
        owner = self.c.scoped_checks(self.facts, [2, 8], owner=True)
        self.assertEqual(['first', 'middle', 'last'], [s['id'] for s in context[0]['states']])
        self.assertEqual(['first', 'middle'], [s['id'] for s in owner[0]['states']])
        self.assertEqual([], self.c.scoped_checks(self.facts, [6, 8], owner=True))
        self.assertEqual([], self.c.scoped_checks(self.facts, [12, 13]))

    def test_prepare_exports_native_source_and_candidate_proofs_only_pending(self):
        result = self.prepared(); review = result['review']
        self.assertTrue((self.root / result['review_path']).is_file())
        self.assertEqual('pending', review['checks']['tracked-print']['status'])
        self.assertEqual({'first', 'middle'}, set(review['checks']['tracked-print']['states']))
        from PIL import Image
        for state in review['checks']['tracked-print']['states'].values():
            self.assertEqual('pending', state['status'])
            for key in ('evidence', 'source_evidence'):
                with Image.open(self.root / state[key]['path']) as image: self.assertEqual((40, 30), image.size)
        with self.assertRaises(ValueError): self.c.prepare(self.root, self.facts, self.window, self.record, 'review-window')
        for out in ('assets/evidence/new', 'evidence/new', '../outside'):
            with self.subTest(out=out), self.assertRaises(ValueError): self.c.prepare(self.root, self.facts, self.window, self.record, out)

    def test_prepare_rejects_case_variants_and_resolved_aliases_of_source_trees(self):
        (self.root / 'assets').mkdir()
        (self.root / 'source-tree-alias').symlink_to(self.root / 'assets', target_is_directory=True)
        for out in ('Assets/new-proof', 'EVIDENCE/new-proof', 'source-tree-alias/alias-proof'):
            with self.subTest(out=out), self.assertRaises(ValueError):
                self.c.prepare(self.root, self.facts, self.window, self.record, out)

    def test_invalid_empty_check_object_is_not_a_legacy_bypass(self):
        facts = copy.deepcopy(self.facts); facts['consistency_checks'] = {}
        with self.assertRaises(ValueError): self.c.review_guard(self.root, facts, self.window, self.record, self.entry)
        with self.assertRaises(ValueError): self.c.final_guard(self.root, facts, self.record)

    def test_prepare_refuses_non_chronological_state_mapping_before_writing(self):
        self.record['source_to_output'] = [9, 8, 7, 3, 2, 1]
        with self.assertRaises(ValueError): self.prepared()
        self.assertFalse((self.root / 'review-window').exists())

    def test_pending_prepare_never_satisfies_review_guard(self):
        self.record['physical']['consistency_review'] = self.prepared()['review']
        with self.assertRaises(ValueError): self.guard()

    def test_current_owner_state_pngs_and_transition_observations_pass(self):
        review = self.observed(); self.guard()
        self.assertEqual([1, 8], review['checks']['tracked-print']['transitions'][0]['output_interval'])
        self.assertNotIn('last', review['checks']['tracked-print']['states'])

    def test_missing_state_wrong_mapping_or_changed_definition_rejects(self):
        review = self.observed(); original = copy.deepcopy(review)
        cases = ('missing', 'mapping', 'definition', 'input')
        for case in cases:
            self.record['physical']['consistency_review'] = copy.deepcopy(original)
            if case == 'missing': del self.record['physical']['consistency_review']['checks']['tracked-print']['states']['middle']
            if case == 'mapping': self.record['physical']['consistency_review']['checks']['tracked-print']['states']['first']['output_frame'] = 2
            if case == 'definition': self.check['local_axes']['normal'] = 'changed semantic source definition'
            if case == 'input': self.record['physical']['consistency_review']['input_digest'] = 'old-input'
            with self.subTest(case=case), self.assertRaises(ValueError): self.guard()
            self.check['local_axes']['normal'] = 'outward'

    def test_foreign_or_resized_png_and_stale_evidence_sha_reject(self):
        review = self.observed(); state = review['checks']['tracked-print']['states']['first']
        from PIL import Image
        path = self.root / state['evidence']['path']; saved = path.read_bytes()
        for size, stale in (((40, 30), False), ((20, 15), False), ((40, 30), True)):
            Image.new('RGB', size, 'black').save(path)
            if not stale: state['evidence']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            else: state['evidence']['sha256'] = 'stale-sha'
            with self.subTest(size=size, stale=stale), self.assertRaises(ValueError): self.guard()
        path.write_bytes(saved)

    def test_source_evidence_pair_cannot_be_missing_foreign_or_stale(self):
        review = self.observed(); state = review['checks']['tracked-print']['states']['first']
        original = copy.deepcopy(state['source_evidence']); path = self.root / original['path']; saved = path.read_bytes()
        for change in ('missing', 'foreign', 'stale-sha', 'missing-file'):
            state['source_evidence'] = copy.deepcopy(original); path.write_bytes(saved)
            if change == 'missing': del state['source_evidence']
            if change == 'foreign': state['source_evidence'] = copy.deepcopy(state['evidence'])
            if change == 'stale-sha': state['source_evidence']['sha256'] = 'stale'
            if change == 'missing-file': path.unlink()
            with self.subTest(change=change), self.assertRaises((ValueError, OSError)): self.guard()
        path.write_bytes(saved)

    def test_source_actual_bytes_must_still_match_facts_and_metadata(self):
        self.observed(); (self.root / 'source.mkv').write_bytes(b'changed original source')
        with self.assertRaises(ValueError): self.guard()

    def test_missing_or_incorrect_transition_cannot_be_replaced_by_state_notes(self):
        review = self.observed(); checks = review['checks']['tracked-print']; original = copy.deepcopy(checks['transitions'])
        for mutate in ('missing', 'notes', 'range', 'states'):
            checks['transitions'] = copy.deepcopy(original)
            if mutate == 'missing': checks['transitions'] = []
            if mutate == 'notes': checks['transitions'][0]['notes'] = ''
            if mutate == 'range': checks['transitions'][0]['output_interval'] = [1, 7]
            if mutate == 'states': checks['transitions'][0]['to_state'] = 'last'
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): self.guard()

    def test_current_output_bytes_are_bound_even_if_pngs_still_exist(self):
        self.observed(); (self.root / 'candidate.mkv').write_bytes(b'changed video')
        with self.assertRaises(ValueError): self.guard()

    def test_final_requires_all_states_identity_frame_mapping_and_current_composition(self):
        review = self.observed(final=True); self.c.final_guard(self.root, self.facts, self.record)
        self.assertEqual({'first', 'middle', 'last'}, set(review['checks']['tracked-print']['states']))
        review['composition_digest'] = 'stale-composition'
        with self.assertRaises(ValueError): self.c.final_guard(self.root, self.facts, self.record)


if __name__ == '__main__': unittest.main()
