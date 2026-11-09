"""New-source authoring uses actual tiny decoded media, no visual-pass inference."""
from pathlib import Path
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import factory as f
import media
from test_factory import video_fixture
try:
    import physical_source as author
except ModuleNotFoundError:
    author = None


class PhysicalSourceAuthoring(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(author, 'Pending source-physical authoring tool is missing')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'assets').mkdir()
        path = video_fixture(self.root/'assets/source.mp4', fps=8, pts=[0,1,2])
        report = media.inspect(path)
        self.source = {'schema_version':1, 'source':f.file_signature(self.root,'assets/source.mp4'),
                       **{k:v for k,v in report.items() if k != 'file_signature'}}
        self.source['timeline_digest'] = f.digest({'video':self.source['video'], 'audio_streams':self.source['audio_streams']})
        f.write(self.root/'source.json',self.source)
        self.analysis = {'schema_version':1,'source_sha256':self.source['source']['sha256'],'status':'passed',
                         'roles':[],'shots':[{'id':'s1','start':0,'end':3,'roles':[],
                                            'description_en':'The inspected synthetic source has one package.','events':[]}],
                         'soundscape_en':'Silent fixture.','music_en':'No music.','review_notes':'Synthetic source review contract fixture.'}
        f.write(self.root/'analysis.json',self.analysis)
        f.write(self.root/'job.json',{'production_authorized':False,'media_references':[
            {'id':'human','purpose':'identity','role_slot':'A'},
            {'id':'object','purpose':'product','product':'parcel'},
            {'id':'other-view','purpose':'product','product':'parcel'}]})

    def ready(self):
        path = author.draft(self.root)
        facts = f.read(path)
        facts['products']['parcel'] = {'source_interval':[0,3],
            'panels':{'lid':'The inspected source lid is the same connected physical face.'},
            'hinges':['The source lid is connected to the base.']}
        facts['rules'] = [{'id':'lid-continuity','product':'parcel','panel':'lid','source_interval':[0,3],
            'attribute':'surface_tracking','expected':'Keep this same source lid face.',
            'origin':'source','basis':'Actual synthetic source frame1.','supersedes':[]}]
        facts['consistency_checks'] = [{'id':'lid-check','product':'parcel','panel':'lid','source_interval':[0,3],
            'criterion':'surfaces','rule_ids':['lid-continuity'],
            'states':[{'id':'shown','source_frame':1,'description':'The inspected source lid face remains connected.'}]}]
        facts['source_review'] = {'status':'passed','notes':'Actually inspected the local synthetic source; no production visual claim.',
            'capture':{criterion:{'status':'not_applicable','notes':'Not present in this small synthetic source fixture.','check_ids':[]}
                       for criterion in author.CRITERIA}}
        facts['source_review']['capture']['surfaces'] = {'status':'observed','notes':'Actually inspected the source lid face.','check_ids':['lid-check']}
        f.write(path,facts)
        return path,facts

    def test_draft_collects_product_ids_without_inventing_geometry_or_activation(self):
        path = author.draft(self.root)
        facts = f.read(path)
        self.assertEqual(path,(self.root/'evidence/physical-source.draft.json').resolve())
        self.assertEqual(list(facts['products']),['parcel'])
        self.assertEqual(facts['products']['parcel'],{'source_interval':None,'panels':{},'hinges':[]})
        self.assertEqual(facts['source_review']['status'],'pending')
        self.assertEqual(len(facts['source_review']['capture']),9)
        self.assertTrue(all(x == {'status':'unknown','notes':'','check_ids':[]} for x in facts['source_review']['capture'].values()))
        self.assertFalse((self.root/'evidence/physical-source.json').exists())
        self.assertFalse((self.root/'production-contract.json').exists())
        self.assertEqual(f.read(self.root/'source.json'),self.source)

    def test_explicit_ids_and_empty_inputs_stay_pending_without_fabricated_products(self):
        path = author.draft(self.root,product_ids=['crate','crate','tray'])
        self.assertEqual(list(f.read(path)['products']),['crate','tray'])
        path.unlink(); f.write(self.root/'job.json',{})
        self.assertEqual(f.read(author.draft(self.root))['products'],{})
        with self.assertRaises(ValueError):author.activate(self.root)

    def test_existing_draft_is_preserved(self):
        path = author.draft(self.root);value=f.read(path)
        value['source_review']['notes']='Work in progress, keep this observation.';f.write(path,value)
        before=path.read_bytes();self.assertEqual(author.draft(self.root),path)
        self.assertEqual(path.read_bytes(),before)

    def test_unknown_missing_or_unreviewed_capture_cannot_activate(self):
        path,facts=self.ready()
        for mutation in ('pending','unknown','missing','notes'):
            value=copy.deepcopy(facts)
            if mutation=='pending':value['source_review']['status']='pending'
            elif mutation=='unknown':value['source_review']['capture']['openings']['status']='unknown'
            elif mutation=='missing':value['source_review']['capture'].pop('openings')
            else:value['source_review']['notes']=''
            f.write(path,value)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):author.activate(self.root)
        self.assertFalse((self.root/'evidence/physical-source.json').exists())

    def test_reviewed_validation_returns_current_source_facts_without_enabling_them(self):
        self.ready();facts=author.validate(self.root)
        self.assertEqual(facts['source_sha256'],self.source['source']['sha256'])
        self.assertEqual(facts['frame_count'],3)
        self.assertIn('structured-consistency',facts['required_capabilities'])
        self.assertFalse((self.root/'evidence/physical-source.json').exists())
        self.assertEqual(f.read(self.root/'source.json'),self.source)

    def test_activation_initializes_pending_targets_and_marks_top_level_capabilities_only(self):
        self.ready();f.write(self.root/'run-runtime.json',{'sentinel':'Existing runtime must not be auto-adopted.'})
        before=(self.root/'run-runtime.json').read_bytes();facts=author.activate(self.root)
        self.assertEqual(f.read(self.root/'evidence/physical-source.json'),facts)
        source=f.read(self.root/'source.json')
        self.assertEqual(source['source'],self.source['source'])
        self.assertEqual(set(source['source_capabilities']),{'structured-consistency','scoped-physical-contract'})
        target=f.read(self.root/'production-contract.json')
        self.assertEqual(target['products']['parcel']['panels'],{'lid':''})
        self.assertEqual(target['products']['parcel']['references'],[])
        self.assertEqual(f.read(self.root/'physical-reviews.json')['inputs'],{})
        self.assertEqual((self.root/'run-runtime.json').read_bytes(),before)
        self.assertFalse(f.read(self.root/'job.json')['production_authorized'])

    def test_existing_target_contract_and_reviews_are_not_overwritten(self):
        self.ready();f.write(self.root/'production-contract.json',{'sentinel':'current target choices'})
        f.write(self.root/'physical-reviews.json',{'sentinel':'current actual reviews'})
        before={name:(self.root/name).read_bytes() for name in ('production-contract.json','physical-reviews.json')}
        author.activate(self.root)
        self.assertEqual({name:(self.root/name).read_bytes() for name in before},before)

    def test_different_active_facts_are_rejected_at_both_supported_locations(self):
        path,facts=self.ready()
        for name in ('assets/evidence/physical-source.json','evidence/physical-source.json'):
            with self.subTest(name=name):
                previous=copy.deepcopy(facts);previous['source_review']['notes']='Different prior source observations.'
                target=self.root/name;f.write(target,previous);original=target.read_bytes()
                with self.assertRaisesRegex(ValueError,'active|conflict|different'):author.activate(self.root)
                self.assertEqual(target.read_bytes(),original)
                self.assertEqual(f.read(self.root/'source.json'),self.source)
                target.unlink()

    def test_observed_capture_requires_actual_matching_check_ids(self):
        path,facts=self.ready()
        for ids in ([],['missing']):
            value=copy.deepcopy(facts);value['source_review']['capture']['surfaces']['check_ids']=ids;f.write(path,value)
            with self.subTest(ids=ids),self.assertRaisesRegex(ValueError,'check'):author.validate(self.root)
        value=copy.deepcopy(facts);value['source_review']['capture']['openings'].update(status='observed',check_ids=['lid-check'])
        f.write(path,value)
        with self.assertRaisesRegex(ValueError,'criterion|check'):author.validate(self.root)

    def test_interval_empty_geometry_and_state_source_frame_are_checked(self):
        path,facts=self.ready()
        for change in ('interval','panels','frame'):
            value=copy.deepcopy(facts)
            if change=='interval':value['products']['parcel']['source_interval']=[0,4]
            elif change=='panels':value['products']['parcel']['panels']={}
            else:value['consistency_checks'][0]['states'][0]['source_frame']=3
            f.write(path,value)
            with self.subTest(change=change),self.assertRaises(ValueError):author.validate(self.root)

    def test_source_rule_self_override_cannot_activate_an_invalid_source_catalog(self):
        path,facts=self.ready()
        facts['rules'][0]['supersedes']=['lid-continuity'];f.write(path,facts)
        with self.assertRaisesRegex(ValueError,'supersedes|cyclic|override'):author.activate(self.root)
        self.assertFalse((self.root/'evidence/physical-source.json').exists())

    def test_actual_source_bytes_and_decoded_frame_count_cannot_be_forged(self):
        path,facts=self.ready()
        metadata=copy.deepcopy(self.source);metadata['video']['frame_count']=4
        metadata['video']['frames'].append(copy.deepcopy(metadata['video']['frames'][-1]));f.write(self.root/'source.json',metadata)
        analysis=copy.deepcopy(self.analysis);analysis['shots'][0]['end']=4;f.write(self.root/'analysis.json',analysis)
        facts['frame_count']=4;f.write(path,facts)
        with self.assertRaisesRegex(ValueError,'decoded|frame'):author.validate(self.root)
        f.write(self.root/'source.json',self.source);f.write(self.root/'analysis.json',self.analysis)
        (self.root/'assets/source.mp4').write_bytes(b'changed source bytes')
        with self.assertRaisesRegex(ValueError,'source|SHA|bytes'):author.validate(self.root)

    def test_source_change_after_reviewed_validation_rejects_before_activation(self):
        self.ready();validate=author.validate
        def changed(project,relative,**kwargs):
            facts=validate(project,relative,**kwargs)
            (self.root/'assets/source.mp4').write_bytes(b'changed immediately before activation')
            return facts
        with patch.object(author,'validate',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'source|SHA|bytes'):author.activate(self.root)
        self.assertFalse((self.root/'evidence/physical-source.json').exists())
        self.assertEqual(f.read(self.root/'source.json'),self.source)

    def test_decode_options_reach_actual_media_runtime(self):
        self.ready()
        import av
        deps=str(Path(av.__file__).parent.parent)
        facts=author.validate(self.root,deps=deps,scalar_cpu=False)
        self.assertEqual(facts['frame_count'],3)
        if sys.platform != 'win32':
            with self.assertRaisesRegex(ValueError,'scalar_cpu.*Windows'):
                author.validate(self.root,deps=deps,scalar_cpu=True)

    def test_cli_activation_accepts_decode_dependencies_and_retains_source_signature(self):
        self.ready()
        import av
        process=subprocess.run([sys.executable,'-B',str(Path(author.__file__).resolve()),'activate',
            '--project',str(self.root),'--deps',str(Path(av.__file__).parent.parent)],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(json.loads(process.stdout)['status'],'activated')
        self.assertEqual(f.read(self.root/'source.json')['source'],self.source['source'])

    def test_current_passed_analysis_and_source_sha_are_required(self):
        self.ready()
        for key,value in (('status','pending'),('source_sha256','0'*64)):
            analysis=copy.deepcopy(self.analysis);analysis[key]=value;f.write(self.root/'analysis.json',analysis)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'analysis|source'):author.validate(self.root)

    def test_absolute_traversal_symlink_and_active_named_draft_paths_reject(self):
        path,_=self.ready()
        for relative in (str(path.resolve()),'../outside.json','evidence/physical-source.json','assets/evidence/physical-source.json'):
            with self.subTest(relative=relative),self.assertRaises(ValueError):
                author.draft(self.root,draft_relative=relative)
        outside=self.root/'other.json';outside.write_text('{}');link=self.root/'linked.json';link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,'symlink|contained|path'):author.validate(self.root,'linked.json')
        with tempfile.TemporaryDirectory() as other:
            (self.root/'linked-dir').symlink_to(other,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'symlink|contained|path'):author.draft(self.root,draft_relative='linked-dir/draft.json')
            self.assertEqual(list(Path(other).iterdir()),[])

    def test_legacy_runtime_facts_do_not_silently_acquire_authoring_approval_requirements(self):
        _,facts=self.ready();facts.pop('source_review');facts.pop('required_capabilities',None)
        current=author.validate_source_structure(self.root,facts,decode=False)
        self.assertNotIn('source_review',current)
        self.assertNotIn('structured-consistency',current.get('required_capabilities',[]))
        f.write(self.root/'evidence/physical-source.draft.json',facts)
        with self.assertRaisesRegex(ValueError,'review'):author.validate(self.root)

    def test_legacy_empty_physical_catalog_keeps_its_existing_compatibility(self):
        facts={'schema_version':1,'source_sha256':self.source['source']['sha256'],
               'frame_count':3,'products':{},'rules':[]}
        self.assertEqual(author.validate_source_structure(self.root,facts,decode=False)['products'],{})

    def test_cli_draft_is_pending_and_validate_refuses_unreviewed_draft(self):
        script=Path(author.__file__).resolve()
        command=[sys.executable,'-B',str(script)]
        drafted=subprocess.run(command+['draft','--project',str(self.root),'--product','crate'],capture_output=True,text=True)
        self.assertEqual(drafted.returncode,0,drafted.stderr)
        self.assertEqual(json.loads(drafted.stdout)['status'],'pending')
        checked=subprocess.run(command+['validate','--project',str(self.root)],capture_output=True,text=True)
        self.assertNotEqual(checked.returncode,0)
        self.assertFalse((self.root/'evidence/physical-source.json').exists())


if __name__=='__main__':unittest.main(verbosity=2)
