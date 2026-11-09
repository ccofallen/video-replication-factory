"""Real tiny fixtures: authorized promotional layers, never synthetic review approval."""
from pathlib import Path
from fractions import Fraction
import copy, importlib.util, json, math, os, struct, subprocess, tempfile, unittest, wave
import factory as f
import media
from test_factory import video_fixture
try:
    import postproduction as p
except ImportError:
    p = None

class PostproductionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(p, 'Restricted authorized postproduction module is missing')
        self.tmp=tempfile.TemporaryDirectory(prefix='postproduction-');self.project=Path(self.tmp.name)
        (self.project/'outputs').mkdir();base=self.project/'outputs/base.mp4'
        silent=video_fixture(self.project/'silent.mp4',fps=8,width=160,height=120)
        with wave.open(str(self.project/'music.wav'),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000)
            w.writeframes(b''.join(struct.pack('<h',int(6000*math.sin(2*math.pi*440*i/48000))) for i in range(96000)))
        subprocess.run([media.find_ffmpeg(),'-v','error','-i',str(silent),'-i',str(self.project/'music.wav'),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-t','1',str(base)],check=True)
        self.base={'output_path':'outputs/base.mp4','file_signature':f.file_signature(self.project,'outputs/base.mp4'),
            'composition_digest':'fixture-composition','technical':{'status':'passed','report':media.inspect(base)},
            'visual':{'status':'passed','notes':'Synthetic fixture condition only; no production observation.'}}
        f.write(self.project/'reviews.json',{'final':self.base})
        self.authorization={'kind':'explicit-user','source_message':'Add white MixedCase text below the product and use music.wav from 0.25 to 1.25 seconds at half gain with fades.',
                            'authorized_by':'user','scope':['captions','audio-replace']}
        p.init(self.project,authorization=self.authorization,safe_areas=[{'name':'below-product','box':[0,82,160,120]}],protected_product_regions=[{'box':[0,0,160,80]}])
        cfg=f.read(self.project/'postproduction.json')
        fonts=[Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
               Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
               Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arial.ttf']
        font=next((path for path in fonts if path.is_file()),None)
        self.assertIsNotNone(font,'A system TrueType font is required for real drawtext fixtures')
        import shutil
        shutil.copyfile(font,self.project/'font.ttf')
        cfg['captions']=[{'text':'MixedCase','fontfile':f.file_signature(self.project,'font.ttf'),'font_size':14,'color':'#FFFFFF',
            'x':4,'y':88,'pixel_rect':[2,84,135,116],'safe_area':'below-product','frames':[1,7]}]
        f.write(self.project/'postproduction.json',cfg)
    def tearDown(self):
        if hasattr(self,'tmp'):self.tmp.cleanup()
    def config(self,change):
        cfg=f.read(self.project/'postproduction.json');change(cfg);f.write(self.project/'postproduction.json',cfg)
    def render(self,name='promo.mp4'):
        return p.render(self.project,name)
    def mechanical(self,record):
        return p.guard(self.project,record['record_path'],require_reviews=False)
    def test_below_product_caption_renders_only_declared_rect_and_stays_pending(self):
        record=self.render();result=self.mechanical(record)
        self.assertEqual(result['technical']['status'],'passed')
        self.assertEqual(result['proof']['outside_caption_rect_changed_pixels'],0)
        self.assertGreater(result['proof']['changed_caption_pixels'],0)
        self.assertEqual(result['visual']['status'],'pending');self.assertEqual(result['listening']['status'],'pending')
        self.assertEqual(media.audio_packets(self.project/'outputs/base.mp4'),media.audio_packets(self.project/'outputs/promo.mp4'))
        with self.assertRaisesRegex(ValueError,'visual'):p.guard(self.project,record['record_path'])
        self.assertEqual(f.read(self.project/'reviews.json')['final'],self.base)
    def test_authorized_excerpt_gain_and_fades_bound_to_actual_audio(self):
        self.config(lambda c:c.update(audio={'mode':'replace','source':f.file_signature(self.project,'music.wav'),
            'excerpt':[0.25,1.25],'gain':0.5,'fade_in':0.1,'fade_out':0.2}))
        r=self.render();result=self.mechanical(r)
        self.assertEqual(result['proof']['audio']['mode'],'replace')
        self.assertEqual(result['proof']['audio']['renderer_chain_verified'],True)
        self.assertNotEqual(media.audio_packets(self.project/'outputs/base.mp4'),media.audio_packets(self.project/'outputs/promo.mp4'))
        self.assertEqual(result['listening']['status'],'pending')
    def test_missing_explicit_authorization_rejects(self):
        self.config(lambda c:c['authorization'].update(source_message=''))
        with self.assertRaisesRegex(ValueError,'authorization'):p.validate_config(self.project)
    def test_protected_product_overlap_rejects(self):
        self.config(lambda c:c['captions'][0].update(pixel_rect=[2,60,135,116]))
        with self.assertRaisesRegex(ValueError,'protected'):p.validate_config(self.project)
    def test_caption_outside_declared_safe_area_rejects(self):
        self.config(lambda c:c['captions'][0].update(pixel_rect=[2,80,135,116]))
        with self.assertRaisesRegex(ValueError,'safe area'):p.validate_config(self.project)
    def test_text_escaping_preserves_literal_case_and_colons(self):
        self.config(lambda c:c['captions'][0].update(text="Mix: Bob's 100%",font_size=10))
        self.mechanical(self.render())
    def test_changed_caption_config_invalidates_existing_post_only(self):
        r=self.render();self.config(lambda c:c['captions'][0].update(text='Changed'))
        with self.assertRaisesRegex(ValueError,'configuration'):self.mechanical(r)
        self.assertEqual(f.read(self.project/'reviews.json')['final'],self.base)
    def test_unknown_patch_layer_is_rejected(self):
        self.config(lambda c:c.update(patches=[{'box':[10,10,20,20]}]))
        with self.assertRaisesRegex(ValueError,'unsupported'):p.validate_config(self.project)
    def test_changed_base_composition_invalidates_post(self):
        r=self.render();reviews=f.read(self.project/'reviews.json');reviews['final']['composition_digest']='changed';f.write(self.project/'reviews.json',reviews)
        with self.assertRaisesRegex(ValueError,'base'):self.mechanical(r)
    def test_changed_music_file_invalidates_post(self):
        self.config(lambda c:c.update(audio={'mode':'replace','source':f.file_signature(self.project,'music.wav'),'excerpt':[0.25,1.25],'gain':0.5,'fade_in':0.1,'fade_out':0.2}))
        r=self.render()
        with (self.project/'music.wav').open('ab') as h:h.write(b'changed')
        with self.assertRaisesRegex(ValueError,'artifact|changed'):self.mechanical(r)
    def test_oversized_glyph_layer_outside_rect_rejects_before_lossy_encode(self):
        self.config(lambda c:c['captions'][0].update(font_size=50))
        with self.assertRaisesRegex(ValueError,'outside'):self.render()
    def test_replaced_video_and_forged_signature_still_rejected(self):
        r=self.render();record_path=self.project/r['record_path']
        import shutil
        shutil.copy2(self.project/'outputs/base.mp4',self.project/'outputs/promo.mp4')
        r['file_signature']=f.file_signature(self.project,'outputs/promo.mp4');f.write(record_path,r)
        with self.assertRaisesRegex(ValueError,'renderer|video|proof'):self.mechanical(r)
    def test_muted_visual_observation_cannot_stand_in_for_listening(self):
        r=self.render();r['visual']={'status':'passed','playback_rate':1,'native_resolution':True,'dynamic_intervals':[[0,8]],'native_intervals':[[0,8]],'notes':'Synthetic metadata contract exercise.',
            'file_signature':r['file_signature'],'configuration_digest':r['configuration_digest'],'proof_digest':f.digest(r['proof'])}
        f.write(self.project/r['record_path'],r)
        with self.assertRaisesRegex(ValueError,'listening'):p.guard(self.project,r['record_path'])
    def test_caption_time_interval_is_projected_to_current_pts(self):
        def change(c):
            c['captions'][0].pop('frames');c['captions'][0]['times']=[0.2,0.8]
        self.config(change)
        r=self.render();self.assertEqual(r['proof']['caption_frame_intervals'],[[2,7]])
        self.mechanical(r)
    def test_postproduction_directory_symlink_cannot_escape_run(self):
        with tempfile.TemporaryDirectory(prefix='post-outside-') as other:
            (self.project/'postproduction').symlink_to(other,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'escapes|contained'):self.render()
            self.assertEqual(list(Path(other).iterdir()),[])
    def test_font_path_punctuation_is_data_not_ffmpeg_syntax(self):
        old=self.project/'font.ttf';new=self.project/"font 'quoted':100%.ttf";old.rename(new)
        self.config(lambda c:c['captions'][0].update(fontfile=f.file_signature(self.project,new.name)))
        self.mechanical(self.render())
    def test_saved_canonical_evidence_cannot_be_substituted(self):
        r=self.render();canonical=self.project/Path(r['record_path']).parent/'captioned.nut'
        canonical.write_bytes((canonical.parent/'base.nut').read_bytes())
        r['artifacts']=[f.file_signature(self.project,a['path']) if a['path'].endswith('/captioned.nut') else a for a in r['artifacts']]
        f.write(self.project/r['record_path'],r)
        with self.assertRaisesRegex(ValueError,'canonical|proof'):self.mechanical(r)
    def test_vfr_clock_and_non_square_sample_aspect_ratio_are_retained(self):
        target=self.project/'outputs/base.mp4';target.unlink()
        video_fixture(target,fps=8,pts=[0,1,3,4,7,8,9,10],width=160,height=120,sar=Fraction(2))
        self.base['file_signature']=f.file_signature(self.project,'outputs/base.mp4')
        self.base['technical']['report']=media.inspect(target)
        f.write(self.project/'reviews.json',{'final':self.base})
        self.config(lambda c:c.update(base={k:self.base[k] for k in ('output_path','file_signature','composition_digest')}))
        r=self.render();self.mechanical(r)
        observed=r['technical']['report']['video'];expected=self.base['technical']['report']['video']
        self.assertEqual([x['time'] for x in observed['frames']],['0','1/8','3/8','1/2','7/8','1','9/8','5/4'])
        self.assertEqual(observed['end_time'],'11/8');self.assertEqual(observed['sample_aspect_ratio'],'2')
        self.assertEqual(observed['frame_count'],8)
    def test_forged_technical_report_cannot_hide_changed_final_sar(self):
        r=self.render();actual=self.project/r['output_path'];changed=self.project/'changed.mp4'
        subprocess.run([media.find_ffmpeg(),'-v','error','-i',str(actual),'-map','0','-c','copy','-aspect','16:9',str(changed)],check=True)
        actual.write_bytes(changed.read_bytes())
        r['file_signature']=f.file_signature(self.project,r['output_path'])
        report=media.inspect(actual);report['audio_packet_verification']='passed';r['technical']['report']=report
        f.write(self.project/r['record_path'],r)
        with self.assertRaisesRegex(ValueError,'canvas|SAR|clock|report'):self.mechanical(r)
    def test_rational_excerpt_supports_normal_24fps_duration(self):
        target=self.project/'outputs/base.mp4';target.unlink();video_fixture(target,fps=24,width=160,height=120)
        self.base['file_signature']=f.file_signature(self.project,'outputs/base.mp4');self.base['technical']['report']=media.inspect(target)
        f.write(self.project/'reviews.json',{'final':self.base})
        self.config(lambda c:c.update(base={k:self.base[k] for k in ('output_path','file_signature','composition_digest')},
            audio={'mode':'replace','source':f.file_signature(self.project,'music.wav'),'excerpt':[0,'1/3'],'gain':0.5,'fade_in':0.05,'fade_out':0.05}))
        r=self.render();self.mechanical(r)
        self.assertEqual(r['proof']['audio']['selected_source_samples'],[0,16000])
        self.assertEqual(r['proof']['audio']['selected_pcm']['sample_count'],16000)
    def test_preserve_multiple_original_audio_tracks(self):
        base=self.project/'outputs/base.mp4';changed=self.project/'multi.mp4'
        subprocess.run([media.find_ffmpeg(),'-v','error','-i',str(base),'-map','0:v','-map','0:a','-map','0:a','-c','copy',str(changed)],check=True)
        base.write_bytes(changed.read_bytes());self.base['file_signature']=f.file_signature(self.project,'outputs/base.mp4');self.base['technical']['report']=media.inspect(base)
        f.write(self.project/'reviews.json',{'final':self.base})
        self.config(lambda c:c.update(base={k:self.base[k] for k in ('output_path','file_signature','composition_digest')}))
        r=self.render();self.mechanical(r)
        self.assertEqual(len(r['proof']['audio']['actual_track_fingerprint']['tracks']),2)
        self.assertEqual(media.audio_packets(base),media.audio_packets(self.project/r['output_path']))
    def test_partial_visual_review_never_counts_as_full_observation(self):
        r=self.render();r['visual']={'status':'passed','playback_rate':1,'native_resolution':True,'notes':'Only one synthetic frame recorded.',
            'file_signature':r['file_signature'],'configuration_digest':r['configuration_digest'],'proof_digest':f.digest(r['proof']),
            'dynamic_intervals':[[0,1]],'native_intervals':[[0,1]]}
        f.write(self.project/r['record_path'],r)
        with self.assertRaisesRegex(ValueError,'visual.*coverage'):p.guard(self.project,r['record_path'])
    def test_config_change_during_complete_guard_rejects(self):
        from unittest.mock import patch
        r=self.render();original=p.video_fingerprint;changed=False
        def inspect_and_change(*args,**kwargs):
            nonlocal changed
            result=original(*args,**kwargs)
            if not changed:
                changed=True;self.config(lambda c:c['captions'][0].update(text='Changed while checking'))
            return result
        with patch.object(p,'video_fingerprint',side_effect=inspect_and_change):
            with self.assertRaisesRegex(ValueError,'configuration|Configuration'):self.mechanical(r)
    def test_saved_canonical_pts_cannot_be_forged_with_same_rgb(self):
        r=self.render();saved=self.project/Path(r['record_path']).parent/'captioned.nut';changed=self.project/'shifted.nut'
        subprocess.run([media.find_ffmpeg(),'-v','error','-itsoffset','0.125','-i',str(saved),'-copyts','-map','0:v','-c','copy',str(changed)],check=True)
        saved.write_bytes(changed.read_bytes())
        r['artifacts']=[f.file_signature(self.project,a['path']) if a['path'].endswith('/captioned.nut') else a for a in r['artifacts']]
        f.write(self.project/r['record_path'],r)
        with self.assertRaisesRegex(ValueError,'canonical|proof'):self.mechanical(r)
    @unittest.skipIf(os.name == 'nt', 'The enforcing executable shim is POSIX; native Windows scalar runtime is separate.')
    def test_scalar_ffmpeg_flags_reach_real_caption_and_audio_encode(self):
        from unittest.mock import patch
        import sys
        self.config(lambda c:c.update(audio={'mode':'replace','source':f.file_signature(self.project,'music.wav'),
            'excerpt':[0.25,1.25],'gain':0.5,'fade_in':0.1,'fade_out':0.2}))
        dependencies=self.project/'scalar-deps';(dependencies/'bin').mkdir(parents=True)
        executable=dependencies/'bin/ffmpeg-enforced.exe';actual=media.find_ffmpeg()
        executable.write_text('#!'+sys.executable+'\nimport os,sys\nargs=sys.argv[1:]\n'
            +'if not any(args[i:i+2]==["-cpuflags","0"] for i in range(len(args)-1)):\n'
            +' sys.stderr.write("scalar CPU flag did not reach actual FFmpeg process");sys.exit(64)\n'
            +'os.execv('+repr(actual)+',['+repr(actual)+',*args])\n')
        executable.chmod(0o755)
        native_runtime=media.runtime
        # Only Windows-specific PyAV CPU setup is unavailable here; every FFmpeg
        # child really executes with zero CPU flags, enforced by the executable.
        with patch.object(media,'runtime',side_effect=lambda deps=None,scalar_cpu=False:native_runtime(deps,False)):
            r=p.render(self.project,'scalar.mp4',deps=dependencies,scalar_cpu=True)
            checked=p.guard(self.project,r['record_path'],deps=dependencies,scalar_cpu=True,require_reviews=False)
        self.assertEqual(checked['technical']['report']['video']['frame_count'],8)
        self.assertEqual(checked['proof']['outside_caption_rect_changed_pixels'],0)
        self.assertEqual(checked['proof']['audio']['selected_pcm']['sample_count'],48000)
        self.assertEqual(checked['visual']['status'],'pending');self.assertEqual(checked['listening']['status'],'pending')
    def test_unpassed_base_rejects_render(self):
        reviews=f.read(self.project/'reviews.json');reviews['final']['visual']['status']='pending';f.write(self.project/'reviews.json',reviews)
        with self.assertRaisesRegex(ValueError,'base'):self.render()

if __name__=='__main__':unittest.main()
