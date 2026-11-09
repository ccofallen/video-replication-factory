"""Run-owned, authorized caption/audio layers; mechanical proofs never approve perception.

Config intervals are half-open. Only deterministic drawtext and one selected audio
excerpt are supported. Guards regenerate the complete lossless/encoded chain.
"""
from pathlib import Path
from fractions import Fraction
import hashlib
import json
import re
import subprocess
import tempfile
import factory as f
import media


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bound(project, artifact):
    require(isinstance(artifact, dict) and artifact.get('path'), 'Missing bound artifact')
    require(f.file_signature(project, artifact['path']) == artifact, 'Bound artifact changed')
    return f.resolve(project, artifact['path'])


def parent(project, base_record):
    record = base_record if base_record is not None else f.read(Path(project)/'reviews.json').get('final', {})
    require(record.get('technical', {}).get('status') == 'passed' and
            record.get('visual', {}).get('status') == 'passed', 'Current base technical/visual review must pass')
    require(record.get('composition_digest'), 'Current base composition is missing')
    bound(project, record.get('file_signature'))
    require(record.get('output_path') == record['file_signature']['path'], 'Current base output binding differs')
    return {k: record[k] for k in ('output_path', 'file_signature', 'composition_digest')}


def init(project, base_record=None, authorization=None, safe_areas=None, protected_product_regions=None,
         deps=None, scalar_cpu=False):
    project = Path(project);target = project/'postproduction.json'
    require(not target.exists(), 'Preserve existing postproduction configuration')
    config = {'schema_version': 1, 'mode': 'restricted-promotional', 'base': parent(project, base_record),
              'authorization': authorization or {}, 'safe_areas': safe_areas or [],
              'protected_product_regions': protected_product_regions or [], 'captions': [], 'audio': {'mode': 'preserve'}}
    # Deliberately no fabricated authorization or visual/listening verdicts.
    validate_config(project, base_record, deps, scalar_cpu, config=config)
    f.write(target, config)
    return config


def box(value, width, height):
    require(isinstance(value, list) and len(value) == 4 and all(type(v) is int for v in value), 'Invalid pixel rectangle')
    a,b,c,d = value
    require(0 <= a < c <= width and 0 <= b < d <= height, 'Pixel rectangle escapes native canvas')
    return value


def intersects(a,b):
    return max(a[0],b[0]) < min(a[2],b[2]) and max(a[1],b[1]) < min(a[3],b[3])


