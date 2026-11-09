"""Optional run-owned production contracts; validate records, never create judgments.

production-policy.json schema 1 contains stages, artwork_masters and
visible_identity lists. Scopes intersect window_ids, source_interval and products
(omitted dimensions are unrestricted). Only a stage with a user_request containing
actor=user and source_message is an approval gate. Its approval binds the digest of
stage_contract(), including current asset bytes. Approval progress is deliberately
excluded from scoped_contract(), which contains only generation configuration.
Codex approvals require a user delegation with explicit stage_ids and equal scope.

A candidate's policy record binds contract_digest, input_digest and file_sha256.
artwork[id] records declared strictness, master_sha256, status and observations
keyed by every declared characteristic, anchor and state correspondence.
visible_identity[id] records reference_digest and per-part status, observations and
reference_attributes. Parts absent from source or references are not_assessable;
these records cannot establish facial likeness outside the frame.

delivery_state.json binds one output_sha256, preview, known_issues, exceptions and
user_acceptance. Each exception binds issue_id and digest(the complete issue).
An existing delivery state is enforced even without optional policy stages; only
a run with neither file retains legacy behavior. final_guard is a final-master
gate: provisional acceptance stays
provisional. None of these checks establishes generation authority or verifies the
truth of a supplied human observation or source_message.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

POLICY = 'production-policy.json'
STATE = 'delivery_state.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def _asset(project, record):
    name = record.get('path') if isinstance(record, dict) else None
    if not _text(name):
        raise ValueError('Policy assets require an actual run-contained path')
    root, path = Path(project).resolve(), Path(name)
    actual = (root / path).resolve()
    if path.is_absolute() or '..' in path.parts or not actual.is_relative_to(root):
        raise ValueError('Policy asset paths must stay inside the run')
    before = actual.stat()
    sha = hashlib.sha256(actual.read_bytes()).hexdigest()
    after = actual.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Policy asset changed during hashing')
    if record.get('sha256') is not None and record['sha256'] != sha:
        raise ValueError('Policy declared SHA differs from actual asset bytes')
    return {'path': path.as_posix(), 'sha256': sha}


def _scope(value):
    if not isinstance(value, dict) or set(value) - {'window_ids', 'source_interval', 'products'}:
        raise ValueError('Policy scope must explicitly use window_ids, source_interval or products')
    for key in ('window_ids', 'products'):
        if key in value and (not isinstance(value[key], list) or not value[key] or
                             any(not _text(item) for item in value[key])):
            raise ValueError('Policy scope lists must contain explicit nonempty IDs')
    if 'source_interval' in value:
        pair = value['source_interval']
        if (not isinstance(pair, list) or len(pair) != 2 or any(type(i) is not int for i in pair)
                or not 0 <= pair[0] < pair[1]):
            raise ValueError('Policy source scope must be a nonempty frame interval')
    return copy.deepcopy(value)


def _matches(project, scope, window):
    scope = _scope(scope)
    if 'window_ids' in scope and window['window_id'] not in scope['window_ids']:
        return False
    interval = window.get('context_interval', window['source_interval'])
    pair = scope.get('source_interval', interval)
    if max(pair[0], interval[0]) >= min(pair[1], interval[1]):
        return False
    if 'products' in scope:
        products = window.get('products', window.get('product_ids', []))
        if isinstance(products, dict): products = list(products)
        if window.get('product'): products = [*products, window['product']]
        if not products:
            for relative in ('assets/evidence/physical-source.json', 'evidence/physical-source.json'):
                path = Path(project) / relative
                if path.is_file():
                    products = [key for key, item in read(path).get('products', {}).items()
                                if max(item['source_interval'][0], interval[0]) <
                                   min(item['source_interval'][1], interval[1])]
                    break
        if not products:
            raise ValueError('Product-scoped policy requires current product-to-window source mapping')
        if not set(products) & set(scope['products']):
            return False
    return True


def _load(project):
    path = Path(project) / POLICY
    if not path.is_file(): return None
    value = read(path)
    if value.get('schema_version') != 1:
        raise ValueError('Unsupported production policy schema')
    for key in ('stages', 'artwork_masters', 'visible_identity'):
        items = value.get(key, [])
        if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
            raise ValueError('Production policy sections must be lists of objects')
        ids = [i.get('id') for i in items]
        if any(not _text(i) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Production policy IDs must be nonempty and unique in each section')
    return value


def init_run(project):
    """Initialize pending state, preserving all current contracts and human records."""
    path = Path(project) / STATE
    if not path.exists():
        _write(path, {'schema_version': 1, 'output_sha256': None,
                      'preview': {'status': 'pending'}, 'known_issues': [], 'exceptions': [],
                      'user_acceptance': {'status': 'pending'}})
    return _load(project)


def _requested(stage):
    request = stage.get('user_request')
    if request is None: return False
    if (not isinstance(request, dict) or request.get('actor') != 'user' or
            not _text(request.get('source_message'))):
        raise ValueError('A stage request must cite the explicit user request')
    return True


def stage_contract(project, stage):
    """Exact current asset/scope binding for a conditional stage approval."""
    assets = stage.get('assets')
    if not isinstance(assets, list) or not assets:
        raise ValueError('Requested approval stage requires actual review assets')
    return {'id': stage['id'], 'scope': _scope(stage.get('scope', {})),
            'user_request': copy.deepcopy(stage['user_request']),
            'assets': [_asset(project, item) for item in assets],
            'configuration': copy.deepcopy(stage.get('configuration', {}))}


def _master(project, item):
    if (item.get('strictness') not in ('exact', 'structural', 'approximate') or
            any(not _text(item.get(k)) for k in ('product', 'panel', 'source_message', 'sha256'))):
        raise ValueError('Artwork requires explicit user strictness, panel, product and actual master SHA')
    value = {key: copy.deepcopy(item.get(key)) for key in ('id', 'product', 'panel', 'strictness',
              'source_message', 'characteristics', 'anchors', 'state_correspondences')}
    value.update(_asset(project, item), scope=_scope(item.get('scope', {})))
    for key in ('characteristics', 'anchors', 'state_correspondences'):
        values = item.get(key)
        if not isinstance(values, dict) or not values or any(not _text(k) or not _text(v) for k, v in values.items()):
            raise ValueError('Artwork requires declared characteristics, anchors and state correspondences')
    return value


def _identity(project, item):
    refs, parts = item.get('references'), item.get('source_visible_parts')
    if (not _text(item.get('role')) or not isinstance(refs, list) or not refs or
            not isinstance(parts, list) or any(not _text(part) for part in parts)):
        raise ValueError('Visible identity needs role, references and actual source visible parts')
    value = {key: copy.deepcopy(item[key]) for key in ('id', 'role', 'source_visible_parts')}
    value['scope'] = _scope(item.get('scope', {}))
    value['references'] = []
    for ref in refs:
        coverage, attributes = ref.get('coverage'), ref.get('attributes')
        if (not _text(ref.get('sha256')) or not isinstance(coverage, list) or not coverage or
                any(not _text(part) for part in coverage) or not isinstance(attributes, dict) or
                any(k not in coverage or not _text(v) for k, v in attributes.items()) or
                any(part not in attributes for part in coverage)):
            raise ValueError('Identity reference coverage requires current observed attributes per covered part')
        value['references'].append({**_asset(project, ref),
                                    'coverage': copy.deepcopy(coverage), 'attributes': copy.deepcopy(attributes)})
    return value


def scoped_contract(project, window):
    """Stable scoped configuration for the generation digest, excluding review progress."""
    policy = _load(project)
    if policy is None: return None
    result = {'schema_version': 1, 'stages': [], 'artwork_masters': [], 'visible_identity': []}
    for stage in policy.get('stages', []):
        if _requested(stage) and _matches(project, stage.get('scope', {}), window):
            result['stages'].append(stage_contract(project, stage))
    for key, normalize in (('artwork_masters', _master), ('visible_identity', _identity)):
        for item in policy.get(key, []):
            if _matches(project, item.get('scope', {}), window):
                if key == 'visible_identity' and 'role_slots' in window and item.get('role') not in window['role_slots']:
                    raise ValueError('Visible identity role is not present in this source window')
                result[key].append(normalize(project, item))
    return result


def submission_guard(project, entry):
    """Check conditional gates only; this function never grants submission authority."""
    policy = _load(project)
    if policy is None or entry.get('passthrough'): return None
    window = next((w for w in read(Path(project) / 'plan.json')['windows']
                   if w['window_id'] == entry['window_id']), None)
    if window is None: raise ValueError('Unknown policy window')
    for stage in policy.get('stages', []):
        if not _requested(stage) or not _matches(project, stage.get('scope', {}), window): continue
        current = stage_contract(project, stage)
        approval = stage.get('approval', {})
        if (approval.get('status') != 'approved' or not _text(approval.get('source_message')) or
                approval.get('contract_digest') != digest(current)):
            raise ValueError('Requested stage needs current explicit approved assets and scope')
        actor = approval.get('actor', 'user')
        if actor == 'codex':
            delegation = approval.get('delegation', {})
            if (delegation.get('actor') != 'user' or not _text(delegation.get('source_message')) or
                    not isinstance(delegation.get('stage_ids'), list) or stage['id'] not in delegation['stage_ids'] or
                    _scope(delegation.get('scope', {})) != current['scope']):
                raise ValueError('Codex stage approval requires explicit user delegation for this exact scope')
        elif actor != 'user':
            raise ValueError('Stage approver must be user or explicitly delegated Codex')
    return None


def candidate_guard(project, window, record, entry):
    current = scoped_contract(project, window)
    if current is None or entry.get('passthrough'): return None
    submission_guard(project, entry)
    if window['window_id'] != entry['window_id']:
        raise ValueError('Policy candidate window differs from request')
    if not current['artwork_masters'] and not current['visible_identity']: return None
    actual = _asset(project, {'path': record.get('output_path')})['sha256']
    review = record.get('policy', {})
    if (review.get('contract_digest') != digest(current) or review.get('file_sha256') != actual or
            not _text(entry.get('input_digest')) or review.get('input_digest') != entry['input_digest'] or
            record.get('input_digest') != entry['input_digest']):
        raise ValueError('Policy observations must bind current output bytes, scoped contract and input digest')
    for master in current['artwork_masters']:
        observed = review.get('artwork', {}).get(master['id'], {})
        if (observed.get('status') != 'passed' or observed.get('strictness') != master['strictness'] or
                observed.get('master_sha256') != master['sha256']):
            raise ValueError('Artwork review is pending, failed or does not meet declared strictness')
        for key in ('characteristics', 'anchors', 'state_correspondences'):
            notes = observed.get('observations', {}).get(key, {})
            if any(not _text(notes.get(k)) for k in master[key]):
                raise ValueError('Artwork needs actual observations for every declared feature and state')
    for identity in current['visible_identity']:
        observed = review.get('visible_identity', {}).get(identity['id'], {})
        if (observed.get('status') != 'passed' or
                observed.get('reference_digest') != digest(identity['references'])):
            raise ValueError('Visible identity requires current reference-bound observations')
        parts = observed.get('parts', {})
        covered = {p for ref in identity['references'] for p in ref['coverage']}
        # A face conclusion must be explicitly limited when face is not visible.
        required = set(identity['source_visible_parts']) | set(parts) | {'face'}
        for part in required:
            note = parts.get(part, {})
            assessable = part in identity['source_visible_parts'] and part in covered
            expected = 'passed' if assessable else 'not_assessable'
            attributes = [ref['attributes'][part] for ref in identity['references'] if part in ref['coverage']]
            if (note.get('status') != expected or not _text(note.get('observations')) or
                    (assessable and note.get('reference_attributes') != attributes)):
                raise ValueError('Visible parts require actual current attributes; unavailable parts are not_assessable')
    return None


def final_guard(project, record):
    """Block final-master readiness on unresolved hard issues and non-final acceptance."""
    policy = _load(project)
    path = Path(project) / STATE
    if policy is None and not path.is_file(): return None
    if not path.is_file(): raise ValueError('Production delivery state is pending')
    state = read(path)
    actual = _asset(project, {'path': record.get('output_path')})['sha256']
    if state.get('schema_version') != 1 or state.get('output_sha256') != actual:
        raise ValueError('Delivery state does not bind current output bytes')
    preview = state.get('preview', {})
    if preview.get('status') != 'ready' or preview.get('output_sha256') != actual:
        raise ValueError('Current preview state is pending')
    issues, exceptions = state.get('known_issues'), state.get('exceptions')
    if not isinstance(issues, list) or not isinstance(exceptions, list):
        raise ValueError('Delivery issues and exceptions must be explicit lists')
    for issue in issues:
        if (any(not _text(issue.get(k)) for k in ('id', 'description')) or
                issue.get('severity') not in ('hard', 'soft') or issue.get('status') not in ('open', 'resolved') or
                issue.get('output_sha256') != actual):
            raise ValueError('Known issues must bind specific issues to the current output')
        if issue['severity'] == 'hard' and issue['status'] != 'resolved':
            accepted = any(e.get('issue_id') == issue['id'] and e.get('issue_digest') == digest(issue) and
                           e.get('status') == 'accepted' and
                           e.get('actor') == 'user' and _text(e.get('source_message')) and
                           e.get('output_sha256') == actual for e in exceptions)
            if not accepted: raise ValueError('Unresolved hard requirement blocks final master')
    acceptance = state.get('user_acceptance', {})
    if (acceptance.get('status') != 'final' or acceptance.get('actor') != 'user' or
            not _text(acceptance.get('source_message')) or acceptance.get('output_sha256') != actual):
        raise ValueError('Final master needs actual current user final acceptance; provisional remains provisional')
    return None
