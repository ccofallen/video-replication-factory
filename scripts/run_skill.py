"""Run a verified project-aware CLI from a bound runtime.

Usage: run-skill --project RUN [--skill ID_OR_PATH] factory.py prepare ...
Wrapper options precede the script. Options after it belong to that script.
Only explicit binding commands, and explicit-skill ingestion/instantiation into
an empty new run, bootstrap without a binding. Scripts enforce their own authority.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path
import runtime_binding

# Project forwarding follows each actual CLI. Library modules have no launcher entry.
CLI = {
    'factory.py': (('ingest', 'validate-analysis', 'prepare', 'review-guard', 'assemble', 'build-skill',
        'recover-install', 'instantiate', 'inspect-candidate', 'refresh-plan', 'post-init', 'post-render',
        'post-guard', 'version-list','consistency-evidence'),
        ('video', 'skill', 'source-sha256', 'config', 'window-id', 'task-id', 'candidate', 'deps',
         'output', 'out', 'skills-root', 'status', 'display-name', 'delivery-review'),
        ('scalar-cpu', 'approve-semantics', 'approve-projection', 'final', 'upgrade-runtime')),
    'rh_runner.py': (('tick', 'status', 'stop', 'resume', 'recover', 'recover-unknown', 'visual-failed', 'pilot-promote'),
        ('ledger', 'key-file', 'account', 'attempt', 'task-id', 'failure-record', 'window-id'), ()),
    'comfy_runner.py': (('tick', 'recover', 'select-output', 'status', 'stop', 'resume'),
        ('ledger', 'url', 'deps', 'attempt', 'selection'), ('scalar-cpu',)),
    'physical_contract.py': (('init', 'check', 'status'), ('window-id',), ()),
    'physical_source.py': (('draft','validate','activate'),('draft','product','deps'),('scalar-cpu',)),
    'runninghub_workflow.py': (('check', 'status', 'prepare', 'prepare-factory', 'profile', 'submit', 'recover'),
        ('config', 'window', 'video', 'image', 'prompt-file', 'seed', 'aspect-ratio', 'megapixels',
         'instance-type', 'request', 'approve-digest', 'production-request', 'attempt', 'task-id'), ()),
    'comfy_workflow.py': (('inspect', 'h3-profile'),
        ('workflow', 'url', 'schemas', 'out', 'identity-slots', 'reference-slots', 'quality-level', 'workflow-out'), ()),
    'runtime_binding.py': (('bind', 'adopt', 'migrate', 'diagnose'), ('runtime-root', 'source-message'), ()),
    'candidate_review.py': (('evidence', 'map', 'verify-rgb'),
        ('window-id', 'candidate', 'out', 'mapping', 'rois', 'deps', 'plan', 'video', 'ffmpeg', 'ffprobe'),
        ('native-all', 'scalar-cpu')),
    'cost_audit.py': ((), ('ledger', 'account', 'out', 'scenario-reduction'), ()),
    'face_swap.py': (('tick-pilot',), ('ledger', 'key-file', 'account'), ()),
}
SCRIPTS = frozenset(CLI)
READ_ONLY = {('runninghub_workflow.py', 'check'): 'inspect',
    ('runninghub_workflow.py', 'status'): 'status', ('runninghub_workflow.py', 'recover'): 'recover',
    ('comfy_workflow.py', 'inspect'): 'inspect', ('rh_runner.py', 'status'): 'status', ('rh_runner.py', 'recover'): 'recover', ('rh_runner.py', 'recover-unknown'): 'recover-unknown',
    ('comfy_runner.py', 'status'): 'status', ('comfy_runner.py', 'recover'): 'recover',
    ('physical_contract.py', 'status'): 'status', ('physical_contract.py', 'check'): 'physical-check',
    ('physical_source.py','validate'):'physical-check',
    ('runtime_binding.py', 'diagnose'): 'diagnose', ('factory.py', 'validate-analysis'): 'validate-analysis',
    ('factory.py', 'version-list'): 'version-list', ('cost_audit.py', 'cost-audit'): 'cost-audit'}


class Parser(argparse.ArgumentParser):
    def error(self, message): raise ValueError(message)


def _parsed(script, arguments):
    if script not in CLI: raise ValueError('Requested script is outside the project-aware CLI whitelist')
    commands, values, flags = CLI[script]
    parser = Parser(prog=script, add_help=False, allow_abbrev=False)
    if commands: parser.add_argument('command', choices=commands, nargs='?')
    parser.add_argument('--project')
    parser.add_argument('--help', '-h', action='store_true')
    for name in values: parser.add_argument('--' + name, action='append' if name in ('window-id', 'scenario-reduction', 'image','product') else 'store')
    for name in flags: parser.add_argument('--' + name, action='store_true')
    parsed = parser.parse_args(arguments)
    if parsed.help: return 'help', parsed
    if commands and parsed.command is None: raise ValueError('An actual supported CLI command is required')
    return parsed.command if commands else 'cost-audit', parsed


def operation_for(script, arguments):
    """Parse known option arities, so option values cannot impersonate commands."""
    return _parsed(script, list(arguments))[0]


def _skill(value):
    path = Path(value).expanduser()
    if path.is_dir(): return path.resolve()
    if path.name != value or value in ('.', '..'):
        raise ValueError('Explicit skill must be an existing runtime directory or installed skill ID')
    roots = [runtime_binding.ROOT.parent, Path.home() / '.agents/skills',
             Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills']
    matches = {(root / value).resolve() for root in roots if (root / value).is_dir()}
    if len(matches) != 1: raise ValueError('Explicit skill ID is missing or ambiguous; pass its directory')
    return matches.pop()


def _without_project(arguments):
    result, skip = [], False
    for argument in arguments:
        if skip: skip = False; continue
        if argument == '--project': skip = True
        elif not argument.startswith('--project='): result.append(argument)
    return result


def resolve_launch(project, script, args=None, skill=None):
    """Validate typed operation, runtime binding and manifest before any execution."""
    if script and not script.endswith('.py'): script += '.py'
    if script not in SCRIPTS or Path(script).name != script:
        raise ValueError('Requested script is outside the project-aware CLI whitelist')
    arguments = list(args or []); operation, parsed = _parsed(script, arguments)
    project = Path(project).expanduser().resolve()
    if parsed.project and Path(parsed.project).expanduser().resolve() != project:
        raise ValueError('Forwarded project differs from selected project')
    if project.exists() and not project.is_dir(): raise ValueError('Project must be a directory')
    binding_path = project / 'run-runtime.json'
    binding = runtime_binding.read(binding_path) if binding_path.is_file() else {}
    runtime = _skill(skill) if skill else Path(binding.get('runtime_root', runtime_binding.ROOT)).resolve()
    binding_command = script == 'runtime_binding.py' and operation in ('bind', 'adopt', 'migrate')
    bootstrap = (script == 'factory.py' and operation in ('ingest', 'instantiate') and skill is not None and
                 (not project.exists() or not any(project.iterdir())))
    if not binding_command and not bootstrap:
        runtime_binding.guard(project, 'status' if operation == 'help' else READ_ONLY.get((script, operation), operation), runtime)
    elif binding_command and parsed.runtime_root and Path(parsed.runtime_root).expanduser().resolve() != runtime:
        raise ValueError('Binding runtime-root must equal the selected verified skill')
    files = runtime_binding.production_files(runtime)
    declared = runtime_binding.read(runtime / 'manifest.json').get('files', {})
    if not isinstance(declared, dict) or any(declared.get(name) != sha for name, sha in files.items()):
        raise ValueError('Runtime production files do not match the packaged manifest')
    target = runtime_binding._path(runtime, 'scripts/' + script)
    if 'scripts/' + script not in files: raise ValueError('Requested CLI is missing from selected runtime')
    forwarded = _without_project(arguments)
    if bootstrap and operation == 'instantiate' and not parsed.skill:
        forwarded.extend(('--skill', str(runtime)))
    if script != 'runninghub_workflow.py' or operation in ('prepare', 'prepare-factory', 'profile'):
        forwarded.extend(('--project', str(project)))
    return {'runtime_root': str(runtime), 'script': str(target), 'operation': operation,
            'command': [sys.executable, str(target), *forwarded]}


def main(argv=None):
    parser = Parser(description=__doc__, add_help=False, allow_abbrev=False)
    parser.add_argument('--project'); parser.add_argument('--skill', help='Actual runtime directory or installed skill ID')
    parser.add_argument('script', nargs='?'); parser.add_argument('arguments', nargs=argparse.REMAINDER)
    values = list(sys.argv[1:] if argv is None else argv)
    if values in (['--help'], ['-h']): parser.print_help(); return 0
    args = parser.parse_args(values)
    if args.script is None: parser.error('--project and a project-aware script are required (use --help)')
    script = args.script if args.script.endswith('.py') else args.script + '.py'
    operation, target = _parsed(script, args.arguments)
    project = args.project or target.project
    if project is None and (operation == 'help' or (script == 'comfy_workflow.py' and operation == 'inspect')):
        project = Path.cwd()
    if project is None: parser.error('--project is required')
    launch = resolve_launch(project, args.script, args.arguments, args.skill)
    os.execv(sys.executable, launch['command'])


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise SystemExit(str(error))
