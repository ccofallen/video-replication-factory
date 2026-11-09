"""Local RunningHub workflow 2117403951334162433 adapter.

prepare is offline; check is read-only. Only submit creates paid work, using a
byte-bound reviewed request and the factory's shared account ledger.
"""
from __future__ import annotations
import argparse
import copy
import datetime
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.error
import urllib.request
import uuid

ROOT=Path(os.environ.get('AI_VIDEO_GENERATION_ROOT',str(Path.home()/'ai_video_generation')))
local_scripts=Path(__file__).resolve().parent
sys.path.insert(0,str(local_scripts) if (local_scripts/'factory.py').is_file() else
    os.environ.get('AI_VIDEO_FACTORY_SCRIPTS',str(ROOT/'video-replication-factory/scripts')))
import rh_runner as rh
import media

WORKFLOW_ID='2117403951334162433'
DEFAULT_CONFIG=ROOT/'workflows'/('runninghub-'+WORKFLOW_ID)/'connection.json'
ASPECTS={'1:1':'1:1 (Square)','2:3':'2:3 (Portrait Photo)','3:2':'3:2 (Photo)',
         '3:4':'3:4 (Portrait Standard)','4:3':'4:3 (Standard)',
         '9:16':'9:16 (Portrait Widescreen)','16:9':'16:9 (Widescreen)','21:9':'21:9 (Ultrawide)'}
FORMULA='max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17'
REFERENCE_BINDINGS=[{'source':'reference','index':0,'node_id':'51','input':'image'},
                    {'source':'reference','index':1,'node_id':'49','input':'image'}]


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,path)


def graph(config):
    if config.get('site')!=rh.BASE or config.get('workflow_id')!=WORKFLOW_ID:
        raise ValueError('This local adapter is bound to the verified overseas workflow')
    value=read(config['local_workflow_path'])
    expected={'27':'VHS_LoadVideo','49':'LoadImage','51':'LoadImage','250':'ComfyMathExpression',
              '252':'ResolutionSelector','259':'PrimitiveFloat','263':'Text',
              '265':'MiniMaxH3ReferenceToVideo','364':'VHS_VideoCombine','397':'SelfLiftH3Sampler'}
    if any(value.get(k,{}).get('class_type')!=v for k,v in expected.items()):
        raise ValueError('Workflow node definitions changed; re-inspect the adapter bindings')
    inputs=value['265']['inputs']
    if (inputs.get('ref_images.ref_image_0')!=['51',0] or
        inputs.get('ref_images.ref_image_1')!=['49',0] or
        inputs.get('ref_videos.ref_video_0')!=['27',0] or inputs.get('prompt')!=['263',0] or
        inputs.get('length')!=['250',1] or value['250']['inputs'].get('expression')!=FORMULA or
        value['250']['inputs'].get('values.a')!=['259',0] or
        value['364']['inputs'].get('frame_rate')!=24):
        raise ValueError('Workflow reference order or frame clock changed; re-inspection required')
    return value


def generation_frames(seconds, quality_level=None):
    try:value=Fraction(str(seconds))
    except (ValueError,ZeroDivisionError):raise ValueError('Invalid source segment duration') from None
    import factory
    cap=factory.generation_duration_cap({} if quality_level is None else {'quality_level':quality_level})
    if value<=0 or value>cap:raise ValueError(f'Source segment must be positive and at most {cap} seconds')
    # Round UP the actual media duration before applying this workflow's 5 mod17
    # lattice. Never truncate source poses; all padding counts toward the cap.
    n=max(5,math.ceil(value*24));n+=(5-n%17)%17
    if Fraction(n,24)>cap:raise ValueError(f'Padded generation exceeds {cap} seconds; split at an earlier reviewed action boundary')
    return n


def staged_copy(source,target):
    source=Path(source).resolve();target=Path(target)
    if not source.is_file():raise ValueError('Input asset is missing')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if rh.sha(source)!=rh.sha(target):raise ValueError('Existing request assets are never overwritten; use a new window ID')
    else:shutil.copy2(source,target)
    return target


