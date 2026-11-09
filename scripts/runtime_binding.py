"""Bind a run to its actual source-specific runtime; no generation authority granted.

New operations require an exact runtime root, identity and production-code digest.
Unbound legacy runs and changed runtimes require explicit adopt/migrate with a user
source_message. Original-ID recovery and read-only diagnosis remain available.
Source capabilities accept a canonical list or {required_capabilities, files,
entrypoint, contract_initializer, guards}; declarations and source facts are bound
separately from target choices and review progress.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READ_ONLY = frozenset(('diagnose', 'status', 'recover', 'recover-unknown', 'query', 'download', 'inspect', 'list',
                       'cost-audit', 'validate-analysis', 'version-list', 'physical-check'))
CAPABILITY_FILES = {
    'runtime-binding': ('scripts/runtime_binding.py', 'scripts/run_skill.py'),
    'scoped-physical-contract': ('scripts/physical_contract.py',),
    'multi-purpose-references': ('scripts/media_references.py',),
    'conditional-production-policy': ('scripts/production_policy.py',),
    'restricted-postproduction': ('scripts/postproduction.py',),
    'structured-consistency': ('scripts/physical_source.py','scripts/consistency_review.py'),
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _sha(path):
    path = Path(path)
    if not path.is_file(): raise ValueError('Required runtime/source file is missing: ' + str(path))
    before = path.stat()
    value = hashlib.sha256(path.read_bytes()).hexdigest(); after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Runtime/source file changed during hashing')
    return value


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _path(root, name):
    root, path = Path(root).resolve(), Path(name)
    actual = (root / path).resolve()
    if path.is_absolute() or '..' in path.parts or not actual.is_relative_to(root):
        raise ValueError('Runtime/source contract paths must stay inside their root')
    return actual


def production_files(runtime_root=None):
    root = Path(runtime_root or ROOT).resolve()
    scripts = root / 'scripts'
    if not scripts.is_dir(): raise ValueError('Runtime scripts directory is missing')
    return {path.relative_to(root).as_posix(): _sha(_path(root, path.relative_to(root)))
            for path in sorted(scripts.rglob('*')) if path.is_file() and
            '__pycache__' not in path.parts and not path.name.startswith('test_') and
            path.suffix in ('.py', '.sh', '')}


CAPABILITY_EXPORTS = {
    'runtime-binding': {'scripts/runtime_binding.py': ('descriptor', 'bind', 'guard'),
                        'scripts/run_skill.py': ('resolve_launch', 'operation_for', 'main')},
    'scoped-physical-contract': {'scripts/physical_contract.py': ('current_evidence', 'enabled', 'init_run',
        'window_contract', 'input_guard', 'review_guard', 'final_guard')},
    'multi-purpose-references': {'scripts/media_references.py': ('resolve_inputs', 'identity_picture_map',
        'prompt_definitions', 'scoped_contract')},
    'conditional-production-policy': {'scripts/production_policy.py': ('init_run', 'scoped_contract',
        'submission_guard', 'candidate_guard', 'final_guard')},
    'restricted-postproduction': {'scripts/postproduction.py': ('init', 'validate_config', 'render', 'guard')},
    'structured-consistency': {'scripts/physical_source.py': ('draft','validate','activate','validate_source_structure'),
        'scripts/consistency_review.py': ('validate_checks','scoped_checks','prepare','review_guard','final_guard')},
}
# These are required connections, not a claim that AST inspection proves behavior.
CAPABILITY_HOOKS = {
    'runtime-binding': (('factory.py', 'ingest', 'runtime_binding.bind'),
        ('factory.py', 'instantiate', 'runtime_binding.bind'), ('factory.py', 'prepare', 'runtime_binding.guard'),
        ('factory.py', 'review_guard', 'runtime_binding.guard'),
        ('rh_runner.py', 'preflight', 'runtime_binding.guard'), ('comfy_runner.py', 'preflight', 'runtime_binding.guard')),
    'scoped-physical-contract': (('factory.py', 'instantiate', 'physical_contract.init_run'),
        ('factory.py', 'compute_input_digest', 'physical_contract.window_contract'),
        ('factory.py', 'review_guard', 'physical_contract.review_guard'),
        ('factory.py', 'review_guard', 'physical_contract.final_guard'),
        ('rh_runner.py', 'preflight', 'physical_contract.input_guard'),
        ('comfy_runner.py', 'preflight', 'physical_contract.input_guard')),
    'multi-purpose-references': (('factory.py', 'compute_input_digest', 'media_references.scoped_contract'),
        ('factory.py', 'compile_prompt', 'media_references.resolve_inputs'),
        ('factory.py', 'prepare', 'media_references.resolve_inputs')),
    'conditional-production-policy': (('factory.py', 'compute_input_digest', 'production_policy.scoped_contract'),
        ('factory.py', 'review_guard', 'production_policy.candidate_guard'),
        ('factory.py', 'build_skill', 'production_policy.final_guard'),
        ('rh_runner.py', 'preflight', 'production_policy.submission_guard'),
        ('comfy_runner.py', 'preflight', 'production_policy.submission_guard')),
    'restricted-postproduction': (('factory.py', 'main', 'postproduction.init'),
        ('factory.py', 'main', 'postproduction.render'), ('factory.py', 'build_skill', 'postproduction.guard')),
    'structured-consistency': (('physical_contract.py','_load','physical_source.validate_source_structure'),
        ('physical_contract.py','window_contract','consistency_review.scoped_checks'),
        ('physical_contract.py','review_guard','consistency_review.review_guard'),
        ('physical_contract.py','final_guard','consistency_review.final_guard')),
}


def _tree(root, name):
    try: return ast.parse(_path(root, name).read_text(encoding='utf-8-sig'))
    except (SyntaxError, OSError) as error: raise ValueError('Invalid capability provider: ' + name) from error


def _function(tree, qualified):
    node = tree
    for name in qualified.split('.'):
        node = next((item for item in getattr(node, 'body', []) if
                     isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name == name), None)
        if node is None: return None
    return node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _call_name(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute): return _call_name(node.value) + '.' + node.attr
    return ''


def descriptor(runtime_root=None):
    root = Path(runtime_root or ROOT).resolve(); meta = read(root / 'meta.json')
    if not _text(meta.get('name')): raise ValueError('Runtime metadata requires a stable skill name')
    files = production_files(root)
    declared = meta.get('available_capabilities', [])
    if not isinstance(declared, list) or any(not _text(v) for v in declared):
        raise ValueError('Explicit available_capabilities must be a list')
    trees = {}
    def tree(name):
        if name not in trees: trees[name] = _tree(root, name)
        return trees[name]
    for capability in declared:
        if capability not in CAPABILITY_EXPORTS: raise ValueError('Unknown declared runtime capability: ' + capability)
        for name, exports in CAPABILITY_EXPORTS[capability].items():
            if name not in files or any(_function(tree(name), function) is None for function in exports):
                raise ValueError('Declared capability lacks provider exports: ' + capability)
        for filename, function, call in CAPABILITY_HOOKS[capability]:
            node = _function(tree('scripts/' + filename), function)
            if node is None or not any(isinstance(item, ast.Call) and _call_name(item.func) == call for item in ast.walk(node)):
                raise ValueError('Declared capability lacks required consumer hook: ' + capability + ' ' + call)
    return {'runtime_root': str(root), 'skill_id': meta['name'],
            'factory_version': str(meta.get('version', meta.get('factory_version', 'unknown'))),
            'runtime_version': str(meta.get('runtime_version', meta.get('version', meta.get('factory_version', 'unknown')))),
            'runtime_digest': digest(files), 'available_capabilities': sorted(set(declared))}


def _capabilities(value):
    if value is None: return [], []
    if isinstance(value, list): required, names = value, []
    elif isinstance(value, dict):
        required = value.get('required_capabilities', [])
        names = value.get('files', [])
        if not isinstance(names, list): raise ValueError('Source capability files must be a list')
        names = list(names)
        for key in ('entrypoint', 'contract_initializer'):
            if value.get(key): names.append(value[key])
        guards = value.get('guards', [])
        if not isinstance(guards, list): raise ValueError('Source capability guards must be a list')
        names.extend(guards)
    else: raise ValueError('Source capabilities must be a list or object')
    if not isinstance(required, list) or any(not _text(v) for v in required):
        raise ValueError('Required source capabilities must be canonical nonempty strings')
    if any(not _text(v) for v in names): raise ValueError('Source extension paths must be explicit strings')
    return required, names


def _source(project):
    source = read(Path(project) / 'source.json')
    original = source.get('source', {})
    if not _text(original.get('path')) or not _text(original.get('sha256')):
        raise ValueError('Run needs a current source path and SHA before runtime binding')
    if _sha(_path(project, original['path'])) != original['sha256']:
        raise ValueError('Actual run source bytes do not match source metadata')
    return source


def _current(project, runtime_root=None):
    project, runtime = Path(project).resolve(), Path(runtime_root or ROOT).resolve()
    result, source, meta = descriptor(runtime), _source(project), read(runtime / 'meta.json')
    sha = source['source']['sha256']
    if meta.get('source_sha256') and meta['source_sha256'] != sha:
        raise ValueError('Dedicated runtime belongs to another source')
    declarations = [meta.get('source_capabilities'), source.get('source_capabilities'),
                    source['source'].get('source_capabilities')]
    result['source_contract_digest'] = digest(declarations)
    required, extensions = _capabilities(declarations[0])
    for declaration in declarations[1:]:
        extra, paths = _capabilities(declaration); required.extend(extra); extensions.extend(paths)
    result['source_extensions'] = {}
    for descriptor_name in sorted(set(extensions)):
        name, separator, function = descriptor_name.partition(':')
        result['source_extensions'][name] = _sha(_path(runtime, name))
        if separator and (not _text(function) or _function(_tree(runtime, name), function) is None):
            raise ValueError('Declared source initializer/guard function is missing: ' + descriptor_name)
    facts = {}
    for relative in ('assets/evidence/physical-source.json', 'evidence/physical-source.json'):
        path = project / relative
        if path.is_file():
            facts_document=read(path)
            if facts_document.get('source_sha256') != sha:
                raise ValueError('Run physical facts do not match the current source SHA')
            facts[relative] = _sha(_path(project, relative))
            required.append('scoped-physical-contract')
            extra,_=_capabilities(facts_document.get('required_capabilities'))
            required.extend(extra)
            if facts_document.get('consistency_checks'):required.append('structured-consistency')
    packaged = runtime / 'assets/evidence/physical-source.json'
    if not facts and meta.get('source_sha256') == sha and packaged.is_file():
        if read(packaged).get('source_sha256') != sha:
            raise ValueError('Packaged physical facts do not match their source')
        result['source_extensions']['assets/evidence/physical-source.json'] = _sha(packaged)
        required.append('scoped-physical-contract')
    result.update(source_sha256=sha, required_capabilities=sorted(set(required)), source_facts=facts)
    if set(required) - set(result['available_capabilities']):
        raise ValueError('Runtime lacks a required source capability')
    return result


def _write(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def bind(project, runtime_root=None, *, adopt=False, source_message=None):
    """Bind a fresh run; adoption/migration is explicit and preserves prior requirements."""
    project = Path(project).resolve(); path = project / 'run-runtime.json'
    current = _current(project, runtime_root)
    previous = read(path) if path.is_file() else None
    if previous:
        if previous.get('source_sha256') != current['source_sha256']:
            raise ValueError('A runtime migration cannot replace the source of an existing run')
        current['required_capabilities'] = sorted(set(current['required_capabilities']) |
                                                  set(previous.get('required_capabilities', [])))
        if set(current['required_capabilities']) - set(current['available_capabilities']):
            raise ValueError('Migration would drop an inherited source capability')
        if all(previous.get(key) == value for key, value in current.items()): return previous
    historical = previous or any((project / name).is_file() for name in ('queue.json', 'reviews.json', 'outputs.json'))
    if historical and (not adopt or not _text(source_message)):
        raise ValueError('Existing run needs explicit adopt/migrate with a real user source_message')
    result = {'schema_version': 1, **current, 'bound_at': datetime.now(timezone.utc).isoformat(),
              'history': list(previous.get('history', [])) if previous else []}
    if previous:
        result['history'].append({k: v for k, v in previous.items() if k != 'history'})
    if adopt:
        if not _text(source_message): raise ValueError('Explicit adoption needs user source_message')
        result['adoption'] = {'actor': 'user', 'source_message': source_message}
    _write(path, result)
    return result


def guard(project, operation, runtime_root=None):
    """Enforce runtime identity before mutations; recovery/diagnosis never authorizes work."""
    path = Path(project) / 'run-runtime.json'
    binding = read(path) if path.is_file() else None
    if operation in READ_ONLY:
        return {'read_only': True, 'operation': operation, 'binding': binding}
    if binding is None:
        raise ValueError('Run is not runtime-bound; explicitly adopt legacy runs before new operations')
    if binding.get('schema_version') != 1: raise ValueError('Unsupported run runtime binding schema')
    current = _current(project, runtime_root)
    for key in ('runtime_root', 'skill_id', 'factory_version', 'runtime_version', 'runtime_digest',
                'source_sha256', 'source_extensions', 'source_facts', 'source_contract_digest'):
        if binding.get(key) != current[key]:
            raise ValueError('Run runtime binding is stale or selected a different skill: ' + key)
    required = set(binding.get('required_capabilities', []))
    if (not set(current['required_capabilities']) <= required or
            not required <= set(current['available_capabilities'])):
        raise ValueError('Runtime does not preserve the bound required source capabilities')
    return binding


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('bind', 'adopt', 'migrate', 'diagnose'))
    parser.add_argument('--project', required=True)
    parser.add_argument('--runtime-root')
    parser.add_argument('--source-message')
    args = parser.parse_args(argv)
    if args.command == 'diagnose':
        result = guard(args.project, 'diagnose', args.runtime_root)
        try: result['current_runtime'] = descriptor(args.runtime_root)
        except (ValueError, OSError) as error: result['runtime_error'] = str(error)
    else:
        result = bind(args.project, args.runtime_root, adopt=args.command in ('adopt', 'migrate'),
                      source_message=args.source_message)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise SystemExit(str(error))
