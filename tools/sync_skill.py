"""Copy only the verified factory manifest into its dedicated Git checkout."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess
import verify_publish as guard

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--key-file')
    args=parser.parse_args()
    repo=Path(guard.git('rev-parse','--show-toplevel').decode().strip())
    if not guard.remote_ok(guard.git('remote','get-url','origin').decode().strip()):
        raise ValueError('Wrong repository; no files copied')
    policy=json.loads((repo/'publish-policy.json').read_text(encoding='utf8'))
    source=args.source.resolve()
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf8'))
    if manifest['name'] != guard.EXPECTED_SKILL:
        raise ValueError('Source is not video-replication-factory')
    keys=guard.known_keys(args.key_file)
    selected={}
    for name in [*manifest['files'],'manifest.json']:
        path=(source/name).resolve()
        if not path.is_relative_to(source) or name not in policy['runtime_files']:
            raise ValueError('Source manifest is outside the explicit factory whitelist')
        data=path.read_bytes()
        errors=guard.check_payload(name,data,keys)
        if errors:
            raise ValueError('\n'.join(errors))
        if name!='manifest.json' and hashlib.sha256(data).hexdigest()!=manifest['files'][name]:
            raise ValueError('Source manifest signature is stale: '+name)
        selected[name]=data
    # All source members are checked before the first copy; no recursive sync.
    for name in selected:
        target=repo/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,target)
    print('Synced '+str(len(selected))+' verified factory files. Git staging/push remains explicit.')

if __name__=='__main__':
    main()
