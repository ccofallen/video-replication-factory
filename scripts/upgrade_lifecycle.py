"""Read-only revision allocation and pure source-preserving registry updates.

This module never installs, removes or writes a skill. Call allocation and
persist returned registry copies inside the caller's existing registry lock.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import re


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('A full source SHA256 is required')
    return value


def _positive(value):
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if type(value) is not int or value < 1:
        raise ValueError('Template revision must be a positive integer')
    return value


def _capabilities(value):
    if (not isinstance(value, (list, tuple)) or
            any(not isinstance(c, str) or not c.strip() for c in value)):
        raise ValueError('Required capabilities must be a list of names')
    return set(value)


def _name_revision(name, sha):
    match = re.fullmatch(r'r2va-video-([a-f0-9]{12,64})(?:-v([1-9][0-9]*))?', name or '')
    if not match or not sha.startswith(match[1]):
        raise ValueError('Version name does not match the full source identity')
    return int(match[2] or 1)


def _records(value):
    if isinstance(value, str):
        yield {'name': value}
    elif isinstance(value, list):
        for item in value:
            yield from _records(item)
    elif isinstance(value, dict):
        if 'name' in value:
            yield value
        else:
            for key, item in value.items():
                if key.startswith('r2va-video-') and isinstance(item, dict):
                    yield {'name': key, **item}


def _registry(root, registry):
    if registry is not None:
        return registry
    path = Path(root) / '.video-factory-registry.json'
    return _read(path) if path.exists() else {'schema_version': 1, 'sources': {}}


def list_versions(skills_root, source_sha256, registry=None):
    """List source versions across current, history, removals and install dirs.

    Legacy previous_versions strings and source-scoped versions/history/
    tombstones records are supported. Global history/tombstones may be a list
    of records carrying source_sha256, or a mapping keyed by full source SHA.
    No files, directories, registry values or timestamps are modified.
    """
    sha, root = _sha(source_sha256), Path(skills_root) if skills_root is not None else None
    registry, found = _registry(root, registry), {}
    current = registry.get('sources', {}).get(sha, {})

    def add(record, origin, removed=False, installed=False):
        name = record.get('name')
        revision = _name_revision(name, sha)
        for key in ('template_revision', 'template_version', 'revision'):
            if key in record:
                revision = max(revision, _positive(record[key]))
        item = found.setdefault(name, {'name': name, 'template_revision': revision,
            'installed': False, 'current': name == current.get('name'),
            'removed': False, 'status': record.get('status'), 'origins': set()})
        item['template_revision'] = max(item['template_revision'], revision)
        item['removed'] |= removed or bool(record.get('removed'))
        item['installed'] |= installed
        item['origins'].add(origin)
        if record.get('status') is not None:
            item['status'] = record['status']

    if current.get('name'):
        add(current, 'registry.current')
    for key in ('previous_versions', 'versions', 'history', 'tombstones'):
        for record in _records(current.get(key, [])):
            add(record, 'registry.' + key, removed=key == 'tombstones')
    for key in ('history', 'tombstones'):
        value = registry.get(key, [])
        if isinstance(value, dict) and sha in value:
            records = _records(value[sha])
        else:
            records = (r for r in _records(value) if r.get('source_sha256') == sha)
        for record in records:
            add(record, 'registry.global.' + key, removed=key == 'tombstones')
    if root is not None and root.exists():
        for folder in sorted(root.iterdir()):
            if not folder.is_dir() or folder.is_symlink():
                continue
            try:
                _name_revision(folder.name, sha)
            except ValueError:
                continue
            manifest = _read(folder / 'manifest.json') if (folder / 'manifest.json').is_file() else {}
            if manifest.get('source_sha256', sha) != sha:
                continue
            add({**manifest, 'name': folder.name}, 'installed', installed=True)
    return [{**item, 'origins': sorted(item['origins'])} for item in
            sorted(found.values(), key=lambda row: (row['template_revision'], row['name']))]


def allocate_revision(skills_root, source_sha256, registry=None):
    """Return a new name/revision above every known revision, including removals."""
    sha, root = _sha(source_sha256), Path(skills_root)
    registry = _registry(root, registry)
    rows = list_versions(root, sha, registry)
    entry = registry.get('sources', {}).get(sha, {})
    highest = max([row['template_revision'] for row in rows] + [0])
    if entry.get('max_revision') is not None:
        highest = max(highest, _positive(entry['max_revision']))
    revision = highest + 1
    for length in (12, 24, 64):
        name = 'r2va-video-' + sha[:length] + (f'-v{revision}' if revision > 1 else '')
        if not (root / name).exists() and not (root / name).is_symlink():
            return {'name': name, 'template_revision': revision}
    raise FileExistsError('No collision-free source revision name is available')


def version_metadata(factory_version, template_revision, runtime_digest,
                     required_capabilities=(), *, runtime_version=None):
    """Keep factory release, template revision and runtime identity independent."""
    revision = _positive(template_revision)
    return {'factory_version': factory_version, 'template_revision': revision,
            'template_version': str(revision), 'runtime_version': runtime_version,
            'runtime_digest': runtime_digest, 'required_capabilities': sorted(_capabilities(required_capabilities))}


def record_version(registry, source_sha256, version):
    """Return an idempotent registry update after the caller verifies installation."""
    sha, result = _sha(source_sha256), copy.deepcopy(registry)
    rows = list_versions(None, sha, registry)
    revision = _name_revision(version.get('name'), sha)
    if version.get('template_revision', revision) != revision:
        raise ValueError('Version name and template revision must agree')
    entry = result.setdefault('sources', {}).setdefault(sha, {})
    if entry.get('name') == version['name'] and not entry.get('removed'):
        return result
    maximum = max([r['template_revision'] for r in rows] +
                  [_positive(entry['max_revision']) if entry.get('max_revision') is not None else 0])
    if revision <= maximum:
        raise ValueError('A historical template revision cannot be reused')
    previous = [r['name'] for r in rows if r['name'] != version['name']]
    history = list(entry.get('versions', []))
    if entry.get('name') and not any(r.get('name') == entry['name'] for r in history):
        history.append({key: entry[key] for key in ('name', 'status', 'template_revision') if key in entry})
    history.append({**copy.deepcopy(version), 'template_revision': revision})
    entry.update(copy.deepcopy(version), template_revision=revision, max_revision=revision,
                 previous_versions=previous, versions=history, removed=False)
    return result


def record_removal(registry, source_sha256, name, reason, *, removed_at=None):
    """Return a removal tombstone only; never remove or move the named directory."""
    sha, result = _sha(source_sha256), copy.deepcopy(registry)
    revision = _name_revision(name, sha)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('A removal record needs its actual reason')
    entry = result.setdefault('sources', {}).setdefault(sha, {})
    tombstone = {'name': name, 'template_revision': revision, 'reason': reason, 'removed_at': removed_at}
    tombstones = entry.setdefault('tombstones', [])
    if tombstone not in tombstones:
        tombstones.append(tombstone)
    entry['max_revision'] = max(_positive(entry['max_revision']) if entry.get('max_revision') is not None else 0, revision)
    if entry.get('name') == name:
        entry['removed'] = True
    return result


def _path(root, name):
    if not isinstance(name, str) or not name:
        raise ValueError('Source extension path must be a nonempty relative path')
    path, root = Path(name), Path(root).resolve()
    actual = (root / path).resolve()
    if path.is_absolute() or '..' in path.parts or not actual.is_relative_to(root) or (root / path).is_symlink():
        raise ValueError('Source extension paths must stay relative and contained')
    return actual


def _hash(root, name):
    path = _path(root, name)
    before = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Source evidence or extension changed during hashing')
    return digest


def source_contract(skill):
    """Bind neutral evidence, declared dedicated entry/init/guards, and capabilities."""
    root = Path(skill)
    manifest = _read(root / 'manifest.json')
    meta = _read(root / 'meta.json') if (root / 'meta.json').exists() else {}
    sha = _sha(manifest.get('source_sha256', meta.get('source_sha256')))
    if meta.get('source_sha256', sha) != sha:
        raise ValueError('Source capability metadata has a different source identity')
    declaration = manifest.get('source_capabilities', meta.get('source_capabilities', {}))
    if ('source_capabilities' in manifest and 'source_capabilities' in meta and
            manifest['source_capabilities'] != meta['source_capabilities']):
        raise ValueError('Source capability declarations disagree')
    if not isinstance(declaration, (list, dict)):
        raise ValueError('Source capability declaration must be an object or a capability list')
    capabilities = declaration if isinstance(declaration, list) else declaration.get('required_capabilities', [])
    if not isinstance(capabilities, list) or any(not isinstance(c, str) or not c.strip() for c in capabilities):
        raise ValueError('Required source capabilities must be a list of names')
    required = _capabilities(capabilities) | _capabilities(manifest.get('required_capabilities', []))
    evidence, extensions = {}, {}
    evidence_root = root / 'assets/evidence'
    if evidence_root.exists():
        for path in sorted(evidence_root.rglob('*')):
            if path.is_symlink():
                raise ValueError('Source evidence paths cannot contain symlinks')
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                evidence[relative] = _hash(root, relative)
    if 'assets/evidence/physical-source.json' in evidence:
        required.add('scoped-physical-contract')
        try:facts=_read(root/'assets/evidence/physical-source.json')
        except ValueError as error:raise ValueError('Invalid source physical evidence') from error
        required.update(_capabilities(facts.get('required_capabilities',[])))
        if facts.get('consistency_checks'):required.add('structured-consistency')
    if isinstance(declaration, dict):
        files = declaration.get('files', [])
        if not isinstance(files, list):
            raise ValueError('Source extension files must be an explicit list')
        entries = [declaration[k] for k in ('entrypoint', 'contract_initializer') if declaration.get(k)]
        guards = declaration.get('guards', [])
        if not isinstance(guards, list):
            raise ValueError('Source guards must be an explicit list')
        if any(not isinstance(entry, str) or not entry.strip() for entry in entries + guards):
            raise ValueError('Source entry/init/guard descriptors need explicit paths')
        for entry in entries + guards:
            if not _path(root, entry.split(':', 1)[0]).is_file():
                raise ValueError('Source entry/init/guard provider path is missing')
        # Generic providers may evolve while preserving declared capabilities.
        # Only explicitly source-owned custom files have immutable byte bindings.
        for name in files:
            extensions[name] = _hash(root, name)
    return {'source_sha256': sha, 'source_capabilities': copy.deepcopy(declaration),
            'required_capabilities': sorted(required), 'source_evidence': evidence,
            'source_extensions': extensions}


def _preserved(before, after):
    if isinstance(before, dict):
        return isinstance(after, dict) and all(k in after and _preserved(v, after[k]) for k, v in before.items())
    if isinstance(before, list):
        return isinstance(after, list) and all(item in after for item in before)
    return before == after


def _declaration(value):
    """List and object spellings carry the same requirements, not new powers."""
    value = {'required_capabilities': value} if isinstance(value, list) else copy.deepcopy(value)
    for key in ('required_capabilities', 'files', 'guards'):
        value.setdefault(key, [])
    return value


def verify_source_contract(candidate, previous_contract, available_capabilities):
    """Reject loss of source evidence, dedicated extensions, or runtime capability."""
    current = source_contract(candidate)
    if current['source_sha256'] != previous_contract['source_sha256']:
        raise ValueError('Upgrade changed the source identity')
    for key in ('source_capabilities', 'source_evidence', 'source_extensions'):
        before, after = previous_contract[key], current[key]
        if key == 'source_capabilities':
            before, after = _declaration(before), _declaration(after)
        if not _preserved(before, after):
            raise ValueError('Upgrade dropped or changed required source ' + key)
    required = set(previous_contract['required_capabilities']) | set(current['required_capabilities'])
    if not required.issubset(set(current['required_capabilities'])) or not required.issubset(set(available_capabilities)):
        raise ValueError('Upgrade runtime is missing a required source capability')
    return current