def validate_config(project, base_record=None, deps=None, scalar_cpu=False, config=None):
    project = Path(project);c = config if config is not None else f.read(project/'postproduction.json')
    require(set(c) == {'schema_version','mode','base','authorization','safe_areas','protected_product_regions','captions','audio'} and
            c.get('schema_version') == 1 and c.get('mode') == 'restricted-promotional', 'Unknown/unsupported postproduction mode or layer')
    require(c['base'] == parent(project, base_record), 'Postproduction base is stale')
    auth = c.get('authorization', {})
    require(auth.get('kind') == 'explicit-user' and auth.get('authorized_by') == 'user' and
            isinstance(auth.get('source_message'), str) and auth['source_message'].strip(), 'Explicit user authorization source message is required')
    require(isinstance(auth.get('scope'), list) and set(auth['scope']) <= {'captions','audio-replace'}, 'Invalid authorization scope')
    report = media.inspect(bound(project, c['base']['file_signature']), deps, scalar_cpu)
    v = report['video'];w,h = v['width'],v['height'];count = v['frame_count']
    require(Fraction(v['start_time']) == 0 and int(v.get('rotation', 0)) % 360 == 0, 'Unsupported base clock/display transform')
    areas = {};protected = []
    for area in c['safe_areas']:
        require(set(area) == {'name','box'} and area.get('name') and area['name'] not in areas, 'Invalid/repeated authorized safe area')
        areas[area['name']] = box(area['box'],w,h)
    for region in c['protected_product_regions']:
        require(set(region) <= {'box','frames'} and 'box' in region, 'Unsupported protected product region')
        protected.append((box(region['box'],w,h), interval(region.get('frames',[0,count]),count)))
    require(isinstance(c['captions'],list), 'Captions must be a list')
    for caption in c['captions']:
        require('captions' in auth['scope'], 'Caption authorization missing')
        require(set(caption) in ({'text','fontfile','font_size','color','x','y','pixel_rect','safe_area','frames'}, {'text','fontfile','font_size','color','x','y','pixel_rect','safe_area','times'}), 'Unknown/unsupported caption setting')
        require(isinstance(caption['text'],str) and caption['text'].strip() and '\x00' not in caption['text'], 'Caption text is empty/invalid')
        require(type(caption['font_size']) is int and 1 <= caption['font_size'] <= h, 'Caption font size invalid')
        require(re.fullmatch(r'#[0-9A-Fa-f]{6}',caption['color']) is not None, 'Caption color must be exact RGB hex')
        require(type(caption['x']) is int and type(caption['y']) is int, 'Caption position must be native integer pixels')
        bound(project,caption['fontfile']);rect = box(caption['pixel_rect'],w,h);frames = caption_interval(caption,v)
        require(not any(intersects(rect,r) and max(frames[0],t[0]) < min(frames[1],t[1]) for r,t in protected), 'Caption overlaps protected product region')
        safe = areas.get(caption['safe_area'])
        require(safe and safe[0] <= rect[0] < rect[2] <= safe[2] and safe[1] <= rect[1] < rect[3] <= safe[3], 'Caption escapes authorized safe area')
        require(rect[0] <= caption['x'] < rect[2] and rect[1] <= caption['y'] < rect[3], 'Caption origin outside pixel rectangle')
    audio = c['audio']
    if audio.get('mode') == 'preserve':
        require(set(audio) == {'mode'}, 'Unknown preserve-audio setting')
    else:
        require(audio.get('mode') == 'replace' and set(audio) == {'mode','source','excerpt','gain','fade_in','fade_out'}, 'Unknown/unsupported audio mode')
        require('audio-replace' in auth['scope'], 'Audio replacement authorization missing')
        path = bound(project,audio['source']);av = media.runtime(deps,scalar_cpu)
        with av.open(str(path)) as container:
            require(len(container.streams.audio) == 1, 'Replacement source must have exactly one audio track')
            track = container.streams.audio[0];samples = sum(frame.samples for frame in container.decode(track))
            duration = Fraction(samples,track.codec_context.sample_rate)
        excerpt = audio['excerpt'];target_duration = Fraction(v['end_time'])
        require(isinstance(excerpt,list) and len(excerpt) == 2, 'Invalid audio excerpt')
        a,b = map(seconds,excerpt)
        require(0 <= a < b <= duration and abs(b-a-target_duration) <= Fraction(1,48000), 'Audio excerpt must cover exact base duration without looping')
        require(finite(audio['gain']) and 0 <= audio['gain'] <= 8 and all(finite(audio[k]) and 0 <= audio[k] <= float(target_duration) for k in ('fade_in','fade_out')), 'Invalid audio gain/fades')
    return c


def finite(value):
    import math
    return type(value) in (int,float) and math.isfinite(value)


def seconds(value):
    require(finite(value) or (isinstance(value,str) and re.fullmatch(r'[0-9]{1,12}(?:/[1-9][0-9]{0,11})?',value)), 'Invalid rational seconds')
    return Fraction(str(value))


def interval(value,count):
    require(isinstance(value,list) and len(value) == 2 and all(type(x) is int for x in value) and 0 <= value[0] < value[1] <= count, 'Invalid half-open frame interval')
    return value


def caption_interval(caption,video):
    if 'frames' in caption:
        return interval(caption['frames'],video['frame_count'])
    times = caption.get('times')
    require(isinstance(times,list) and len(times) == 2 and all(finite(t) for t in times), 'Invalid caption time interval')
    a,b = [Fraction(str(t)) for t in times]
    require(0 <= a < b <= Fraction(video['end_time']), 'Caption time interval escapes base clock')
    selected = [i for i,frame in enumerate(video['frames']) if a <= Fraction(frame['time']) < b]
    require(selected, 'Caption time interval contains no source PTS')
    return [selected[0],selected[-1]+1]


def command(args):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(result.returncode == 0, 'FFmpeg failed: '+result.stderr.decode(errors='replace')[-1200:])
    return result.stdout


def ffargs(deps, scalar=False):
    args = [media.find_ffmpeg(deps),'-nostdin','-v','error','-threads','1','-filter_threads','1']
    return args + (['-cpuflags','0'] if scalar else [])


def quote(value):
    # ffmpeg filter grammar, not shell quoting; text itself always uses textfile.
    return str(value).replace('\\','\\\\').replace(':','\\:').replace("'", "'\\''")


def rgb_frames(path, deps=None, scalar_cpu=False):
    av = media.runtime(deps,scalar_cpu)
    with av.open(str(path)) as container:
        container.streams.video[0].codec_context.thread_count = 1
        for frame in container.decode(video=0):
            yield frame, frame.to_ndarray(format='rgb24')