def prepare(config,project,window,video,images,prompt_file,seed,aspect_ratio=None,megapixels=None,instance_type='plus'):
    snapshot=graph(config)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',window):raise ValueError('Invalid window ID')
    if len(images)!=2:raise ValueError('This graph needs exactly two ordered reference images')
    if type(seed) is not int or not 0<=seed<2**64:raise ValueError('Explicit seed must be an unsigned 64-bit integer')
    if instance_type not in ('default','plus','ultra'):raise ValueError('Unsupported instance type')
    text=Path(prompt_file).read_text(encoding='utf-8-sig')
    if not text.strip():raise ValueError('A current reviewed prompt is required; the exported example is never a default')
    video_digest=rh.sha(video)
    image_digests=[rh.sha(p) for p in images]
    info=media.inspect(Path(video))['video']
    if not info.get('cfr') or Fraction(info['fps'])!=24:
        raise ValueError('Prepare an explicitly reviewed 24fps derived input using the factory media tools')
    seconds=Fraction(info['end_time'])-Fraction(info['start_time'])
    canvas=media.display_canvas(info)
    ratio=Fraction(canvas['width'],canvas['height'])*Fraction(canvas['sample_aspect_ratio'])
    selected=next((v for k,v in ASPECTS.items() if Fraction(k.replace(':','/'))==ratio),None)
    if not selected or (aspect_ratio and aspect_ratio!=selected):
        raise ValueError('Aspect ratio must match the measured source display canvas')
    mp=snapshot['252']['inputs']['megapixels'] if megapixels is None else megapixels
    if type(mp) not in (float,int) or not math.isfinite(mp) or not 0.1<=mp<=16:
        raise ValueError('Megapixels must be finite and between 0.1 and 16')
    frames=generation_frames(seconds,mp)
    from PIL import Image
    for image in images:
        with Image.open(image) as loaded:loaded.verify()
    project=Path(project).resolve();folder=project/'rh-requests'/window
    bundle_path=folder/'request.json'
    if bundle_path.exists():raise FileExistsError('Prepared request exists; use a new window ID')
    folder.mkdir(parents=True,exist_ok=True)
    video_path=staged_copy(video,folder/('video'+Path(video).suffix))
    image_paths=[staged_copy(p,folder/(f'picture-{i+1}'+Path(p).suffix)) for i,p in enumerate(images)]
    if rh.sha(video_path)!=video_digest or [rh.sha(p) for p in image_paths]!=image_digests:
        raise ValueError('Source assets changed during media inspection/staging; prepare a new revision')
    prompt_path=folder/'prompt.txt';prompt_path.write_text(text,encoding='utf-8')
    workflow_path=folder/'workflow.json';save(workflow_path,snapshot)
    paths=[video_path,*image_paths,prompt_path,workflow_path]
    relative=lambda p:p.relative_to(project).as_posix()
    bundle={'schema_version':1,'adapter':'runninghub-custom-h3','project':str(project),
        'window_id':window,'workflow_id':WORKFLOW_ID,'workflow_digest':rh.digest_object(snapshot),
        'video':relative(video_path),'images':[relative(p) for p in image_paths],
        'prompt':relative(prompt_path),'workflow':relative(workflow_path),
        'files':{relative(p):rh.sha(p) for p in paths},
        'parameters':{'frames':frames,'fps':24,'content_seconds':str(seconds),
            'duration_seconds':float(Fraction(frames,24)),'aspect_ratio':selected,
            'megapixels':mp,'seed':seed,'instance_type':instance_type},
        'production_authorized':False,'visual_status':'pending'}
    bundle['digest']=rh.digest_object(bundle)
    save(bundle_path,bundle)
    return bundle_path,bundle


