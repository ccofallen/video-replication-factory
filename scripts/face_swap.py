"""Disabled face-swap submission API; retain original-ID recovery and evidence tools.

Current production repairs regenerate complete affected video windows. No CLI,
public submit call or supplied validator enables a new face-swap request.
"""
from pathlib import Path
from fractions import Fraction
import sys
import json
import subprocess
import argparse
import shutil
import os
import media

ROOT=Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import factory
import rh_runner as rh

APP_NODES={
    '1911332072277929986':('10','11',[]),
    '1891737138617069570':('2','3',[('frame_load_cap','0'),('select_every_nth','1'),('skip_first_frames','0')]),
    '1872958921492389890':('3','51',[]),
    '1931791712199618561':('5','4',[]),
}

def nodes_for(profile, image, video):
    if profile.get('kind')!='reviewed-framewise-face-swap' or profile.get('app_id') not in APP_NODES:
        raise ValueError('Unknown face-swap application')
    image_node,video_node,controls=APP_NODES[profile['app_id']]
    return [{'nodeId':image_node,'fieldName':'image','fieldValue':image},
            {'nodeId':video_node,'fieldName':'video','fieldValue':video}]+[
            {'nodeId':video_node,'fieldName':name,'fieldValue':value} for name,value in controls]

def preflight(project,entry):
    raise ValueError('Regeneration-only policy: regenerate the affected complete video window; face-swap overlay submissions are disabled')


def _legacy_preflight(project,entry):
    project=Path(project)
    actual=factory.compute_input_digest(project,entry)
    if actual!=entry['input_digest']:
        raise ValueError('Face-swap inputs changed')
    semantic=entry.get('semantic_review',{})
    if semantic.get('status')!='passed' or semantic.get('input_digest')!=actual or not semantic.get('notes'):
        raise ValueError('Face-swap input semantics not reviewed')
    job=factory.read(project/'job.json')
    if entry.get('production_authorized') is not True or job.get('production_authorized') is not True:
        raise ValueError('No current production authorization')
    profile=entry['profile']
    if factory.generation_profile(profile)!=factory.generation_profile(job['profile']):
        raise ValueError('Face-swap queue/profile mismatch')
    nodes_for(profile,'image-placeholder','video-placeholder')
    if len(entry['reference_paths'])!=1 or entry['reference_paths'][0]!=job['references']['A']['path']:
        raise ValueError('Exactly one current identity photograph required')
    window=entry['source_contract']['window']
    factory.validate_generation_duration({**window,'generation_frames':entry['generation_frames'],'duration':entry['duration']})
    if Fraction(window['generation_fps'])!=24:
        raise ValueError('This measured route currently supports explicit24fps input only')
    for name in ('video_path','prompt_path'):
        rh.asset(project,entry[name])
    for name in entry['reference_paths']:
        rh.asset(project,name)
    schema_path=rh.asset(project,profile['schema_path'])
    if rh.sha(schema_path)!=profile['schema_sha256']:
        raise ValueError('Face-swap schema snapshot changed')
    schema=factory.read(schema_path)
    if str(schema.get('code')) not in ('0','200'):
        raise ValueError('Face-swap schema did not succeed')
    live={(n['nodeId'],n['fieldName']):n for n in schema['data']['nodeInfoList']}
    for node in nodes_for(profile,'image-placeholder','video-placeholder'):
        if (node['nodeId'],node['fieldName']) not in live:
            raise ValueError('Requested face-swap field not published')
    if entry['source_projection_review'].get('status')!='passed' or entry['source_projection_review'].get('input_digest')!=actual:
        raise ValueError('Face-swap frame ownership/input clock not reviewed')
    input_report=factory.read(project/'derived_inputs/current-input-proof.json')
    if input_report['input_signature']!=factory.file_signature(project,entry['video_path']):
        raise ValueError('Face-swap complete input report is stale')
    video=input_report['report']['video']
    if video['frame_count']!=entry['generation_frames'] or video['fps']!='24' or Fraction(video['end_time'])>10:
        raise ValueError('Actual complete face-swap input frame clock invalid')
    return actual

class ScalarTransport(rh.Transport):
    @staticmethod
    def _verify_download(temp):
        ffmpeg = os.environ.get('VIDEO_FACTORY_FFMPEG') or shutil.which('ffmpeg')
        if not ffmpeg:
            raise ValueError('ffmpeg is required for strict complete decode')
        command=[ffmpeg,'-nostdin','-v','error','-xerror','-cpuflags','0','-threads','1',
                 '-i',str(temp),'-map','0:v:0','-threads','1','-f','null','-']
        check=subprocess.run(command,capture_output=True,timeout=120)
        if check.returncode or check.stderr.strip():
            raise ValueError('Face-swap result failed strict scalar complete decode; .part preserved')

class Runner(rh.Runner):
    def submit_one(self,project,entry,validator=None):
        # The supported API is closed even when a caller supplies a validator.
        # Keep recovery of old accepted IDs in the inherited recovery methods.
        raise ValueError('Regeneration-only policy: regenerate the affected complete video window; face-swap overlay submissions are disabled')

    def tick_one_pilot(self,project,entry):
        rows=self.ledger.db.execute('SELECT id FROM attempts WHERE account=? AND state IN (?,?,?,?,?,?) ORDER BY created',
                                   (self.account,*rh.POLLABLE)).fetchall()
        for row in rows:
            self.recover(row['id'],defer_download=True)
        try:
            preflight(project,entry)
            if entry.get('pilot') is not True:
                raise ValueError('Prototype permits only isolated representative pilots')
            prior=self.ledger.db.execute('SELECT window FROM attempts WHERE account=? AND project=? AND window<>?',
                                        (self.account,str(Path(project).resolve()),entry['window_id'])).fetchone()
            if prior:
                raise ValueError('New app cannot expand before actual pilot qualification')
            self.submit_one(project,entry)
        finally:
            ready=self.ledger.db.execute("SELECT id FROM attempts WHERE account=? AND state IN ('RESULTS_READY','DOWNLOAD_FAILED') AND next_poll<=?",
                                         (self.account,self.ledger.clock())).fetchall()
            for row in ready:self.recover(row['id'])
        return self.ledger.summary(self.account)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=('tick-pilot',))
    ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--ledger',type=Path,default=rh.default_private()/'tasks.sqlite')
    ap.add_argument('--key-file',type=Path,default=rh.default_key());ap.add_argument('--account',default='default')
    args=ap.parse_args()
    ap.error('Regeneration-only policy: regenerate the affected video window instead of applying patches, overlays or face swaps')

if __name__=='__main__':main()