def canonical(project,c,directory,deps,scalar):
    """An uncompressed RGB canvas is compared before any lossy final encode."""
    import numpy as np
    base = bound(project,c['base']['file_signature']);before = directory/'base.nut';after = directory/'captioned.nut'
    av = media.runtime(deps,scalar);report = media.inspect(base,deps,scalar);v = report['video']
    with av.open(str(before),'w',format='nut') as output:
        stream = output.add_stream('rawvideo',rate=Fraction(v['fps'] or 24));stream.width = v['width'];stream.height = v['height'];stream.pix_fmt = 'rgb24'
        stream.time_base = stream.codec_context.time_base = Fraction(v['time_base']);stream.codec_context.sample_aspect_ratio = Fraction(v['sample_aspect_ratio'])
        for source,array in rgb_frames(base,deps,scalar):
            frame = av.VideoFrame.from_ndarray(array,format='rgb24');frame.pts = source.pts;frame.time_base = source.time_base
            for packet in stream.encode(frame):output.mux(packet)
        for packet in stream.encode():output.mux(packet)
    filters = []
    for i,cap in enumerate(c['captions']):
        text = directory/f'text-{i}.txt';text.write_text(cap['text'],encoding='utf-8')
        a,b = caption_interval(cap,v)
        filters.append(f"drawtext=fontfile='{quote(bound(project,cap['fontfile']))}':textfile='{quote(text)}':expansion=none:fontsize={cap['font_size']}:fontcolor={cap['color']}:x={cap['x']}:y={cap['y']}:enable='between(n,{a},{b-1})'")
    command(ffargs(deps,scalar)+['-copyts','-i',str(before),'-map','0:v:0','-vf',','.join(filters+['format=rgb24','setsar='+v['sample_aspect_ratio']]),'-fps_mode','passthrough','-enc_time_base:v',v['time_base'],'-c:v','rawvideo','-pix_fmt','rgb24',str(after)])
    proof = {'outside_caption_rect_changed_pixels':0,'changed_caption_pixels':0,'frame_count':0,'canonical_rgb_sha256':[],'caption_frame_intervals':[caption_interval(cap,v) for cap in c['captions']]}
    left = iter(rgb_frames(before,deps,scalar));right = iter(rgb_frames(after,deps,scalar));count = v['frame_count']
    for number in range(count):
        a,one = next(left);b,two = next(right)
        require(Fraction(a.pts)*a.time_base == Fraction(b.pts)*b.time_base == Fraction(v['frames'][number]['time']), 'Canonical RGB PTS changed')
        mask = np.zeros(one.shape[:2],dtype=bool)
        for cap,active in zip(c['captions'],proof['caption_frame_intervals']):
            if active[0] <= number < active[1]:
                x0,y0,x1,y1 = cap['pixel_rect'];mask[y0:y1,x0:x1] = True
        changed = np.any(one != two,axis=2);outside = int(np.count_nonzero(changed & ~mask))
        require(outside == 0, 'Caption pixels changed outside declared pixel rectangles')
        proof['changed_caption_pixels'] += int(np.count_nonzero(changed));proof['frame_count'] += 1
        proof['canonical_rgb_sha256'].append(hashlib.sha256(two.tobytes()).hexdigest())
    require(next(left,None) is None and next(right,None) is None, 'Canonical RGB frame count changed')
    require(not c['captions'] or proof['changed_caption_pixels'] > 0, 'Declared captions did not render any visible pixels')
    return after,report,proof