def verify_bundle(config,path,approved_digest):
    bundle=read(path);claimed=bundle.get('digest')
    if not claimed or claimed!=approved_digest or rh.digest_object({k:v for k,v in bundle.items() if k!='digest'})!=claimed:
        raise ValueError('Prepared request parameters changed or semantic review digest does not match')
    if bundle.get('adapter')!='runninghub-custom-h3' or bundle.get('workflow_id')!=WORKFLOW_ID:
        raise ValueError('Request belongs to another workflow')
    project=Path(bundle['project']).resolve()
    if not Path(path).resolve().is_relative_to(project):raise ValueError('Request is outside its project')
    for rel,expected in bundle['files'].items():
        if rh.sha(rh.asset(project,rel))!=expected:raise ValueError('Prepared request asset changed; prepare a new revision')
    if rh.digest_object(graph(config))!=bundle['workflow_digest']:
        raise ValueError('Configured workflow changed since request preparation')
    snapshot=read(rh.asset(project,bundle['workflow']))
    if rh.digest_object(snapshot)!=bundle['workflow_digest']:raise ValueError('Request workflow snapshot changed')
    params=bundle['parameters']
    if params['frames']!=generation_frames(params['content_seconds'],params['megapixels']) or params['fps']!=24:
        raise ValueError('Generation frame clock is outside the inspected workflow contract')
    import factory
    cap=factory.generation_duration_cap({'quality_level':params['megapixels']})
    if Fraction(str(params['duration_seconds']))>cap:raise ValueError(f'Generation exceeds {cap} seconds')
    if abs(Fraction(str(params['duration_seconds']))-Fraction(params['frames'],24))>Fraction(1,10**12):
        raise ValueError('Node duration must match the reviewed generation frame clock')
    return bundle


def build_request(config,bundle,uploads,project):
    snapshot=copy.deepcopy(read(rh.asset(project,bundle['workflow'])))
    params=bundle['parameters']
    replacements=[('27','video',uploads['video']),('51','image',uploads['images'][0]),
        ('49','image',uploads['images'][1]),('263','text',rh.asset(project,bundle['prompt']).read_text(encoding='utf-8')),
        ('259','value',params['duration_seconds']),('252','aspect_ratio',params['aspect_ratio']),
        ('252','megapixels',params['megapixels']),('397','seed',params['seed']),('364','frame_rate',24)]
    nodes=[]
    for node,field,value in replacements:
        snapshot[node]['inputs'][field]=value
        nodes.append({'nodeId':node,'fieldName':field,'fieldValue':value})
    import physical_contract
    if physical_contract.enabled(project):
        entry=factory_entry(project,bundle['window_id'])
        physical_contract.validate_sampler(snapshot,physical_contract.sampler_settings(
            project,entry['source_contract']['window'],entry['profile']))
    return {'workflowId':WORKFLOW_ID,'workflow':json.dumps(snapshot,ensure_ascii=False),
            'nodeInfoList':nodes,'instanceType':params['instance_type'],'usePersonalQueue':False}


def create_profile(config,project,seed,instance_type='plus'):
    snapshot=graph(config);project=Path(project).resolve()
    target=project/'private-workflows'/('runninghub-'+WORKFLOW_ID+'.json')
    if target.exists() and read(target)!=snapshot:raise ValueError('Existing workflow snapshot differs; use a new run/revision')
    save(target,snapshot)
    return {'kind':'runninghub-workflow','workflow_id':WORKFLOW_ID,
        'workflow_path':target.relative_to(project).as_posix(),'workflow_digest':rh.digest_object(snapshot),
        'seed':seed,'instance_type':instance_type,'megapixels':snapshot['252']['inputs']['megapixels'],
        'bindings':copy.deepcopy(REFERENCE_BINDINGS),
        'limits':{'fps':['24'],'reference_slots':2,'identity_slots':2},'quality_evidence':'requires-production-pilot'}


