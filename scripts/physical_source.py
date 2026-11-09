"""Author source-bound physical facts; drafts and mechanical checks never approve pixels.

Activation changes the source contract, not generation authorization or an existing
runtime binding. Adopt/migrate that binding explicitly within actual authorization.
"""
from __future__ import annotations
import argparse
import copy
import importlib
import json
import os
from pathlib import Path
import tempfile
import media

DEFAULT = 'evidence/physical-source.draft.json'
ACTIVE = ('assets/evidence/physical-source.json', 'evidence/physical-source.json')
CRITERIA = ('surfaces', 'connections', 'fold_state', 'artwork', 'openings',
            'stacking', 'occlusion', 'continuity', 'text_legibility')
REQUIRED = ('scoped-physical-contract', 'structured-consistency')


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _root(project):
    path = Path(project)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Source authoring needs an existing nonsymlink run directory')
    return path.resolve()


def _path(project, relative):
    root = _root(project)
    if not isinstance(relative, (str, Path)) or not str(relative):
        raise ValueError('Source artifact path must be nonempty and relative')
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Source artifact paths must be relative and contained')
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('Source artifact paths cannot contain symlinks')
    if not current.resolve().is_relative_to(root):
        raise ValueError('Source artifact path escapes the run')
    return current


def _read(project, relative):
    return json.loads(_path(project, relative).read_text(encoding='utf-8-sig'))


