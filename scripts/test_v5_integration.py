"""Actual preparation/request integration; no model or remote service calls."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch
import factory as f
import comfy_workflow as cw
import test_factory as fixtures
import test_comfy_workflow as graphs


class IntegratedContracts(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FactoryIntegration('test_actual_ingest_pts_and_evidence')
        self.fixture.setUp()
        self.project = self.fixture.project
        self.job = copy.deepcopy(self.fixture.job)
        from PIL import Image
        Image.new('RGB', (32,32), 'pink').save(self.project/'references-input/product.png')
        self.job['media_references'] = [
            {'id':'product','path':'references-input/product.png','purpose':'product','product':'gift',
             'source_interval':[0,8], 'description_en':'One pink folding gift box.'},
            {'id':'hero','path':'references-input/A.png','purpose':'identity','role_slot':'A',
             'source_interval':[0,8]}]
        f.write(self.project/'job.json',self.job)

    def test_one_person_two_inputs_preserves_real_picture_order(self):
        entry = f.prepare(self.project,approve_semantics=True)['jobs'][0]
        prompt = (self.project/entry['prompt_path']).read_text()
        self.assertEqual(entry['reference_paths'],['references-input/product.png','references-input/A.png'])
        self.assertIn('<Subject 1> is the person represented by <Picture 2>',prompt)
        self.assertNotIn('<Subject 2>',prompt)
        self.assertIn('<Picture 1> supplies declared product',prompt)
        self.assertEqual(entry['local_bindings'][0]['picture'],2)

    def test_reference_dossier_change_is_request_invalidating(self):
        entry = f.prepare(self.project)['jobs'][0]
        self.job['media_references'][0]['description_en']='A newly approved matte pink box.'
        f.write(self.project/'job.json',self.job)
        self.assertNotEqual(entry['input_digest'],f.compute_input_digest(self.project,entry))

    def test_unrelated_reference_scope_does_not_stale_current_window(self):
        entry = f.prepare(self.project)['jobs'][0]
        self.job['references']['B'] = self.job['references']['A']
        self.job['media_references'].append({'id':'other','path':'references-input/A.png',
             'purpose':'identity','role_slot':'B','source_interval':[0,8]})
        f.write(self.project/'job.json',self.job)
        self.assertEqual(entry['input_digest'],f.compute_input_digest(self.project,entry))

    def test_reference_slot_alias_binds_images_independent_of_human_count(self):
        graph,schemas,profile = graphs.fixture()
        profile['limits']={'reference_slots':2,'fps':['12'],'frame_counts':[8,16]}
        path = self.project/'assets/workflow.json'; f.write(path,graph)
        import media
        profile['workflow_sha256']=media.signature(path)['sha256']
        self.job['profile']=profile; f.write(self.project/'job.json',self.job)
        entry=f.prepare(self.project)['jobs'][0]
        compiled=cw.compile_graph(self.project,entry,{'video':'v.mp4','references':['p.png','a.png']},'offline')
        self.assertEqual(compiled['conditioning']['inputs']['portrait_a'],'p.png')
        self.assertEqual(compiled['conditioning']['inputs']['portrait_b'],'a.png')

    def test_declared_node_binding_cannot_disagree_with_effective_graph(self):
        graph,schemas,profile = graphs.fixture()
        profile['limits'].update(fps=['12'],frame_counts=[8,16])
        path=self.project/'assets/workflow.json'; f.write(path,graph)
        import media
        profile['workflow_sha256']=media.signature(path)['sha256']
        self.job['profile']=profile
        self.job['media_references'][0]['node_binding']={'node_id':'conditioning','input':'portrait_b'}
        f.write(self.project/'job.json',self.job)
        with self.assertRaisesRegex(ValueError,'binding'):
            f.prepare(self.project)

    def test_prepare_checks_bound_runtime_before_derived_media(self):
        import runtime_binding
        with patch.object(runtime_binding,'guard',side_effect=ValueError('runtime mismatch')):
            with self.assertRaisesRegex(ValueError,'runtime mismatch'):
                f.prepare(self.project)
        self.assertFalse((self.project/'derived_inputs').exists())

    def test_explicit_two_image_app_keeps_one_person_product_pair(self):
        self.job['profile']['app_id']='2107845954833907713'
        self.job['profile']['limits'].update(fps=['24'],frame_counts=[22])
        plan=f.default_plan(self.fixture.source,self.fixture.analysis,self.job)
        self.assertEqual(f.window_profile(self.job,plan['windows'][0])['app_id'],'2107845954833907713')
        f.write(self.project/'job.json',self.job)
        entry=f.prepare(self.project)['jobs'][0]
        self.assertEqual(len(entry['reference_paths']),2)
        self.assertEqual(len(entry['local_bindings']),1)

    def test_new_delivery_state_blocks_ready_without_optional_stages(self):
        self.job.pop('media_references')  # Isolate delivery-state gate from product-source requirements.
        f.write(self.project/'job.json',self.job)
        self.fixture.candidate()
        f.assemble(self.project,'synthetic.mp4')
        reviews=f.read(self.project/'reviews.json')
        reviews['final']['visual']={'status':'passed','dynamic_intervals':[[0,8]],
            'native_intervals':[[0,8]],'notes':'Synthetic review contract only, not real video acceptance.'}
        f.write(self.project/'reviews.json',reviews)
        self.assertFalse((self.project/'production-policy.json').exists())
        with self.assertRaisesRegex(ValueError,'Delivery state'):
            f.build_skill(self.project,self.fixture.temp/'skills',status='ready')

    def test_artwork_anchors_are_transmitted_to_actual_prompt(self):
        import media
        f.write(self.project/'production-policy.json',{'schema_version':1,'stages':[],
            'artwork_masters':[{'id':'art','path':'references-input/product.png',
                'sha256':media.signature(self.project/'references-input/product.png')['sha256'],
                'product':'gift','panel':'outer_lid','scope':{},'strictness':'exact',
                'source_message':'OFFLINE synthetic exact-artwork request',
                'characteristics':{'foil':'Gold foil letters'},'anchors':{'text':'Keep title below the fold hinge'},
                'state_correspondences':{'open':'Art remains attached to the outer lid'}}],
            'visible_identity':[]})
        entry=f.prepare(self.project)['jobs'][0]
        prompt=(self.project/entry['prompt_path']).read_text()
        self.assertIn('Keep title below the fold hinge',prompt)
        self.assertIn('"strictness": "exact"',prompt)


if __name__=='__main__':
    unittest.main()