def validate_profile(project,profile):
    if profile.get('kind')!='runninghub-workflow' or profile.get('workflow_id')!=WORKFLOW_ID:
        raise ValueError('Unsupported custom RunningHub workflow profile')
    path=rh.asset(project,profile['workflow_path'])
    snapshot=graph({'site':rh.BASE,'workflow_id':WORKFLOW_ID,'local_workflow_path':str(path)})
    if rh.digest_object(snapshot)!=profile.get('workflow_digest'):
        raise ValueError('Current custom workflow differs from its reviewed profile')
    if profile.get('bindings',REFERENCE_BINDINGS)!=REFERENCE_BINDINGS:
        raise ValueError('Custom reference bindings must match actual 51.image then 49.image order')
    return snapshot


def validate_factory_window(project,profile,window):
    validate_profile(project,profile)
    import factory
    frames=window.get('generation_frames')
    cap=factory.generation_duration_cap(profile)
    factory.validate_generation_duration(window,profile)
    if (type(frames) is not int or frames<5 or frames%17!=5 or frames>cap*24 or
        Fraction(window['generation_fps'])!=24):
        raise ValueError(f'Custom workflow generation needs 5 mod17 frames at24fps, with complete output <={cap} seconds')
    import media_references
    rows=media_references.resolve_inputs(project,read(Path(project)/'job.json'),window)
    if len(rows)!=2:raise ValueError('Custom workflow needs exactly two explicitly declared image references; human roles are independent')
    factory.validate_media_bindings(rows,profile)


def factory_entry(project,window):
    import factory
    queue=factory.read(Path(project)/'queue.json')
    entry=next((e for e in queue['jobs'] if e['window_id']==window),None)
    if not entry or entry.get('profile',{}).get('kind')!='runninghub-workflow':
        raise ValueError('A current factory queue entry for this custom workflow is required')
    if factory.compute_input_digest(project,entry)!=entry.get('input_digest'):
        raise ValueError('Current factory inputs changed; prepare and review them again')
    return entry


def prepare_factory(config,project,window):
    project=Path(project).resolve();entry=factory_entry(project,window);profile=entry['profile']
    validate_factory_window(project,profile,entry['source_contract']['window'])
    images=[rh.asset(project,p) for p in entry['reference_paths']]
    if len(images)!=2:
        raise ValueError('Declare two purpose-scoped references for this workflow; do not duplicate a person to fill slots')
    path,bundle=prepare(config,project,window,rh.asset(project,entry['video_path']),images,
        rh.asset(project,entry['prompt_path']),seed=profile['seed'],megapixels=profile['megapixels'],
        instance_type=profile.get('instance_type','plus'))
    if bundle['parameters']['frames']!=entry['generation_frames']:
        raise ValueError('Prepared media duration does not match the factory window generation clock')
    bundle['factory_input_digest']=entry['input_digest']
    bundle['digest']=rh.digest_object({k:v for k,v in bundle.items() if k!='digest'})
    save(path,bundle)
    return path,bundle