def audio_fingerprint(path,deps,scalar):
    av = media.runtime(deps,scalar);tracks = []
    with av.open(str(path)) as container:
        for stream in container.streams.audio:
            tracks.append({'codec':stream.codec_context.name,'sample_rate':stream.codec_context.sample_rate,
                'layout':stream.codec_context.layout.name,'metadata':dict(stream.metadata),'disposition':int(stream.disposition)})
    # Decode each track separately: raw PCM muxers cannot multiplex tracks.
    decoded = []
    for index in range(len(tracks)):
        pcm = command(ffargs(deps,scalar)+['-i',str(path),'-map',f'0:a:{index}','-vn','-f','f32le','-acodec','pcm_f32le','-ar','48000','-ac','2','pipe:1'])
        decoded.append({'sha256':hashlib.sha256(pcm).hexdigest(),'sample_count':len(pcm)//8})
    return {'tracks':tracks,'packets':media.audio_packets(path,deps,scalar),'decoded_pcm':decoded}


def chain(project,c,directory,output,deps,scalar):
    import assembly_session
    canvas,report,proof = canonical(project,c,directory,deps,scalar);v = report['video']
    silent = directory/'encoded.mp4'
    assembly_session.encode(v,[(canvas,i) for i in range(v['frame_count'])],silent,deps,scalar)
    base = bound(project,c['base']['file_signature']);audio = c['audio']
    if audio['mode'] == 'preserve':
        result = assembly_session.remux(base,silent,output,v,deps,scalar)
        require(media.audio_packets(base,deps,scalar) == media.audio_packets(output,deps,scalar), 'Original audio packet preservation failed')
        proof['audio'] = {'mode':'preserve','original_packets_verified':True,'actual_track_fingerprint':audio_fingerprint(output,deps,scalar)}
    else:
        source = bound(project,audio['source']);start,end = audio['excerpt'];duration = float(Fraction(v['end_time']))
        start_sample = round(seconds(start)*48000);target_samples = round(Fraction(v['end_time'])*48000)
        filters = ['aresample=48000',f'atrim=start_sample={start_sample}:end_sample={start_sample+target_samples}','asetpts=PTS-STARTPTS',f"volume={audio['gain']}"]
        if audio['fade_in']:filters.append(f"afade=t=in:st=0:d={audio['fade_in']}")
        if audio['fade_out']:filters.append(f"afade=t=out:st={duration-audio['fade_out']}:d={audio['fade_out']}")
        pcm = directory/'selected.wav'
        command(ffargs(deps,scalar)+['-i',str(source),'-map','0:a:0','-af',','.join(filters),'-ar','48000','-ac','2','-c:a','pcm_f32le',str(pcm)])
        command(ffargs(deps,scalar)+['-copyts','-i',str(silent),'-i',str(pcm),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k',str(output)])
        result = media.inspect(output,deps,scalar);assembly_session.check_video(v,result)
        require(len(result['audio_streams']) == 1 and result['audio_streams'][0]['decoded_samples'] > 0, 'Replacement audio failed complete decode')
        selected = audio_fingerprint(pcm,deps,scalar)['decoded_pcm'][0]
        require(selected['sample_count'] == target_samples, 'Selected audio excerpt did not decode the exact requested sample interval')
        proof['audio'] = {'mode':'replace','selected_pcm':selected,'selected_source_samples':[start_sample,start_sample+target_samples],
            'renderer_chain_verified':True,'actual_track_fingerprint':audio_fingerprint(output,deps,scalar)}
    require([r['time'] for r in result['video']['frames']] == [r['time'] for r in v['frames']] and
            result['video']['sample_aspect_ratio'] == v['sample_aspect_ratio'], 'Final PTS/SAR changed')
    return result,proof


def renderer(deps,scalar):
    import assembly_session
    return {'postproduction_sha256':media.signature(__file__)['sha256'],
            'assembly_sha256':media.signature(assembly_session.__file__)['sha256'],
            'media_sha256':media.signature(media.__file__)['sha256'],
            'ffmpeg_sha256':media.signature(media.find_ffmpeg(deps))['sha256'],
            'backend':assembly_session.backend_identity(deps,scalar)}


def render(project,output,base_record=None,deps=None,scalar_cpu=False):
    project = Path(project).resolve();c = validate_config(project,base_record,deps,scalar_cpu)
    require(Path(output).name == output and Path(output).suffix == '.mp4', 'Postproduction output must be an MP4 filename')
    relative = 'outputs/'+output;destination = f.resolve(project,relative);directory = f.resolve(project,'postproduction/'+Path(output).stem)
    require(not destination.exists() and not directory.exists(), 'Preserve existing postproduction outputs/proofs')
    directory.mkdir(parents=True);destination.parent.mkdir(parents=True,exist_ok=True)
    report,proof = chain(project,c,directory,destination,deps,scalar_cpu)
    artifacts = [f.file_signature(project,path.relative_to(project).as_posix()) for path in sorted(directory.iterdir()) if path.is_file()]
    record_relative = (directory/'record.json').relative_to(project).as_posix()
    record = {'schema_version':1,'kind':'restricted-postproduction','record_path':record_relative,'output_path':relative,
        'file_signature':f.file_signature(project,relative),'base':c['base'],'configuration_digest':f.digest(c),
        'renderer':renderer(deps,scalar_cpu),'proof':proof,'artifacts':artifacts,
        'technical':{'status':'passed','report':report},'visual':{'status':'pending'},'listening':{'status':'pending'},
        'physical':{'status':'pending'},'user_acceptance':{'status':'pending'}}
    # Check that mutable inputs stayed fixed throughout the complete render.
    require(c == validate_config(project,base_record,deps,scalar_cpu), 'Configuration changed while rendering')
    f.write(project/record_relative,record)
    return record


def video_fingerprint(path,deps,scalar):
    return [hashlib.sha256(array.tobytes()).hexdigest() for _,array in rgb_frames(path,deps,scalar)]


def observed(record,key):
    review = record.get(key,{})
    require(review.get('status') == 'passed' and review.get('playback_rate') == 1 and review.get('notes') and
        review.get('file_signature') == record['file_signature'] and review.get('configuration_digest') == record['configuration_digest'] and
        review.get('proof_digest') == f.digest(record['proof']), f'Final {key} needs actual 1x observations bound to this output/configuration/proof')
    frames = range(record['technical']['report']['video']['frame_count'])
    if key == 'visual':
        require(review.get('native_resolution') is True, 'Final visual needs native-resolution observation')
        require(f.coverage(review.get('dynamic_intervals',[]),frames) and f.coverage(review.get('native_intervals',[]),frames), 'Final visual full-output coverage is missing')
    else:
        require(review.get('audio_enabled') is True, 'Final listening requires audible playback; muted visual review is insufficient')
        require(f.coverage(review.get('intervals',[]),frames), 'Final listening full-output coverage is missing')


def guard(project,record_relative,base_record=None,deps=None,scalar_cpu=False,require_reviews=True):
    project = Path(project).resolve();c = validate_config(project,base_record,deps,scalar_cpu)
    record = f.read(f.resolve(project,record_relative))
    require(record.get('schema_version') == 1 and record.get('kind') == 'restricted-postproduction' and record.get('record_path') == record_relative, 'Unknown postproduction proof record')
    require(record.get('base') == c['base'], 'Postproduction base changed')
    require(record.get('configuration_digest') == f.digest(c), 'Postproduction configuration changed after rendering')
    require(record.get('renderer') == renderer(deps,scalar_cpu), 'Postproduction renderer changed')
    actual = bound(project,record.get('file_signature'));require(record.get('output_path') == record['file_signature']['path'], 'Final video output binding differs')
    require(record.get('artifacts'), 'Missing canonical proof artifacts')
    for artifact in record['artifacts']:bound(project,artifact)
    with tempfile.TemporaryDirectory(prefix='post-check-',dir=project) as temporary:
        directory = Path(temporary);expected = directory/'expected.mp4'
        report,proof = chain(project,c,directory,expected,deps,scalar_cpu)
        require(proof == record.get('proof'), 'Canonical RGB/audio proof differs from verified renderer chain')
        artifacts = {a['path']:a for a in record['artifacts']}
        for name in ('base.nut','captioned.nut'):
            relative = (Path(record_relative).parent/name).as_posix()
            require(relative in artifacts, 'Missing canonical RGB proof artifact')
            retained = bound(project,artifacts[relative]);reference = directory/name
            require(video_fingerprint(retained,deps,scalar_cpu) == video_fingerprint(reference,deps,scalar_cpu) and
                    media.inspect(retained,deps,scalar_cpu)['video'] == media.inspect(reference,deps,scalar_cpu)['video'], 'Saved canonical RGB/clock proof differs from renderer')
        require(video_fingerprint(actual,deps,scalar_cpu) == video_fingerprint(expected,deps,scalar_cpu), 'Actual final video differs from verified renderer chain')
        require(audio_fingerprint(actual,deps,scalar_cpu) == audio_fingerprint(expected,deps,scalar_cpu), 'Actual final audio differs from verified renderer chain')
    actual_report = media.inspect(actual,deps,scalar_cpu)
    require(actual_report['video'] == report['video'], 'Actual final video clock/canvas/SAR report differs from verified renderer')
    if c['audio']['mode'] == 'preserve':actual_report['audio_packet_verification'] = 'passed'
    require(record.get('technical',{}).get('status') == 'passed' and record['technical'].get('report') == actual_report, 'Complete final technical report changed')
    require(c == validate_config(project,base_record,deps,scalar_cpu), 'Configuration changed during postproduction guard')
    require(f.file_signature(project,record['output_path']) == record['file_signature'] and
            f.read(f.resolve(project,record_relative)) == record, 'Postproduction output/review changed during guard')
    if require_reviews:
        observed(record,'visual');observed(record,'listening')
    return record
