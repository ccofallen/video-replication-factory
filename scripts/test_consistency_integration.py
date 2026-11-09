"""New-source physical consistency reaches real requests and immutable templates."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch
import factory as f
import media
import physical_contract as pc
import test_factory as fixtures


class ConsistencyIntegration(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.FactoryIntegration('test_actual_ingest_pts_and_evidence')
        self.fixture.setUp();self.project=self.fixture.project
        self.job=copy.deepcopy(self.fixture.job)
        from PIL import Image
        Image.new('RGB',(32,32),'pink').save(self.project/'references-input/box.png')
        self.job['media_references']=[
            {'id':'person','purpose':'identity','role_slot':'A','path':'references-input/A.png','source_interval':[0,8]},
            {'id':'object','purpose':'product','product':'sample','path':'references-input/box.png','source_interval':[0,8]}]
        f.write(self.project/'job.json',self.job)
        self.facts={'schema_version':1,'source_sha256':self.fixture.source['source']['sha256'],'frame_count':8,
            'products':{'sample':{'source_interval':[0,8],
                'panels':{'outside':'Outside print rotates with its original board.',
                    'inside':'Inside has no outside print. The hole stays in the end board.',
                    'stack':'Stack top has four corners; no extra polygon edge.'},
                'hinges':['The hinge stays attached along the original crease.']}},'rules':[]}

    def activate_legacy(self,relative='assets/evidence/physical-source.json'):
        f.write(self.project/relative,self.facts)
        import runtime_binding
        runtime_binding.bind(self.project,adopt=True,source_message='OFFLINE synthetic setup')
        pc.init_run(self.project)
        target=f.read(self.project/'production-contract.json')
        target['products']['sample']={'references':['references-input/box.png'],
            'panels':{'outside':'Current target exterior','inside':'Current target interior','stack':'Current target stack'},
            'hinges':['Current connected hinge']}
        f.write(self.project/'production-contract.json',target)

    def test_prepare_may_be_pending_but_product_submission_needs_source_facts(self):
        entry=f.prepare(self.project)['jobs'][0]
        self.assertFalse(pc.enabled(self.project))
        with self.assertRaisesRegex(ValueError,'source.*physical|physical.*source'):
            pc.input_guard(self.project,entry)

    def test_public_cloud_callback_cannot_skip_missing_physical_facts(self):
        import rh_runner as rh
        entry=f.prepare(self.project)['jobs'][0]
        ledger=rh.Ledger(self.fixture.temp/'private/tasks.sqlite')
        self.addCleanup(ledger.close)
        class NoProvider:
            def upload(self,*args):raise AssertionError('must block before upload')
            def submit(self,*args):raise AssertionError('must block before POST')
        with self.assertRaisesRegex(ValueError,'source.*physical|physical.*source'):
            rh.Runner(ledger,NoProvider()).submit_one(self.project,entry,validator=lambda p,e:e['input_digest'])

    def test_source_geometry_not_duplicated_as_rules_still_enters_real_prompt(self):
        self.activate_legacy()
        entry=f.prepare(self.project)['jobs'][0]
        prompt=(self.project/entry['prompt_path']).read_text()
        for required in ('Inside has no outside print','hole stays in the end board',
                         'Stack top has four corners','original crease'):
            self.assertIn(required,prompt)

    def test_first_build_keeps_actual_assets_facts_despite_ingest_evidence(self):
        self.activate_legacy()
        self.assertTrue((self.project/'evidence').is_dir())
        build=f.build_skill(self.project,self.fixture.temp/'skills')
        target=Path(build['path'])
        self.assertEqual(f.read(target/'assets/evidence/physical-source.json'),self.facts)
        self.assertIn('scoped-physical-contract',f.read(target/'manifest.json')['required_capabilities'])
        f.instantiate(target,self.fixture.temp/'reuse')
        self.assertTrue(pc.enabled(self.fixture.temp/'reuse'))

    def test_conflicting_evidence_directories_cannot_silently_choose_one(self):
        self.activate_legacy()
        other=copy.deepcopy(self.facts)
        other['products']['sample']['panels']['inside']='Conflicting source observation'
        f.write(self.project/'evidence/physical-source.json',other)
        import runtime_binding
        runtime_binding.bind(self.project,adopt=True,source_message='OFFLINE exercise explicit evidence conflict')
        with self.assertRaisesRegex(ValueError,'conflict'):
            f.build_skill(self.project,self.fixture.temp/'conflict-skills')

    def test_product_requirement_does_not_leak_into_an_unrelated_window(self):
        self.job['media_references'][1]['source_interval']=[0,4]
        f.write(self.project/'job.json',self.job)
        self.assertTrue(pc.required(self.project,{'source_interval':[0,4]}))
        self.assertFalse(pc.required(self.project,{'source_interval':[4,8]}))

    def test_physical_review_keeps_explicit_media_backend_options(self):
        self.activate_legacy()
        reviews=self.fixture.candidate();entry=f.read(self.project/'queue.json')['jobs'][0]
        window=f.read(self.project/'plan.json')['windows'][0]
        f.write(self.project/'physical-reviews.json',{'schema_version':1,'inputs':{entry['window_id']:{
            'status':'passed','contract_digest':pc.digest(pc.window_contract(self.project,window,entry['profile'])),
            'input_digest':entry['input_digest'],'request_signatures':pc.input_signatures(self.project,entry),
            'observations':{key:'Synthetic test observation, not actual production approval.'
                for key in ('source','target','guide','prompt')}}}})
        record=reviews['windows'][entry['window_id']]
        record['physical']={'status':'passed','file_signature':record['file_signature'],'input_digest':entry['input_digest'],
            'observations':{key:'Synthetic fixture only.' for key in pc.CRITERIA},
            'playback':{'status':'observed','method':'continuous-playback','speed':1,'intervals':[[0,8]],'notes':'Synthetic fixture only.'}}
        f.write(self.project/'reviews.json',reviews)
        with patch('consistency_review.review_guard') as guard:
            f.review_guard(self.project,deps='explicit-media-bundle',scalar_cpu=True)
        self.assertEqual(guard.call_args.kwargs,{'deps':'explicit-media-bundle','scalar_cpu':True})


if __name__=='__main__':unittest.main()