def factory_preflight(config,bundle):
    if not bundle.get('factory_input_digest'):raise ValueError('Only a reviewed factory-linked bundle may submit; use prepare-factory')
    project=Path(bundle['project']);entry=factory_entry(project,bundle['window_id']);profile=entry['profile']
    if entry['input_digest']!=bundle['factory_input_digest']:
        raise ValueError('Factory semantic input digest changed since adapter preparation')
    rh.preflight(project,entry)
    expected_images=list(entry['reference_paths'])
    if len(expected_images)==1:expected_images*=2
    for original,staged in [(entry['video_path'],bundle['video']),(entry['prompt_path'],bundle['prompt']),*zip(expected_images,bundle['images'])]:
        if rh.sha(rh.asset(project,original))!=rh.sha(rh.asset(project,staged)):
            raise ValueError('Adapter assets differ from the reviewed factory queue')
    params=bundle['parameters']
    canvas=entry['source_contract']['window']['source_projection']['display_canvas']
    ratio=Fraction(canvas['width'],canvas['height'])*Fraction(canvas.get('sample_aspect_ratio','1'))
    aspect=next((v for k,v in ASPECTS.items() if Fraction(k.replace(':','/'))==ratio),None)
    if not aspect or params['aspect_ratio']!=aspect:
        raise ValueError('Adapter aspect differs from the reviewed factory source canvas')
    if (params['frames']!=entry['generation_frames'] or params['seed']!=profile['seed'] or
        params['megapixels']!=profile['megapixels'] or params['instance_type']!=profile.get('instance_type','plus') or
        bundle['workflow_digest']!=profile['workflow_digest']):
        raise ValueError('Adapter parameters differ from the reviewed factory queue')
    return entry


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class WorkflowTransport(rh.Transport):
    def request(self,path,body=None,file=None):
        allowed={'/api/openapi/getJsonApiFormat','/task/openapi/create','/task/openapi/status',
                 '/task/openapi/outputs','/openapi/v2/media/upload/binary'}
        if path not in allowed:raise ValueError('Unsupported workflow endpoint')
        if file is None:
            payload={**(body or {}),'apiKey':self.key}
            data=json.dumps(payload,ensure_ascii=False).encode();content_type='application/json'
        else:
            boundary='----factory'+uuid.uuid4().hex
            name=Path(file).name.replace('"','_').replace('\r','_').replace('\n','_')
            data=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
            data+=Path(file).read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
            content_type='multipart/form-data; boundary='+boundary
        request=urllib.request.Request(rh.BASE+path,data=data,headers={
            'Authorization':'Bearer '+self.key,'Content-Type':content_type},method='POST')
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=45) as response:
                obj=json.load(response)
        except urllib.error.HTTPError as error:
            # Error text may contain signed URLs; expose only its code.
            if error.code>=500:code=error.code
            else:
                try:code=json.loads(error.read()).get('code',error.code)
                except Exception:code=error.code
            raise rh.ApiFailure(code) from None
        return json.loads(json.dumps(obj).replace(self.key,'[REDACTED]'))

    def workflow(self,workflow_id):
        obj=self.request('/api/openapi/getJsonApiFormat',{'workflowId':workflow_id})
        if str(obj.get('code')) not in ('0','200'):raise rh.ApiFailure(obj.get('code'))
        value=(obj.get('data') or {}).get('prompt')
        if not value:raise ValueError('Workflow query returned no graph')
        return json.loads(value) if isinstance(value,str) else value

    def query(self,task_id):
        status=self.request('/task/openapi/status',{'taskId':task_id})
        code=status.get('code')
        if str(code) not in ('0','200'):
            if str(code) in ('804','813'):
                return {'taskId':task_id,'code':0,'status':'RUNNING' if str(code)=='804' else 'QUEUED'}
            return {'taskId':task_id,'code':code,'provider_status':status}
        state=status.get('data')
        if state!='SUCCESS':return {'taskId':task_id,'code':0,'status':state,'provider_status':status}
        outputs=self.request('/task/openapi/outputs',{'taskId':task_id})
        code=outputs.get('code')
        if str(code) not in ('0','200'):
            return {'taskId':task_id,'code':code,'provider_outputs':outputs}
        values=outputs.get('data')
        if not isinstance(values,list):raise ValueError('Successful workflow outputs must be a list')
        return {'taskId':task_id,'code':0,'status':'SUCCESS','provider_outputs':outputs,
                'results':[{'url':v['fileUrl'],'outputType':v.get('fileType',''),'nodeId':'364'}
                           for v in values if str(v.get('nodeId'))=='364' and v.get('fileUrl')]}


