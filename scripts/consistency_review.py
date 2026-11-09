"""Bind declared consistency states to native decoded evidence and human records.

This validates source definitions, ownership, mapping and pixels, never visual
correctness. Existing continuous-playback, physical and technical guards still
apply. prepare() exports only pending records; a person must inspect the actual
states/transitions and record observations before either guard can pass.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import media

CRITERIA = ('surfaces', 'connections', 'fold_state', 'artwork', 'openings',
            'stacking', 'occlusion', 'continuity', 'text_legibility')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _interval(value, bounds=None):
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(type(i) is not int for i in value) or not 0 <= value[0] < value[1] or
            (bounds is not None and not bounds[0] <= value[0] < value[1] <= bounds[1])):
        raise ValueError('Consistency intervals must be nonempty integer source-frame ranges')
    return list(value)


def _overlap(left, right):
    return max(left[0], right[0]) < min(left[1], right[1])


def validate_checks(facts):
    """Validate optional source-owned consistency_checks; legacy absence returns []."""
    if not isinstance(facts, dict): raise ValueError('Consistency source facts must be an object')
    checks = facts.get('consistency_checks', [])
    if not isinstance(checks, list): raise ValueError('consistency_checks must be a list')
    if not checks: return []
    count, products, rules = facts.get('frame_count'), facts.get('products'), facts.get('rules')
    if type(count) is not int or count <= 0 or not isinstance(products, dict) or not isinstance(rules, list):
        raise ValueError('Consistency checks need source frame count, products and source rules')
    by_rule = {}
    for rule in rules:
        if not isinstance(rule, dict) or not _text(rule.get('id')) or rule['id'] in by_rule:
            raise ValueError('Consistency source rule IDs must be unique')
        by_rule[rule['id']] = rule
    result, identifiers = [], set()
    for original in checks:
        if not isinstance(original, dict): raise ValueError('Consistency check must be an object')
        check = copy.deepcopy(original); ident = check.get('id')
        if not _text(ident) or ident in identifiers: raise ValueError('Consistency check IDs must be unique')
        identifiers.add(ident)
        if not _text(check.get('product')) or not _text(check.get('panel')):
            raise ValueError('Consistency product and panel must be explicit IDs')
        product = products.get(check.get('product'))
        if (not isinstance(product, dict) or not isinstance(product.get('panels'), (dict, list)) or
                check.get('panel') not in product['panels']):
            raise ValueError('Consistency check must name a known product and panel')
        bounds = _interval(product.get('source_interval'), [0, count])
        interval = _interval(check.get('source_interval'), bounds)
        if check.get('criterion') not in CRITERIA: raise ValueError('Unknown physical consistency criterion')
        refs = check.get('rule_ids')
        if not isinstance(refs, list) or not refs or any(not _text(ref) for ref in refs) or len(set(refs)) != len(refs):
            raise ValueError('Consistency checks must reference explicit source rule IDs')
        for ref in refs:
            rule = by_rule.get(ref)
            if (not rule or rule.get('product') != check['product'] or rule.get('panel') != check['panel'] or
                    rule.get('origin', 'source') != 'source' or not _overlap(_interval(rule.get('source_interval')), interval)):
                raise ValueError('Consistency rule must be an overlapping source rule for this product and panel')
        axes = check.get('local_axes')
        if axes is not None and (not isinstance(axes, dict) or set(axes) != {'u', 'v', 'normal'} or
                                 any(not _text(v) for v in axes.values())):
            raise ValueError('Local axes require nonempty u, v and normal descriptions')
        forbidden = check.get('forbidden_panels', [])
        if (not isinstance(forbidden, list) or any(not _text(p) or p not in product['panels'] or
                p == check['panel'] for p in forbidden) or len(set(forbidden)) != len(forbidden)):
            raise ValueError('Forbidden panels must name other known panels of this product')
        states = check.get('states')
        if not isinstance(states, list) or not states: raise ValueError('Consistency checks require declared states')
        ids, frames = set(), set()
        for state in states:
            if not isinstance(state, dict): raise ValueError('Consistency state must be an object')
            sid, frame = state.get('id'), state.get('source_frame')
            if (not _text(sid) or sid in ids or type(frame) is not int or frame in frames or
                    not interval[0] <= frame < interval[1] or not _text(state.get('description'))):
                raise ValueError('States need unique IDs/frames, descriptions and frames inside the source check')
            ids.add(sid); frames.add(frame)
        check['states'] = sorted(states, key=lambda state: state['source_frame'])
        result.append(check)
    return result


def scoped_checks(facts, interval, owner=False):
    """Context keeps conditioning definitions; owner keeps only actual owned states."""
    interval = _interval(interval); result = []
    for check in validate_checks(facts):
        product = facts['products'][check['product']]
        if not _overlap(check['source_interval'], interval) or not _overlap(product['source_interval'], interval): continue
        if owner:
            check['states'] = [s for s in check['states'] if interval[0] <= s['source_frame'] < interval[1]]
            if not check['states']: continue
        result.append(check)
    return result


def _resolve(project, name):
    if not isinstance(name, (str, Path)) or not str(name): raise ValueError('Consistency artifact needs a run-contained path')
    root, path = Path(project).resolve(), Path(name)
    actual = (root / path).resolve()
    if path.is_absolute() or '..' in path.parts or not actual.is_relative_to(root):
        raise ValueError('Consistency artifacts must remain inside the run')
    return actual


def signature(project, name):
    """Current bytes and filesystem identity, compatible with parent physical guards."""
    path = _resolve(project, name); before = path.stat(); h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''): h.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Consistency artifact changed during hashing')
    return {'path': Path(name).as_posix(), 'sha256': h.hexdigest(),
            'size_bytes': after.st_size, 'mtime_ns': after.st_mtime_ns}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _source(project, facts):
    original = _read(Path(project) / 'source.json')['source']
    if original.get('sha256') != facts.get('source_sha256'):
        raise ValueError('Consistency source facts do not bind the current run source')
    return original


def _frames(path, indices, deps, scalar_cpu):
    wanted, found = set(indices), {}
    if not wanted: return found
    av = media.runtime(deps, scalar_cpu)
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1: raise ValueError('Consistency proof requires one decoded video stream')
        stream = container.streams.video[0]; stream.codec_context.thread_count = 1
        rotation = None
        for index, frame in enumerate(container.decode(stream)):
            if rotation is None: rotation = getattr(frame, 'rotation', 0)
            if index in wanted: found[index] = media.display_frame(frame, rotation).to_image().convert('RGB')
            if len(found) == len(wanted): break
    if set(found) != wanted: raise ValueError('Consistency evidence frame is outside the decoded output')
    return found


def _scope(facts, window, final):
    return scoped_checks(facts, [0, facts['frame_count']] if final else window['source_interval'], owner=True)


def _mapping(window, record, checks, final):
    indices = {s['source_frame'] for check in checks for s in check['states']}
    if final: return {index: index for index in indices}
    interval = _interval(window['source_interval']); mapping = record.get('source_to_output')
    if (not isinstance(mapping, list) or len(mapping) != interval[1] - interval[0] or
            any(type(index) is not int or index < 0 for index in mapping)):
        raise ValueError('Consistency proof needs the actual complete source_to_output owner mapping')
    result = {index: mapping[index - interval[0]] for index in indices}
    for check in checks:
        values = [result[state['source_frame']] for state in check['states']]
        if any(a >= b for a, b in zip(values, values[1:])):
            raise ValueError('Declared source states must map to chronological distinct output states')
    return result


def _binding(project, facts, window, record, entry, final):
    checks = _scope(facts, window, final)
    if not checks: return checks, None, {}
    _source(project, facts)
    actual = signature(project, record.get('output_path'))
    if record.get('file_signature') != actual: raise ValueError('Consistency output signature is stale')
    if final:
        if not _text(record.get('composition_digest')): raise ValueError('Final consistency review requires composition_digest')
    elif (entry is not None and (window['window_id'] != entry.get('window_id') or
          not _text(entry.get('input_digest')) or record.get('input_digest') != entry['input_digest'])):
        raise ValueError('Consistency candidate must bind the current window and input digest')
    elif not _text(record.get('input_digest')):
        raise ValueError('Consistency candidate requires input_digest')
    return checks, actual, _mapping(window, record, checks, final)


def _png(project, evidence, expected):
    from PIL import Image
    if not isinstance(evidence, dict) or not _text(evidence.get('path')):
        raise ValueError('Consistency state requires a native PNG artifact')
    before = signature(project, evidence['path'])
    if evidence.get('sha256') != before['sha256']: raise ValueError('Consistency PNG SHA is stale')
    with Image.open(_resolve(project, evidence['path'])) as image:
        if image.format != 'PNG' or image.mode != 'RGB' or image.size != expected.size or image.tobytes() != expected.tobytes():
            raise ValueError('Consistency PNG must match the actual decoded native RGB candidate frame')
    if signature(project, evidence['path']) != before: raise ValueError('Consistency PNG changed during verification')


def _guard(project, facts, window, record, entry, deps, scalar_cpu, final):
    checks, actual, mapping = _binding(project, facts, window, record, entry, final)
    if not checks: return None
    review = record.get('physical', {}).get('consistency_review', {})
    key = 'composition_digest' if final else 'input_digest'
    if (review.get('check_digest') != digest(checks) or review.get('file_signature') != actual or
            review.get(key) != record.get(key) or not isinstance(review.get('checks'), dict) or
            set(review['checks']) != {c['id'] for c in checks}):
        raise ValueError('Consistency review must bind current definitions, output and request/composition')
    evidence, source_evidence = [], []
    for check in checks:
        observed = review['checks'][check['id']]; states = observed.get('states', {})
        if (observed.get('status') != 'passed' or not _text(observed.get('notes')) or
                not isinstance(states, dict) or set(states) != {s['id'] for s in check['states']}):
            raise ValueError('Every owned consistency state requires actual observations')
        for state in check['states']:
            note = states[state['id']]; source_index = state['source_frame']; output_index = mapping[source_index]
            if (note.get('status') != 'observed' or not _text(note.get('notes')) or
                    type(note.get('source_frame')) is not int or note['source_frame'] != source_index or
                    type(note.get('output_frame')) is not int or note['output_frame'] != output_index):
                raise ValueError('Consistency state observations must bind the actual source/output mapping')
            evidence.append((note.get('evidence'), output_index))
            source_evidence.append((note.get('source_evidence'), source_index))
        transitions = observed.get('transitions', [])
        pairs = list(zip(check['states'], check['states'][1:]))
        if not isinstance(transitions, list) or len(transitions) != len(pairs):
            raise ValueError('Owned consistency states require adjacent transition observations')
        for left, right in pairs:
            matching = [t for t in transitions if t.get('from_state') == left['id'] and t.get('to_state') == right['id']]
            start, end = mapping[left['source_frame']], mapping[right['source_frame']]
            note = matching[0] if len(matching) == 1 else {}
            interval = note.get('output_interval')
            if (start >= end or note.get('status') != 'observed' or not _text(note.get('notes')) or
                    not isinstance(interval, list) or any(type(i) is not int for i in interval) or interval != [start, end + 1]):
                raise ValueError('Transition notes must cover the mapped native output interval')
    original = _source(project, facts); source_actual = signature(project, original['path'])
    if source_actual['sha256'] != original['sha256']:
        raise ValueError('Consistency source actual bytes no longer match facts and source metadata')
    decoded = _frames(_resolve(project, record['output_path']), [index for _, index in evidence], deps, scalar_cpu)
    decoded_source = _frames(_resolve(project, original['path']), [index for _, index in source_evidence], deps, scalar_cpu)
    for artifact, index in evidence: _png(project, artifact, decoded[index])
    for artifact, index in source_evidence: _png(project, artifact, decoded_source[index])
    if (signature(project, record['output_path']) != actual or
            signature(project, original['path']) != source_actual):
        raise ValueError('Source/output changed during consistency review')
    return review


def review_guard(project, facts, window, record, entry, deps=None, scalar_cpu=False):
    if not validate_checks(facts): return None
    return _guard(project, facts, window, record, entry, deps, scalar_cpu, False)


def final_guard(project, facts, record, deps=None, scalar_cpu=False):
    if not validate_checks(facts): return None
    return _guard(project, facts, None, record, None, deps, scalar_cpu, True)


def prepare(project, facts, window, record, out, deps=None, scalar_cpu=False, final=False):
    """Export new native source/output PNGs and review.json containing only pending states."""
    relative = Path(out)
    directory = _resolve(project, relative)
    actual_relative = directory.relative_to(Path(project).resolve())
    if (not relative.parts or relative.parts[0].casefold() in ('assets', 'evidence') or
            not actual_relative.parts or actual_relative.parts[0].casefold() in ('assets', 'evidence')):
        raise ValueError('Consistency review output must stay outside source assets/evidence')
    if directory.exists(): raise ValueError('Consistency evidence output already exists; use a new directory')
    checks, actual, mapping = _binding(project, facts, window, record, None, final)
    if not checks: raise ValueError('No declared consistency states belong to this owner')
    original = _source(project, facts); source_before = signature(project, original['path'])
    if source_before['sha256'] != original['sha256']: raise ValueError('Actual source bytes changed')
    sources = _frames(_resolve(project, original['path']), mapping, deps, scalar_cpu)
    outputs = _frames(_resolve(project, record['output_path']), mapping.values(), deps, scalar_cpu)
    directory.mkdir(parents=True)
    exported = []
    def save(kind, index, image):
        name = relative / kind / f'frame_{index:06d}.png'; destination = _resolve(project, name)
        destination.parent.mkdir(parents=True, exist_ok=True); image.save(destination, format='PNG')
        artifact = {'path': name.as_posix(), 'sha256': signature(project, name)['sha256']}
        exported.append(artifact); return artifact
    source_artifacts = {index: save('source', index, image) for index, image in sources.items()}
    output_artifacts = {index: save('candidate', index, image) for index, image in outputs.items()}
    key = 'composition_digest' if final else 'input_digest'
    review = {'check_digest': digest(checks), 'file_signature': actual, key: record[key], 'checks': {}}
    for check in checks:
        states = {state['id']: {'status': 'pending', 'source_frame': state['source_frame'],
            'output_frame': mapping[state['source_frame']], 'evidence': output_artifacts[mapping[state['source_frame']]],
            'source_evidence': source_artifacts[state['source_frame']], 'notes': ''} for state in check['states']}
        transitions = [{'from_state': left['id'], 'to_state': right['id'], 'status': 'pending',
            'output_interval': [mapping[left['source_frame']], mapping[right['source_frame']] + 1], 'notes': ''}
            for left, right in zip(check['states'], check['states'][1:])]
        review['checks'][check['id']] = {'status': 'pending', 'notes': '', 'states': states, 'transitions': transitions}
    if signature(project, original['path']) != source_before or signature(project, record['output_path']) != actual:
        raise ValueError('Source/output changed while exporting consistency evidence')
    review_path = relative / 'review.json'
    _resolve(project, review_path).write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'review_path': review_path.as_posix(), 'review': review, 'evidence': exported}
