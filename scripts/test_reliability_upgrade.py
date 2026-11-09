"""Real-media and fault regressions for the generic production reliability upgrade."""
from pathlib import Path
from fractions import Fraction
import argparse,copy,json,socket,subprocess,sys,tempfile,unittest,zipfile
from unittest.mock import patch
from PIL import Image
import factory,media,assembly_session as assembly,candidate_review
import test_factory as fixtures

class GenerationPolicyTests(unittest.TestCase):
    def test_numeric_quality_alone_selects_duration_cap(self):
        for quality, cap in [(0.5,15),(1,15),(1.0,15),(1.0001,10),(2,10)]:
            self.assertEqual(factory.generation_duration_cap({'quality_level':quality}),cap)
        self.assertEqual(factory.generation_duration_cap({'width':64,'height':48}),10)
        self.assertEqual(factory.generation_duration_cap({'quality_level':1,'width':2048,'height':2048}),15)
        self.assertEqual(factory.generation_duration_cap({'quality_level':2,'width':64,'height':48}),10)
        for quality in (True,0,-1,'1.0',None,float('nan'),float('inf')):
            with self.subTest(quality=quality), self.assertRaises(ValueError):
                factory.generation_duration_cap({'quality_level':quality})

    def test_complete_clock_not_requested_duration_controls_cap(self):
        window={'generation_fps':'24','generation_frames':360,'duration':'15','quality_level':1}
        factory.validate_generation_duration(window)
        for frames, duration, quality in [(361,'15',1),(360,'15.1',1),(241,'10',1.1),(240,'10.1',2)]:
            with self.subTest(frames=frames,duration=duration,quality=quality), self.assertRaises(ValueError):
                factory.validate_generation_duration({**window,'generation_frames':frames,'duration':duration,'quality_level':quality})
        with self.assertRaises(ValueError): factory.validate_generation_duration(window,{'quality_level':2})

    def test_low_quality_frame_lattice_keeps_complete_output_below_fifteen(self):
        profile={'quality_level':1,'limits':{'identity_slots':1,'fps':['24'],
                 'frame_grid':{'step':17,'offset':5,'minimum':5}}}
        self.assertEqual(factory.local_frame_count(profile,345,24),345)
        for needed in (346,360,361):
            with self.assertRaises(ValueError):factory.local_frame_count(profile,needed,24)
        with self.assertRaises(ValueError):factory.local_frame_count({**profile,'quality_level':2},239,24)

    def test_regeneration_policy_rejects_patch_overlay_and_face_swap_methods(self):
        factory.require_regeneration({})
        factory.require_regeneration({'modification_method':'regenerate'})
        for method in ('patch','overlay','face-swap','composite','mask'):
            with self.subTest(method=method),self.assertRaises(ValueError):
                factory.require_regeneration({'modification_method':method})

    def test_patch_entry_points_reject_before_loading_models_or_reading_media(self):
        import face_detail, face_swap
        with self.assertRaisesRegex(ValueError,'Regeneration-only'):face_detail.restore({})
        with self.assertRaisesRegex(ValueError,'Regeneration-only'):face_swap.preflight('missing-policy-probe',{})

    def test_old_patch_clis_stop_before_reading_assets_or_credentials(self):
        scripts=Path(factory.__file__).parent
        for script,args in [('face_detail.py',['--config','missing-policy-probe.json']),
                            ('face_swap.py',['tick-pilot','--project','missing-policy-probe'])]:
            result=subprocess.run([sys.executable,str(scripts/script),*args],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('regenerat',result.stderr.lower())
            self.assertNotIn('FileNotFoundError',result.stderr)

class ReliabilityTests(unittest.TestCase):
    setUp=fixtures.FactoryIntegration.setUp
    tearDown=fixtures.FactoryIntegration.tearDown
    def queue(self):return factory.prepare(self.project,approve_semantics=True)
    def test_unchanged_prepare_keeps_actual_semantic_review(self):
        old=self.queue()['jobs'][0]
        old['semantic_review']['notes']='Actually reviewed unchanged fixture prompt'
        factory.write(self.project/'queue.json',{'jobs':[old]})
        new=factory.prepare(self.project)['jobs'][0]
        self.assertEqual(new['semantic_review'],old['semantic_review'])
        self.job['references']['A']['identity_en']='Changed current identity'
        factory.write(self.project/'job.json',self.job)
        self.assertEqual(factory.prepare(self.project)['jobs'][0]['semantic_review']['status'],'pending')
    def two_windows(self):
        self.analysis['roles'][0]['appearances']=[[0,4]]
        self.analysis['roles'].append({'slot':'B','appearances':[[4,8]]})
        self.analysis['shots']=[{'id':'left','start':0,'end':4,'roles':['A'],'description_en':'{{A}} follows source.','events':[]},
            {'id':'right','start':4,'end':8,'roles':['B'],'description_en':'{{B}} follows source.','events':[]}]
        factory.write(self.project/'analysis.json',self.analysis)
        Image.new('RGB',(32,32),'blue').save(self.project/'references-input/B.png')
        self.job['references']['B']={'path':'references-input/B.png','identity_en':'Current blue B identity'}
        factory.write(self.project/'job.json',self.job)
        return self.queue()['jobs']
    def test_other_reference_and_window_do_not_revoke_this_window(self):
        a,b=self.two_windows()
        Image.new('RGB',(32,32),'red').save(self.project/'references-input/B.png')
        self.assertEqual(factory.compute_input_digest(self.project,a),a['input_digest'])
        self.assertNotEqual(factory.compute_input_digest(self.project,b),b['input_digest'])
        plan=factory.read(self.project/'plan.json');plan['windows'][1]['risk_source_intervals']=[[4,6]]
        factory.write(self.project/'plan.json',plan)
        self.assertEqual(factory.compute_input_digest(self.project,a),a['input_digest'])
    def test_unrelated_window_still_cannot_break_global_owner_plan(self):
        a,b=self.two_windows();plan=factory.read(self.project/'plan.json')
        plan['windows'][1]['source_interval']=[5,8];factory.write(self.project/'plan.json',plan)
        with self.assertRaises(ValueError):factory.compute_input_digest(self.project,a)
    def test_appearance_policy_revokes_semantics(self):
        a=self.queue()['jobs'][0];self.job['appearance_policy']={'headset':'remove'}
        factory.write(self.project/'job.json',self.job)
        self.assertNotEqual(factory.compute_input_digest(self.project,a),a['input_digest'])
    def test_actual_generated_tail_cannot_exceed_ten_seconds(self):
        self.queue();(self.project/'candidates').mkdir()
        fixtures.video_fixture(self.project/'candidates/too-long.mp4',pts=list(range(121)))
        with self.assertRaisesRegex(ValueError,'10-second production cap'):
            factory.inspect_candidate(self.project,'window_001','fixture','candidates/too-long.mp4')
    def test_twelve_second_source_uses_low_quality_cap_without_changing_owners(self):
        video=fixtures.video_fixture(self.temp/'twelve.mp4',fps=12,pts=list(range(144)))
        source=factory.ingest(self.temp/'twelve-run',video)
        analysis={'roles':[{'slot':'A','appearances':[[0,144]]}],
                  'shots':[{'id':'s1','start':0,'end':144,'roles':['A'],'description_en':'{{A}} follows source.'}]}
        job={'profile':{'kind':'standard-h3','quality_level':1,'limits':{}},'references':self.job['references']}
        plan=factory.default_plan(source,analysis,job)
        self.assertEqual(plan['windows'][0]['generation_frames'],144)
        self.assertEqual(plan['windows'][0]['quality_level'],1)
        self.assertEqual(plan['windows'][0]['source_interval'],[0,144])
        factory.validate_plan(source,analysis,plan)
        job['profile']['quality_level']=1.1
        with self.assertRaises(ValueError):factory.default_plan(source,analysis,job)

    def test_low_quality_candidate_tail_between_ten_and_fifteen_is_accepted(self):
        self.job['profile']['quality_level']=1
        factory.write(self.project/'job.json',self.job)
        self.queue();(self.project/'candidates').mkdir()
        fixtures.video_fixture(self.project/'candidates/twelve.mp4',fps=12,pts=list(range(144)))
        record=factory.inspect_candidate(self.project,'window_001','fixture','candidates/twelve.mp4')
        self.assertEqual(record['technical']['status'],'passed')
        self.assertEqual(record['visual']['status'],'pending')
        fixtures.video_fixture(self.project/'candidates/over-fifteen.mp4',fps=12,pts=list(range(181)))
        with self.assertRaises(ValueError):factory.inspect_candidate(self.project,'window_001','fixture','candidates/over-fifteen.mp4')

    def test_media_proof_reuses_decode_and_rechecks_corruption(self):
        cache=self.temp/'cache';a=media.inspect_cached(self.video,cache)
        with patch('media.inspect',side_effect=AssertionError('Unchanged media should not decode again')):
            self.assertEqual(media.inspect_cached(self.video,cache),a)
        path=next(cache.glob('*.json'));data=factory.read(path);data['report']['video']['frame_count']=100
        factory.write(path,data)
        self.assertEqual(media.inspect_cached(self.video,cache)['video']['frame_count'],8)
    def test_complete_evidence_reuse_rejects_changed_artifact(self):
        self.queue();rel='candidates/test.mp4';(self.project/'candidates').mkdir()
        import shutil;shutil.copy2(self.video,self.project/rel)
        args=(self.project,'window_001',rel,'candidate-evidence/current')
        first=candidate_review.prepare_evidence(*args,native_all=True)
        with patch('media.inspect',side_effect=AssertionError('Reuse complete proof')):
            self.assertTrue(candidate_review.prepare_evidence(*args,native_all=True)['reused_complete_evidence'])
        ev=factory.read(factory.resolve(self.project,first['evidence']['path']))
        path=factory.resolve(self.project,ev['files'][0]['path']);path.write_bytes(b'corrupted')
        with self.assertRaises(ValueError):candidate_review.prepare_evidence(*args,native_all=True)
    def test_lazy_selected_frame_conversion_and_repeated_index(self):
        canvas=media.display_canvas(self.source['video'])
        with patch('media.display_frame',wraps=media.display_frame) as display:
            generator=assembly.selected_frames([(self.video,0),(self.video,0),(self.video,6)],canvas)
            next(generator);self.assertEqual(display.call_count,1)
            next(generator);self.assertEqual(display.call_count,1)
            next(generator);self.assertEqual(display.call_count,2)
            with self.assertRaises(StopIteration):next(generator)
    def test_path_switch_can_revisit_earlier_real_frame(self):
        other=fixtures.video_fixture(self.temp/'other.mp4')
        canvas=media.display_canvas(self.source['video'])
        images=[f.to_image().tobytes() for f in assembly.selected_frames([(self.video,7),(other,2),(self.video,0)],canvas)]
        self.assertEqual(len(images),3);self.assertNotEqual(images[0],images[2])
    def test_actual_vfr_silent_reused_after_injected_mux_failure(self):
        original=fixtures.video_fixture(self.temp/'vfr.mp4',pts=[0,1,3,4,7,8,11,12])
        info=media.inspect(original);assign=[(original,i) for i in range(8)];out=self.temp/'final.mp4'
        before=media.signature(original)
        with patch.object(assembly,'remux',side_effect=RuntimeError('Injected local mux interruption')):
            with self.assertRaises(RuntimeError):media.assemble(original,info['video'],assign,out)
        self.assertFalse(out.exists());self.assertTrue(out.with_suffix('.silent.proof.json').exists())
        with patch.object(assembly,'encode',side_effect=AssertionError('Mux retry must not re-encode')):
            report=media.assemble(original,info['video'],assign,out)
        self.assertTrue(report['assembly_session']['complete_silent_reused'])
        self.assertEqual(report['visual_status'],'pending');self.assertEqual(media.signature(original),before)
        self.assertEqual([f['time'] for f in report['video']['frames']],[f['time'] for f in info['video']['frames']])
    def test_truncated_silent_is_never_reused(self):
        out=self.temp/'interrupted.mp4';assign=[(self.video,i) for i in range(8)]
        with patch.object(assembly,'remux',side_effect=RuntimeError('Injected failure')):
            with self.assertRaises(RuntimeError):media.assemble(self.video,self.source['video'],assign,out)
        silent=out.with_suffix('.silent.mp4');data=silent.read_bytes();silent.write_bytes(data[:len(data)//2])
        with self.assertRaisesRegex(ValueError,'Silent video incomplete'):media.assemble(self.video,self.source['video'],assign,out)
    def test_source_evidence_rejects_current_run_proof(self):
        factory.write(self.project/'evidence/cost.json',{'kind':'rh-cost-audit'})
        with self.assertRaises(ValueError):factory.build_skill(self.project,self.temp/'skills')
    def test_new_dedicated_skill_and_new_run_inherit_current_modification_policy(self):
        self.queue();built=factory.build_skill(self.project,self.temp/'policy-skills',display_name='新生成规则测试')
        features=factory.read(Path(built['path'])/'features.json')
        self.assertEqual(features['modification_method'],'regenerate')
        self.assertEqual(features['generation_duration_caps'],{'quality_le_1':15,'quality_gt_1':10,'unspecified':10})
        run=self.temp/'policy-new-run';factory.instantiate(built['path'],run)
        self.assertEqual(factory.read(run/'job.json')['modification_method'],'regenerate')
        self.assertEqual(factory.read(run/'job.json')['profile'],{})

    def test_runtime_revision_and_extracted_skill_inherit_new_tools(self):
        self.queue();skills=self.temp/'skills';first=factory.build_skill(self.project,skills,display_name='合成动作换角')
        manifest=factory.read(Path(first['path'])/'manifest.json')
        manifest['runtime_digest']='old-runtime';factory.write(Path(first['path'])/'manifest.json',manifest)
        upgraded=factory.build_skill(self.project,skills,upgrade_runtime=True)
        self.assertFalse(upgraded['reused']);self.assertNotEqual(first['name'],upgraded['name'])
        self.assertTrue(Path(first['path']).exists());self.assertEqual(upgraded['display_name'],'合成动作换角')
        with zipfile.ZipFile(upgraded['zip']['path']) as archive:
            for module in ['assembly_session.py','pilot_scope.py','cost_audit.py']:
                self.assertIn(upgraded['name']+'/scripts/'+module,archive.namelist())
            self.assertFalse(any('pilot-approvals.json' in n or 'cost-report' in n for n in archive.namelist()))
            archive.extractall(self.temp/'extracted')
        folder=self.temp/'extracted'/upgraded['name'];run=self.temp/'independent-run'
        result=subprocess.run([sys.executable,'-B','-X','utf8',str(folder/'scripts/factory.py'),'instantiate','--skill',str(folder),'--project',str(run)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(factory.read(run/'job.json')['references'],{})
        self.assertFalse((run/'pilot-approvals.json').exists())

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--work');a=ap.parse_args()
    work=Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix='factory-upgrade-regressions-'));work.mkdir(parents=True,exist_ok=True)
    fixtures.WORK=work
    socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Offline tests prohibit networking'))
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReliabilityTests))
    factory.write(work/'results.json',{'tests':result.testsRun,'passed':result.wasSuccessful(),'cloud_calls':0})
    raise SystemExit(not result.wasSuccessful())

if __name__=='__main__':main()