def _write(project, relative, value, *, replace=False):
    path = _path(project, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    _path(project, relative)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix=path.name+'.tmp-',
                                     dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
    try:
        if replace:
            os.replace(temporary, path)
        else:
            # Publish a complete file without ever replacing a concurrent writer.
            try: os.link(temporary, path)
            except FileExistsError:
                if _read(project, relative) != value:
                    raise ValueError('A different source artifact already exists')
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _source(project, *, decode=False, reviewed=False, verify_bytes=False, deps=None, scalar_cpu=False):
    source = _read(project, 'source.json')
    original, video = source.get('source', {}), source.get('video', {})
    if not _text(original.get('sha256')) or type(video.get('frame_count')) is not int or video['frame_count'] <= 0:
        raise ValueError('Source metadata needs actual source SHA and decoded frame count')
    path = _path(project, original.get('path'))
    if decode or verify_bytes:
        actual = media.signature(path)
        if actual['sha256'] != original['sha256'] or ('size_bytes' in original and actual['size_bytes'] != original['size_bytes']):
            raise ValueError('Current source bytes differ from the recorded source SHA')
    if reviewed:
        analysis = _read(project, 'analysis.json')
        if analysis.get('status') != 'passed' or analysis.get('source_sha256') != original['sha256']:
            raise ValueError('Current passed source analysis is required')
    if decode:
        report = media.inspect(path, deps, scalar_cpu)
        if report['video']['frame_count'] != video['frame_count']:
            raise ValueError('Source frame_count differs from the actual decoded source')
        if media.signature(path) != actual:
            raise ValueError('Source bytes changed during decoded validation')
    return source


def _interval(value, count, bounds=None):
    if (not isinstance(value, list) or len(value) != 2 or any(type(i) is not int for i in value) or
            not 0 <= value[0] < value[1] <= count or
            (bounds is not None and not bounds[0] <= value[0] < value[1] <= bounds[1])):
        raise ValueError('Source interval must lie inside the decoded source and product interval')
    return value


def _capabilities(value):
    if not isinstance(value, list) or any(not _text(item) for item in value):
        raise ValueError('Source required capabilities must be an explicit list')
    return sorted(set(value))


def draft(project, product_ids=None, *, draft_relative=DEFAULT):
    """Create/preserve a pending draft; IDs are declared inputs, never inferred geometry."""
    source = _source(project, verify_bytes=True)
    path = _path(project, draft_relative)
    if any(path == _path(project, active) for active in ACTIVE):
        raise ValueError('A pending draft cannot use an active source-facts path')
    if path.exists():
        existing = _read(project, draft_relative)
        if existing.get('source_sha256') != source['source']['sha256'] or not isinstance(existing.get('source_review'), dict):
            raise ValueError('Existing draft does not bind this source review')
        return path
    if product_ids is None:
        job_path = _path(project, 'job.json')
        job = _read(project, 'job.json') if job_path.is_file() else {}
        product_ids = [row.get('product') for row in job.get('media_references', []) if
                       isinstance(row, dict) and row.get('purpose') == 'product']
    if not isinstance(product_ids, (list, tuple)) or any(not _text(ident) for ident in product_ids):
        raise ValueError('Source product IDs must be explicit nonempty names')
    products = {ident: {'source_interval': None, 'panels': {}, 'hinges': []} for ident in product_ids}
    value = {'schema_version': 1, 'source_sha256': source['source']['sha256'],
        'frame_count': source['video']['frame_count'], 'products': products, 'rules': [], 'consistency_checks': [],
        'source_review': {'status': 'pending', 'notes': '',
            'capture': {key: {'status': 'unknown', 'notes': '', 'check_ids': []} for key in CRITERIA}}}
    return _write(project, draft_relative, value)


def _checks(facts):
    checks = facts.get('consistency_checks', [])
    if not isinstance(checks, list):
        raise ValueError('Source consistency_checks must be a list')
    try:
        provider = importlib.import_module('consistency_review')
    except ModuleNotFoundError as error:
        if error.name != 'consistency_review': raise
    else:
        return provider.validate_checks(facts)
    # Older runtimes can inspect legacy facts without a new optional provider.
    # New authoring still checks IDs/state clocks before recording a requirement
    # that prevents such a runtime from submitting the activated contract.
    seen = set()
    for check in checks:
        if not isinstance(check, dict) or not _text(check.get('id')) or check['id'] in seen:
            raise ValueError('Source consistency check IDs must be unique')
        seen.add(check['id'])
        product = facts['products'].get(check.get('product'), {})
        scope = _interval(check.get('source_interval'), facts['frame_count'], product.get('source_interval'))
        if check.get('panel') not in product.get('panels', {}) or check.get('criterion') not in CRITERIA:
            raise ValueError('Source consistency check needs a known panel and criterion')
        states = check.get('states')
        if not isinstance(states, list) or not states:
            raise ValueError('Source checks need actual source states')
        for state in states:
            if (not isinstance(state, dict) or type(state.get('source_frame')) is not int or
                    not scope[0] <= state['source_frame'] < scope[1] or not _text(state.get('description'))):
                raise ValueError('Source check state needs a valid source frame and description')
    return checks


def validate_source_structure(project, facts, decode=True, *, deps=None, scalar_cpu=False):
    """Validate reviewed definitions, not their visual truth; legacy facts remain legacy.

    decode=False is for a runtime that separately verifies current source bytes;
    it checks recorded source SHA/frame-count/analysis without decoding again.
    """
    source = _source(project, decode=decode, reviewed=True, deps=deps, scalar_cpu=scalar_cpu)
    if not isinstance(facts, dict) or facts.get('schema_version') != 1:
        raise ValueError('Physical source facts require schema_version1')
    facts = copy.deepcopy(facts)
    count = source['video']['frame_count']
    if (facts.get('source_sha256') != source['source']['sha256'] or
            type(facts.get('frame_count')) is not int or facts['frame_count'] != count):
        raise ValueError('Physical facts must bind the current source SHA and decoded frame_count')
    required = _capabilities(facts.get('required_capabilities', []))
    authored = 'source_review' in facts or 'structured-consistency' in required
    products, rules = facts.get('products'), facts.get('rules')
    if not authored:
        if not isinstance(products, dict) or not isinstance(rules, list):
            raise ValueError('Legacy source facts need product and rule catalogs')
        if 'consistency_checks' in facts:
            facts['consistency_checks'] = _checks(facts)
        return facts
    if not isinstance(products, dict) or not products:
        raise ValueError('Reviewed physical facts need at least one declared product')
    for ident, product in products.items():
        if not _text(ident) or not isinstance(product, dict):
            raise ValueError('Source products need explicit IDs and observed structure')
        _interval(product.get('source_interval'), count)
        panels, hinges = product.get('panels'), product.get('hinges')
        if (not isinstance(panels, dict) or not panels or any(not _text(k) or not _text(v) for k, v in panels.items()) or
                not isinstance(hinges, list) or any(not _text(value) for value in hinges)):
            raise ValueError('Source products need nonempty observed panels and explicit hinge facts')
    if not isinstance(rules, list):
        raise ValueError('Source rules must be a list')
    by_id = {}
    for rule in rules:
        if not isinstance(rule, dict) or not _text(rule.get('id')) or rule['id'] in by_id:
            raise ValueError('Source rule IDs must be unique')
        product = products.get(rule.get('product'), {})
        if rule.get('panel') not in product.get('panels', {}):
            raise ValueError('Source rule must name a known product and panel')
        _interval(rule.get('source_interval'), count, product['source_interval'])
        if (any(not _text(rule.get(k)) for k in ('attribute', 'expected', 'basis')) or rule.get('origin') != 'source' or
                not isinstance(rule.get('supersedes'), list) or any(not _text(i) for i in rule['supersedes'])):
            raise ValueError('Inherited source rules need observed source origin, basis and explicit supersedes')
        by_id[rule['id']] = rule
    if any(ref not in by_id for rule in rules for ref in rule['supersedes']):
        raise ValueError('Source supersedes must reference actual source rule IDs')
    visited, visiting = set(), set()
    def visit(ident):
        if ident in visiting:
            raise ValueError('Source supersedes cannot be cyclic')
        if ident in visited:
            return
        visiting.add(ident)
        rule = by_id[ident]
        for ref in rule['supersedes']:
            previous = by_id[ref]
            if (any(rule[key] != previous[key] for key in ('product', 'panel', 'attribute')) or
                    max(rule['source_interval'][0], previous['source_interval'][0]) >=
                    min(rule['source_interval'][1], previous['source_interval'][1])):
                raise ValueError('Source supersedes must name an overlapping rule for the same physical face/attribute')
            visit(ref)
        visiting.remove(ident); visited.add(ident)
    for ident in by_id:
        visit(ident)
    checks = _checks(facts)
    facts['consistency_checks'] = checks
    review = facts.get('source_review', {})
    capture = review.get('capture', {}) if isinstance(review, dict) else {}
    if (not isinstance(review, dict) or review.get('status') != 'passed' or not _text(review.get('notes')) or
            not isinstance(capture, dict) or set(capture) != set(CRITERIA)):
        raise ValueError('New source review must be passed with actual notes and all nine capture criteria')
    by_check = {check['id']: check for check in checks}
    for criterion, record in capture.items():
        if (not isinstance(record, dict) or record.get('status') not in ('observed', 'not_applicable') or
                not _text(record.get('notes')) or not isinstance(record.get('check_ids'), list) or
                any(not _text(i) for i in record['check_ids']) or len(set(record['check_ids'])) != len(record['check_ids'])):
            raise ValueError('Source capture remains pending: unknown or missing actual observations')
        ids = record['check_ids']
        if record['status'] == 'observed' and not ids:
            raise ValueError('An observed source criterion must reference actual consistency check IDs')
        if record['status'] == 'not_applicable' and ids:
            raise ValueError('Not-applicable source criteria cannot claim observed checks')
        if any(ident not in by_check or by_check[ident]['criterion'] != criterion for ident in ids):
            raise ValueError('Source capture check IDs must match this exact criterion')
    facts['required_capabilities'] = sorted(set(required) | set(REQUIRED))
    return facts


def validate(project, draft_relative=DEFAULT, *, deps=None, scalar_cpu=False):
    """Return actual reviewed facts without writing or activating anything."""
    facts = _read(project, draft_relative)
    if not isinstance(facts, dict) or 'source_review' not in facts:
        raise ValueError('Authoring validation requires an explicit current source review')
    return validate_source_structure(project, facts, deps=deps, scalar_cpu=scalar_cpu)


def _marked_source(source):
    source = copy.deepcopy(source)
    declaration = source.get('source_capabilities', [])
    if isinstance(declaration, dict):
        declaration['required_capabilities'] = sorted(set(_capabilities(declaration.get('required_capabilities', []))) | set(REQUIRED))
    else:
        declaration = sorted(set(_capabilities(declaration)) | set(REQUIRED))
    source['source_capabilities'] = declaration
    return source


def activate(project, draft_relative=DEFAULT, *, deps=None, scalar_cpu=False):
    """Publish reviewed facts and pending targets; never migrate/authorize/approve a run."""
    facts = validate(project, draft_relative, deps=deps, scalar_cpu=scalar_cpu)
    source = _source(project, reviewed=True, verify_bytes=True)
    if source['source']['sha256'] != facts['source_sha256'] or source['video']['frame_count'] != facts['frame_count']:
        raise ValueError('Source changed after physical source validation')
    marked = _marked_source(source)
    for relative in (*ACTIVE, 'production-contract.json', 'physical-reviews.json'):
        path = _path(project, relative)
        if relative in ACTIVE and path.exists() and _read(project, relative) != facts:
            raise ValueError('Different active physical source facts exist; resolve the conflict explicitly')
    _write(project, ACTIVE[1], facts)
    import physical_contract
    physical_contract.init_run(project)
    if _read(project, 'source.json') != source:
        raise ValueError('Source metadata changed during physical source activation')
    if marked != source:
        _write(project, 'source.json', marked, replace=True)
    return facts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('draft', 'validate', 'activate'))
    parser.add_argument('--project', required=True)
    parser.add_argument('--draft', default=DEFAULT, help='Contained draft JSON path')
    parser.add_argument('--product', action='append', help='Explicit source product ID; draft only')
    parser.add_argument('--deps', help='Existing media dependency directory for decoded validation')
    parser.add_argument('--scalar-cpu', action='store_true', help='Existing supported Windows scalar media mode')
    args = parser.parse_args(argv)
    if args.product and args.command != 'draft': parser.error('--product only applies to draft')
    if args.command == 'draft':
        path = draft(args.project, args.product, draft_relative=args.draft)
        result = {'draft': path.relative_to(_root(args.project)).as_posix(), 'status': 'pending', 'active': False}
    elif args.command == 'validate':
        result = validate(args.project, args.draft, deps=args.deps, scalar_cpu=args.scalar_cpu)
    else:
        result = {'status': 'activated', 'facts': activate(args.project, args.draft, deps=args.deps, scalar_cpu=args.scalar_cpu),
                  'runtime_binding': 'Existing run binding must be explicitly migrated within actual authorization; no new submission is authorized.'}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, TypeError) as error: raise SystemExit(str(error))
