"""Validate scoped physical contracts and human records; never infer visual passes.

Matching run-owned source facts enable the additional gates. SHA/file bindings
prevent stale approval; they cannot establish the truth of human observations.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
EVIDENCE = PACKAGE / 'assets/evidence/physical-source.json'
# Compatibility for source-specific packages only; the generic factory has none.
SOURCE_SHA = (json.loads((PACKAGE / 'meta.json').read_text(encoding='utf-8-sig')).get('source_sha256')
              if (PACKAGE / 'meta.json').is_file() else None)
CRITERIA = ('surfaces', 'connections', 'fold_state', 'artwork', 'openings',
            'stacking', 'occlusion', 'continuity', 'text_legibility')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _resolve(project, name):
    path, root = Path(name), Path(project).resolve()
    if path.is_absolute() or '..' in path.parts or not (root / path).resolve().is_relative_to(root):
        raise ValueError('Physical reference paths must stay inside the run')
    return root / path


def _signature(project, name):
    path = _resolve(project, name)
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Physical reference changed during hashing')
    return {'path': Path(name).as_posix(), 'sha256': h.hexdigest(),
            'size_bytes': after.st_size, 'mtime_ns': after.st_mtime_ns}


def input_signatures(project, entry):
    """Bind the prepared request bytes, independently of a cached queue digest."""
    if (any(not _text(entry.get(key)) for key in ('video_path', 'prompt_path')) or
            not isinstance(entry.get('reference_paths'), list) or
            any(not _text(path) for path in entry['reference_paths'])):
        raise ValueError('Physical input review needs actual prepared video, prompt and reference paths')
    return {'video': _signature(project, entry['video_path']),
            'prompt': _signature(project, entry['prompt_path']),
            'references': [_signature(project, path) for path in entry['reference_paths']]}


def _source_sha(project):
    path = Path(project) / 'source.json'
    return read(path).get('source', {}).get('sha256') if path.is_file() else None


def current_evidence(project):
    """Prefer current run facts; packaged facts apply only to their own source."""
    project, sha = Path(project), _source_sha(project)
    if not sha:
        return None
    for relative in ('assets/evidence/physical-source.json', 'evidence/physical-source.json'):
        path = project / relative
        if path.is_file():
            if read(path).get('source_sha256') != sha:
                raise ValueError('Run physical source facts do not bind the current source SHA')
            return path
    if SOURCE_SHA == sha and EVIDENCE.is_file():
        if read(EVIDENCE).get('source_sha256') != sha:
            raise ValueError('Packaged physical facts do not match their own source metadata')
        return EVIDENCE
    return None


def enabled(project):
    return current_evidence(project) is not None


def required(project, window=None):
    """A declared product input or reviewed source triage cannot silently skip physics."""
    project=Path(project)
    job=read(project/'job.json') if (project/'job.json').is_file() else {}
    analysis=read(project/'analysis.json') if (project/'analysis.json').is_file() else {}
    if analysis.get('physical_review_required') is True or job.get('physical_consistency_required') is True:
        return True
    interval=(window or {}).get('context_interval',(window or {}).get('source_interval'))
    for row in job.get('media_references',[]) or []:
        if not isinstance(row,dict) or row.get('purpose')!='product':continue
        scope=row.get('source_interval')
        if interval is None or (isinstance(scope,list) and len(scope)==2 and _overlap(scope,interval)):
            return True
    return False


def init_run(project):
    """Write pending run-owned choices; preserve any existing contract/reviews."""
    if not enabled(project):
        return None
    project, source = Path(project), read(current_evidence(project))
    path = project / 'production-contract.json'
    if not path.exists():
        write(path, {'schema_version': 1, 'source_sha256': _source_sha(project),
                     'products': {key: {'references': [],
                                      'panels': {panel: '' for panel in product['panels']},
                                      'hinges': []} for key, product in source['products'].items()},
                     'rules': [], 'sampler': None, 'sampler_overrides': {}})
    if not (project / 'physical-reviews.json').exists():
        write(project / 'physical-reviews.json', {'schema_version': 1, 'inputs': {}})
    return read(path)


def _interval(value, bounds):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(i) is not int for i in value) or
            not bounds[0] <= value[0] < value[1] <= bounds[1]):
        raise ValueError('Physical source_interval must be nonempty and inside its product')
    return value


def _overlap(left, right):
    return max(left[0], right[0]) < min(left[1], right[1])


def _load(project):
    source = read(current_evidence(project))
    if (source.get('schema_version') != 1 or type(source.get('frame_count')) is not int or
            source['frame_count'] <= 0 or not isinstance(source.get('products'), dict) or
            not isinstance(source.get('rules'), list)):
        raise ValueError('Physical source facts need a positive frame count, products and rules')
    if 'source_review' in source:
        import physical_source
        physical_source.validate_source_structure(project,source,decode=False)
    if source.get('consistency_checks'):
        import consistency_review
        consistency_review.validate_checks(source)
    path = Path(project) / 'production-contract.json'
    if not path.is_file():
        raise ValueError('Initialize the pending production contract first')
    contract = read(path)
    if contract.get('schema_version') != 1 or contract.get('source_sha256') != _source_sha(project):
        raise ValueError('Physical contract does not describe this source')
    products = contract.get('products')
    if not isinstance(products, dict) or set(products) != set(source['products']):
        raise ValueError('Physical target products must match all known source products')
    additions = contract.get('rules', [])
    if not isinstance(additions, list):
        raise ValueError('Physical rules must be a list')
    rules = copy.deepcopy(source['rules']) + copy.deepcopy(additions)
    by_id = {}
    for rule in rules:
        if not isinstance(rule, dict) or not _text(rule.get('id')) or rule['id'] in by_id:
            raise ValueError('Physical rule IDs must be nonempty and unique')
        product = source['products'].get(rule.get('product'))
        if not product or rule.get('panel') not in product['panels']:
            raise ValueError('Unknown physical product or panel')
        _interval(rule.get('source_interval'), product['source_interval'])
        if any(not _text(rule.get(key)) for key in ('attribute', 'expected', 'basis')):
            raise ValueError('Physical rules need attribute, expected and basis')
        if rule.get('origin') not in ('source', 'user', 'target_reference'):
            raise ValueError('Physical rule origin must be explicit')
        if rule in additions and rule['origin'] == 'source':
            raise ValueError('Run rules cannot declare new inherited source facts')
        if not isinstance(rule.get('supersedes'), list) or any(not _text(i) for i in rule['supersedes']):
            raise ValueError('Physical rule supersedes must list explicit rule IDs')
        by_id[rule['id']] = rule
    for rule in rules:
        for ident in rule['supersedes']:
            previous = by_id.get(ident)
            if (not previous or previous is rule or
                any(rule[key] != previous[key] for key in ('product', 'panel', 'attribute')) or
                not _overlap(rule['source_interval'], previous['source_interval'])):
                raise ValueError('Physical supersedes must name an overlapping rule for the same face/attribute')
            if rule['id'] in previous['supersedes']:
                raise ValueError('Physical supersedes cannot be cyclic')
    visited, visiting = set(), set()
    def visit(ident):
        if ident in visiting:
            raise ValueError('Physical supersedes cannot be cyclic')
        if ident not in visited:
            visiting.add(ident)
            for previous in by_id[ident]['supersedes']:
                visit(previous)
            visiting.remove(ident)
            visited.add(ident)
    for ident in by_id:
        visit(ident)
    for index, left in enumerate(rules):
        for right in rules[index + 1:]:
            if (all(left[key] == right[key] for key in ('product', 'panel', 'attribute')) and
                    _overlap(left['source_interval'], right['source_interval']) and
                    left['expected'] != right['expected'] and
                    right['id'] not in left['supersedes'] and left['id'] not in right['supersedes']):
                raise ValueError('Overlapping physical rules conflict; explicit supersedes is required')
    return source, contract, rules


def _target(project, source, target, ready=False):
    if not isinstance(target, dict):
        raise ValueError('Target product must be an object')
    refs, panels, hinges = target.get('references'), target.get('panels'), target.get('hinges')
    if (not isinstance(refs, list) or any(not _text(p) for p in refs) or
            not isinstance(panels, dict) or not set(panels) <= set(source['panels']) or
            any(not isinstance(note, str) for note in panels.values()) or
            not isinstance(hinges, list) or any(not _text(note) for note in hinges)):
        raise ValueError('Target reference files, known panels and hinge descriptions are required')
    if ready and (not refs or set(panels) != set(source['panels']) or
                  any(not _text(note) for note in panels.values()) or not hinges):
        raise ValueError('Physical target is pending: inspect actual references, every panel and hinges')
    return {'references': [_signature(project, name) for name in refs],
            'panels': panels, 'hinges': hinges}


def _profile_graph(project, profile):
    if not profile.get('workflow_path'):
        raise ValueError('Local/two-stage sampling needs an actual API workflow')
    document = read(_resolve(project, profile['workflow_path']))
    graph = copy.deepcopy(document.get('prompt', document))
    if not isinstance(graph, dict):
        raise ValueError('Sampler inspection needs an API-format graph')
    for parameter in profile.get('parameters', []):
        ident, name = parameter.get('node_id'), parameter.get('input')
        if ident in graph and name in graph[ident].get('inputs', {}):
            graph[ident]['inputs'][name] = parameter.get('value')
    return graph


def sampler_settings(project, window, profile):
    if not enabled(project):
        return None
    _, contract, _ = _load(project)
    overrides = contract.get('sampler_overrides', {})
    if not isinstance(overrides, dict):
        raise ValueError('sampler_overrides must map window IDs to settings')
    known = {w['window_id'] for w in read(Path(project) / 'plan.json')['windows']}
    if not set(overrides) <= known:
        raise ValueError('Unknown sampler override window')
    default = contract.get('sampler')
    if default is None:
        default = profile.get('sampler')
    settings = copy.deepcopy(overrides.get(window['window_id'],
        window.get('profile_override', {}).get('sampler', default)))
    if settings is not None or profile.get('kind') not in ('local-comfyui', 'runninghub-workflow'):
        return settings
    graph = _profile_graph(project, profile)
    h3 = [ident for ident, node in graph.items() if node.get('class_type') == 'SelfLiftH3Sampler']
    if not h3:
        return None
    schedulers = [ident for ident, node in graph.items() if node.get('class_type') == 'BasicScheduler']
    if len(h3) != 1 or len(schedulers) != 1:
        raise ValueError('Ambiguous H3 graph requires explicit scheduler/sampler bindings')
    total = graph[schedulers[0]].get('inputs', {}).get('steps')
    first = graph[h3[0]].get('inputs', {}).get('transition_step')
    if type(total) is not int or type(first) is not int or not 0 < first < total:
        raise ValueError('Actual H3 stages must both be positive integer step counts')
    return {'first_steps': first, 'second_steps': total - first,
            'scheduler_node': schedulers[0], 'sampler_node': h3[0]}


def validate_sampler(graph, settings):
    """Inspect actual bound API graph, including immediately before POST."""
    if settings is None:
        return None
    if not isinstance(settings, dict):
        raise ValueError('Two-stage sampler settings must be an object')
    first, second = settings.get('first_steps'), settings.get('second_steps')
    scheduler, sampler = settings.get('scheduler_node'), settings.get('sampler_node')
    if (type(first) is not int or type(second) is not int or min(first, second) <= 0 or
            not _text(scheduler) or not _text(sampler) or scheduler == sampler):
        raise ValueError('Explicit distinct node bindings and positive integer first/second steps required')
    graph = graph.get('prompt', graph) if isinstance(graph, dict) else {}
    scheduler_node, sampler_node = graph.get(scheduler, {}), graph.get(sampler, {})
    total = scheduler_node.get('inputs', {}).get('steps')
    transition = sampler_node.get('inputs', {}).get('transition_step')
    if (scheduler_node.get('class_type') != 'BasicScheduler' or
            sampler_node.get('class_type') != 'SelfLiftH3Sampler' or
            type(total) is not int or type(transition) is not int or
            total != first + second or transition != first):
        raise ValueError('Actual BasicScheduler total / SelfLiftH3Sampler transition do not match requested stages')
    found, visited, visiting = set(), set(), {sampler}
    def follow(value, effective=True):
        if (not isinstance(value, list) or len(value) != 2 or not _text(value[0]) or
                type(value[1]) is not int or value[1] < 0):
            raise ValueError('Actual sampler sigma input must link to its effective scheduler branch')
        ident = value[0]
        if ident in visiting or ident not in graph:
            raise ValueError('Actual sampler sigma branch is cyclic or dangling')
        if (ident, effective) in visited:
            return
        node = graph[ident]
        if not isinstance(node, dict) or not isinstance(node.get('inputs'), dict):
            raise ValueError('Actual sampler sigma branch has an invalid API node')
        visiting.add(ident)
        is_scheduler = node.get('class_type') == 'BasicScheduler'
        if is_scheduler and effective:
            found.add(ident)
        for upstream in node['inputs'].values():
            if isinstance(upstream, list) and len(upstream) == 2 and isinstance(upstream[0], str):
                follow(upstream, effective and not is_scheduler)
        visiting.remove(ident)
        visited.add((ident, effective))
    follow(sampler_node['inputs'].get('sigmas'))
    if found != {scheduler}:
        raise ValueError('Declared BasicScheduler must be the sole effective scheduler on the sampler sigma branch')
    return {'total_steps': total, 'transition_step': transition,
            'scheduler_node': scheduler, 'sampler_node': sampler,
            'scheduler_class': scheduler_node['class_type'], 'sampler_class': sampler_node['class_type']}


def _effective(rules, interval):
    result = []
    keys = sorted({(r['product'], r['panel'], r['attribute']) for r in rules})
    for key in keys:
        group = [r for r in rules if tuple(r[k] for k in ('product', 'panel', 'attribute')) == key
                 and _overlap(r['source_interval'], interval)]
        points = sorted({max(interval[0], r['source_interval'][0]) for r in group} |
                        {min(interval[1], r['source_interval'][1]) for r in group})
        for left, right in zip(points, points[1:]):
            active = [r for r in group if r['source_interval'][0] <= left and r['source_interval'][1] >= right]
            superseded = {ident for r in active for ident in r['supersedes']}
            survivors = [r for r in active if r['id'] not in superseded]
            if active and not survivors:
                raise ValueError('Physical overrides have no active rule')
            for rule in sorted(survivors, key=lambda r: r['id']):
                result.append({**rule, 'source_interval': [left, right]})
    return result


def window_contract(project, window, profile):
    """Stable scoped generation facts. Pending choices can be prepared, not submitted."""
    if not enabled(project):
        return None
    source, contract, rules = _load(project)
    interval = _interval(window.get('context_interval', window['source_interval']), [0, source['frame_count']])
    original = read(Path(project) / 'source.json')['source']
    actual = _signature(project, original['path'])
    if actual['sha256'] != _source_sha(project):
        raise ValueError('Physical source bytes changed')
    selected = {key: value for key, value in source['products'].items()
                if _overlap(value['source_interval'], interval)}
    products = {key: {'source_geometry': value,
                     'target': _target(project, value, contract['products'][key])}
                for key, value in selected.items()}
    job = read(Path(project) / 'job.json')
    guide = job.get('opening_guides', {}).get(window['window_id'])
    opening = ({'source_frame': guide.get('source_frame'), 'file_signature': _signature(project, guide['path'])}
               if guide else None)
    static = [{'node_id': binding.get('node_id'), 'input': binding.get('input'),
               'file_signature': _signature(project, binding['literal_path'])}
              for binding in profile.get('bindings', []) if binding.get('literal_path')]
    fixed = profile.get('fixed_auxiliary_conditions', [])
    if not isinstance(fixed, list):
        raise ValueError('fixed_auxiliary_conditions must list actual guide file bindings')
    for condition in fixed:
        if not isinstance(condition, dict) or not _text(condition.get('path')):
            raise ValueError('Fixed auxiliary condition needs an actual run-contained path')
        signature = _signature(project, condition['path'])
        if signature['sha256'] != condition.get('sha256'):
            raise ValueError('Fixed auxiliary condition SHA does not match its current file bytes')
        static.append({'kind': condition.get('kind'),
                       'identity_authority': condition.get('identity_authority'),
                       'motion_authority': condition.get('motion_authority'),
                       'file_signature': signature})
    settings = sampler_settings(project, window, profile)
    observed = None
    if settings is not None:
        observed = validate_sampler(_profile_graph(project, profile), settings)
    result={'schema_version': 1, 'source_sha256': _source_sha(project), 'source_signature': actual,
            'window_id': window['window_id'], 'source_interval': interval, 'products': products,
            'rules': _effective([r for r in rules if r['product'] in selected], interval),
            'opening_guide': opening, 'static_guides': static, 'sampler_settings': settings,
            'sampler': {'settings': settings, 'observed': observed} if settings is not None else None}
    if source.get('consistency_checks'):
        import consistency_review
        result['consistency_checks']=consistency_review.scoped_checks(source,interval)
    return result


def _window(project, wid):
    window = next((w for w in read(Path(project) / 'plan.json')['windows'] if w['window_id'] == wid), None)
    if window is None:
        raise ValueError('Unknown physical review window')
    return window


def input_guard(project, entry):
    if entry.get('passthrough'):
        return None
    if not enabled(project) and not required(project):return None
    window = _window(project, entry['window_id'])
    if not enabled(project):
        if required(project,window):
            raise ValueError('Reviewed source physical facts are required before product submission; draft and inspect the actual source first')
        return None
    current = window_contract(project, window, entry['profile'])
    source, contract, _ = _load(project)
    for key in current['products']:
        _target(project, source['products'][key], contract['products'][key], ready=True)
    path = Path(project) / 'physical-reviews.json'
    record = read(path).get('inputs', {}).get(entry['window_id'], {}) if path.is_file() else {}
    if (record.get('status') != 'passed' or record.get('contract_digest') != digest(current) or
            not _text(entry.get('input_digest')) or record.get('input_digest') != entry['input_digest'] or
            record.get('request_signatures') != input_signatures(project, entry) or
            any(not _text(record.get('observations', {}).get(key)) for key in ('source', 'target', 'guide', 'prompt'))):
        raise ValueError('Current source/target/guide/prompt observations must bind the contract, request digest and actual prepared bytes')
    return record


def _playback(record, interval, frame_count):
    playback = record.get('playback', {})
    ranges = playback.get('intervals', [])
    if (playback.get('status') != 'observed' or playback.get('method') != 'continuous-playback' or
            type(playback.get('speed')) not in (int, float) or playback['speed'] != 1 or
            not _text(playback.get('notes')) or not isinstance(ranges, list)):
        raise ValueError('Actual continuous original-speed playback observations are required')
    _interval(interval, [0, frame_count])
    cursor = interval[0]
    for pair in ranges:
        _interval(pair, [0, frame_count])
    for left, right in sorted(ranges):
        if left > cursor:
            break
        cursor = max(cursor, right)
    if cursor < interval[1]:
        raise ValueError('Milestones or partial intervals cannot replace complete actual playback coverage')


def _physical_output(project, record, interval, frame_count):
    physical = record.get('physical', {})
    actual = _signature(project, record['output_path'])
    if (physical.get('status') != 'passed' or physical.get('file_signature') != actual or
            record.get('file_signature') != actual or
            any(not _text(physical.get('observations', {}).get(key)) for key in CRITERIA)):
        raise ValueError('Physical output review requires current signature and per-criterion actual observations')
    _playback(physical, interval, frame_count)
    return physical


def review_guard(project, window, record, entry,deps=None,scalar_cpu=False):
    if entry.get('passthrough'):
        return None
    input_guard(project, entry)
    if not enabled(project):return None
    frames = record.get('technical', {}).get('report', {}).get('video', {}).get('frames', [])
    if not isinstance(frames, list) or not frames:
        raise ValueError('Physical playback needs the current decoded candidate frame count')
    physical = _physical_output(project, record, record['retained_output_interval'], len(frames))
    if (window['window_id'] != entry['window_id'] or not entry.get('input_digest') or
            physical.get('input_digest') != entry['input_digest'] or record.get('input_digest') != entry['input_digest']):
        raise ValueError('Physical candidate observations must bind the current request input_digest')
    import consistency_review
    consistency_review.review_guard(project,read(current_evidence(project)),window,record,entry,deps=deps,scalar_cpu=scalar_cpu)
    return physical


def final_guard(project, record,deps=None,scalar_cpu=False):
    if not enabled(project):
        if required(project):raise ValueError('Reviewed source physical facts are required before final review')
        return None
    count = read(current_evidence(project))['frame_count']
    manifest = read(Path(project) / 'source.json')
    if _signature(project, manifest['source']['path'])['sha256'] != _source_sha(project):
        raise ValueError('Physical final source bytes changed')
    if manifest['video']['frame_count'] != count:
        raise ValueError('Physical final review must retain the complete current source frame count')
    physical = _physical_output(project, record, [0, count], count)
    if not record.get('composition_digest') or physical.get('composition_digest') != record['composition_digest']:
        raise ValueError('Physical final observations must bind the current composition digest')
    import consistency_review
    consistency_review.final_guard(project,read(current_evidence(project)),record,deps=deps,scalar_cpu=scalar_cpu)
    return physical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'check', 'status'))
    parser.add_argument('--project', required=True)
    parser.add_argument('--window-id', action='append')
    args = parser.parse_args()
    if args.command == 'init':
        print(json.dumps({'enabled': enabled(args.project), 'contract': init_run(args.project)}, ensure_ascii=False))
        return
    if not enabled(args.project):
        pending=(any(required(args.project,_window(args.project,wid)) for wid in args.window_id)
                 if args.window_id else required(args.project))
        print(json.dumps({'enabled': False,'required':pending,'status':'pending' if pending else 'not_applicable',
            'block_reason':'Reviewed source physical facts are pending' if pending else None,'windows': []}))
        if args.command=='check' and pending:raise SystemExit(1)
        return
    project = Path(args.project)
    queue = read(project / 'queue.json')['jobs'] if (project / 'queue.json').is_file() else []
    entries = {entry['window_id']: entry for entry in queue}
    job = read(project / 'job.json')
    windows = ([_window(project, wid) for wid in args.window_id] if args.window_id else
               [_window(project, wid) for wid in entries] if entries else read(project / 'plan.json')['windows'])
    result, failed = [], False
    for window in windows:
        entry = entries.get(window['window_id'], {'window_id': window['window_id'],
                    'profile': window.get('profile_override') or job.get('profile', {})})
        item = {'window_id': window['window_id']}
        try:
            current = window_contract(project, window, entry['profile'])
            item.update(contract_digest=digest(current), contract=current)
            if window['window_id'] not in entries:
                raise ValueError('Prepare and queue the actual request before input review')
            item.update(request_signatures=input_signatures(project, entry), input_digest=entry.get('input_digest'))
            import factory
            actual_digest=factory.compute_input_digest(project,entry)
            item['current_input_digest']=actual_digest
            if actual_digest != entry.get('input_digest'):
                raise ValueError('Prepared request is stale; prepare and review current inputs again')
            input_guard(project, entry)
            item['input_review_status'] = 'passed'
        except (ValueError, KeyError, OSError, TypeError) as error:
            failed = True
            item.update(input_review_status='pending', block_reason=str(error))
        result.append(item)
    print(json.dumps({'enabled': True, 'windows': result}, ensure_ascii=False, indent=2))
    if args.command == 'check' and failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