def submit_bundle(config,path,approved_digest,production_request,ledger,transport):
    if not isinstance(production_request,str) or not production_request.strip():
        raise ValueError('A current human production request must be recorded')
    bundle=verify_bundle(config,path,approved_digest)
    factory_preflight(config,bundle)
    project=Path(bundle['project']);window=bundle['window_id']
    prior=ledger.db.execute('SELECT digest FROM attempts WHERE account=? AND project=? AND window=? AND task_id IS NOT NULL LIMIT 1',
        ('default',str(project),window)).fetchone()
    if prior and prior['digest']!=approved_digest:raise ValueError('Accepted inputs are immutable; use a new window ID')
    if not ledger.can_submit('default',project,window,approved_digest,block_uncertain=True):return None
    if rh.digest_object(transport.workflow(WORKFLOW_ID))!=bundle['workflow_digest']:
        raise ValueError('Cloud workflow changed since preparation; inspect and prepare a new revision')
    uploaded={}
    def upload(rel):
        file=rh.asset(project,rel);digest=rh.sha(file)
        if digest not in uploaded:uploaded[digest]=transport.upload(file)
        return uploaded[digest]['filename']
    refs=[upload(p) for p in bundle['images']];video=upload(bundle['video'])
    verify_bundle(config,path,approved_digest)
    factory_preflight(config,bundle)
    body=build_request(config,bundle,{'images':refs,'video':video},project)
    aid=ledger.reserve('default',project,window,approved_digest,block_uncertain=True)
    if not aid:return None
    ledger.update(aid,request=json.dumps({'path':'/task/openapi/create','body':body,
        'reviewed_digest':approved_digest,'production_request':production_request},ensure_ascii=False))
    try:
        result=transport.submit('/task/openapi/create',body)
    except rh.ApiFailure as error:
        if error.code in ('400','401','402','403','1913','1014')+rh.DEFERRED_CODES:
            rh.Runner(ledger,transport).submission_rejected(aid,error.code)
            if error.code=='1014':ledger.stop('default')
        else:ledger.update(aid,state='SUBMISSION_UNKNOWN')
        return aid
    except Exception:
        ledger.update(aid,state='SUBMISSION_UNKNOWN');return aid
    tid=(result.get('data') or {}).get('taskId') or result.get('taskId')
    if not tid:
        code=str(result.get('errorCode') or result.get('code'))
        if code in ('400','401','402','403','1913','1014')+rh.DEFERRED_CODES:
            rh.Runner(ledger,transport).submission_rejected(aid,code)
            if code=='1014':ledger.stop('default')
        else:ledger.update(aid,state='SUBMISSION_UNKNOWN')
        ledger.update(aid,receipt=json.dumps(result));return aid
    state=(result.get('data') or {}).get('taskStatus')
    ledger.update(aid,task_id=str(tid),state=state if state in ('RUNNING','QUEUED') else 'RUNNING',
        receipt=json.dumps(result),next_poll=ledger.clock()+5)
    return aid


def check(config,transport):
    snapshot=graph(config);remote=transport.workflow(WORKFLOW_ID)
    if remote!=snapshot:raise ValueError('Cloud workflow differs from the inspected local export')
    return {'authenticated':True,'workflow_id':WORKFLOW_ID,'node_count':len(remote),
            'exact_graph_match':True,'workflow_digest':rh.digest_object(remote),
            'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'generation_submitted':False}


def recover_attempt(ledger,transport,attempt,task_id=None):
    row=ledger.row(attempt);request=json.loads(row['request'] or '{}')
    if (row['account']!='default' or request.get('path')!='/task/openapi/create' or
        request.get('body',{}).get('workflowId')!=WORKFLOW_ID):
        raise ValueError('Attempt belongs to another backend/account; use its original runner')
    if row['state'] in ('SUBMITTING','SUBMISSION_UNKNOWN'):
        if not task_id:raise ValueError('Reconcile the uncertain attempt using the task ID from account history; do not resubmit')
        receipt=transport.query(task_id)
        if str(receipt.get('code')) not in ('0','200'):raise rh.ApiFailure(receipt.get('code'))
        if receipt.get('taskId')!=task_id or receipt.get('status') not in ('QUEUED','RUNNING','SUCCESS','FAILED'):
            raise ValueError('Task ID was not positively verified; the attempt remains uncertain')
        ledger.update(attempt,task_id=task_id,state='RUNNING',receipt=json.dumps(receipt),next_poll=0)
    rh.Runner(ledger,transport).recover(attempt)
    return attempt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('check');sub.add_parser('status')
    prep=sub.add_parser('prepare');prep.add_argument('--project',type=Path,required=True)
    prep.add_argument('--window',required=True);prep.add_argument('--video',type=Path,required=True)
    prep.add_argument('--image',type=Path,action='append',required=True)
    prep.add_argument('--prompt-file',type=Path,required=True);prep.add_argument('--seed',type=int,required=True)
    prep.add_argument('--aspect-ratio');prep.add_argument('--megapixels',type=float)
    prep.add_argument('--instance-type',choices=('default','plus','ultra'),default='plus')
    bridge=sub.add_parser('prepare-factory');bridge.add_argument('--project',type=Path,required=True);bridge.add_argument('--window',required=True)
    profile=sub.add_parser('profile');profile.add_argument('--project',type=Path,required=True);profile.add_argument('--seed',type=int,required=True)
    profile.add_argument('--instance-type',choices=('default','plus','ultra'),default='plus')
    submit=sub.add_parser('submit');submit.add_argument('--request',type=Path,required=True)
    submit.add_argument('--approve-digest',required=True);submit.add_argument('--production-request',required=True)
    recover=sub.add_parser('recover');recover.add_argument('--attempt',required=True);recover.add_argument('--task-id')
    args=parser.parse_args();ledger=None
    try:
        config=read(args.config)
        if args.command=='profile':
            print(json.dumps(create_profile(config,args.project,args.seed,args.instance_type),ensure_ascii=False,indent=2));return
        if args.command in ('prepare','prepare-factory'):
            if args.command=='prepare-factory':path,bundle=prepare_factory(config,args.project,args.window)
            else:path,bundle=prepare(config,args.project,args.window,args.video,args.image,args.prompt_file,args.seed,
                    args.aspect_ratio,args.megapixels,args.instance_type)
            print(json.dumps({'request':str(path),'digest':bundle['digest'],'parameters':bundle['parameters'],
                'generation_submitted':False},ensure_ascii=False,indent=2));return
        if args.command=='status':
            if not (rh.default_private()/'tasks.sqlite').exists():
                print(json.dumps({'account':'default','active':0,'attempts':[]}));return
            ledger=rh.Ledger(rh.default_private()/'tasks.sqlite')
            print(json.dumps(ledger.summary('default'),ensure_ascii=False,indent=2));return
        key_path=Path(config['key_file']);key=key_path.read_text(encoding='utf-8-sig').strip()
        if not key or '\n' in key or '\r' in key:raise ValueError('Private key file must contain one nonempty line')
        key_path.chmod(0o600);transport=WorkflowTransport(key)
        if args.command=='check':
            report=check(config,transport);save(args.config.with_name('connection_verification.json'),report)
            print(json.dumps(report,ensure_ascii=False,indent=2));return
        private=rh.default_private();private.mkdir(parents=True,exist_ok=True,mode=0o700)
        ledger=rh.Ledger(private/'tasks.sqlite')
        if args.command=='submit':
            aid=submit_bundle(config,args.request,args.approve_digest,args.production_request,ledger,transport)
        else:
            aid=recover_attempt(ledger,transport,args.attempt,args.task_id)
        print(json.dumps({'attempt':aid,'account':ledger.summary('default')},ensure_ascii=False,indent=2))
    except Exception as error:
        reason=str(error) if isinstance(error,(ValueError,FileNotFoundError,FileExistsError)) else 'Inspect private task state; do not automatically resubmit'
        print(json.dumps({'status':'attention_required','error_type':type(error).__name__,'reason':reason},ensure_ascii=False))
        raise SystemExit(1) from None
    finally:
        if ledger is not None:ledger.close()


if __name__=='__main__':main()
