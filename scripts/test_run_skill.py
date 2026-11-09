"""Unified launcher routes only verified local fixture scripts."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent
LAUNCHER = SCRIPTS / 'run_skill.py'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))


class RunSkillTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(LAUNCHER.is_file(), 'unified launcher missing')
        spec = importlib.util.spec_from_file_location('runtime_binding', SCRIPTS / 'runtime_binding.py')
        self.rb = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.rb)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.runtime = self.root / 'skill'; self.project = self.root / 'run'
        (self.runtime / 'scripts').mkdir(parents=True); self.project.mkdir()
        write(self.runtime / 'meta.json', {'name': 'fixture-skill', 'version': '5', 'available_capabilities': []})
        (self.runtime / 'scripts/factory.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        write(self.runtime / 'manifest.json', {'files': {'scripts/factory.py': hashlib.sha256((self.runtime / 'scripts/factory.py').read_bytes()).hexdigest()}})
        (self.project / 'source.mp4').write_bytes(b'source')
        write(self.project / 'source.json', {'source': {'path': 'source.mp4', 'sha256': hashlib.sha256(b'source').hexdigest()}})
        self.rb.bind(self.project, self.runtime)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(LAUNCHER), *args], capture_output=True, text=True)

    def test_help_does_not_need_project_or_runtime(self):
        result = self.run_cli('--help')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('--project', result.stdout)

    def copied_cli(self, *names):
        import shutil
        for name in ('runtime_binding.py', 'run_skill.py', *names):
            shutil.copy2(SCRIPTS / name, self.runtime / 'scripts' / name)
        write(self.runtime / 'manifest.json', {'files': self.rb.production_files(self.runtime)})
        return self.runtime / 'scripts/run_skill.py'

    def test_factory_static_help_without_project_uses_current_default_runtime(self):
        launcher = self.copied_cli('factory.py', 'media.py')
        directory = self.root / 'help-cwd'; directory.mkdir()
        result = subprocess.run([sys.executable, str(launcher), 'factory', '--help'],
                                cwd=directory, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('prepare', result.stdout)
        self.assertFalse((directory / 'run-runtime.json').exists())
        self.assertFalse((directory / 'source.json').exists())

    def test_actual_workflow_inspect_is_read_only_without_project_binding(self):
        launcher = self.copied_cli('comfy_workflow.py')
        workflow = self.root / 'workflow.json'; write(workflow, {'1': {'class_type': 'LoadImage', 'inputs': {}}})
        report = self.root / 'inspect.json'
        result = subprocess.run([sys.executable, str(launcher), 'comfy_workflow', 'inspect',
                                 '--workflow', str(workflow), '--out', str(report)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('api', json.loads(report.read_text())['workflow_format'])
        self.assertFalse((self.root / 'run-runtime.json').exists())

    def test_h3_profile_typed_reference_options_require_current_binding(self):
        (self.runtime / 'scripts/comfy_workflow.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        write(self.runtime / 'manifest.json', {'files': self.rb.production_files(self.runtime)})
        self.rb.bind(self.project, self.runtime, adopt=True, source_message='fixture adds actual CLI route')
        arguments = ['h3-profile', '--workflow', 'workflow.json', '--url', 'http://127.0.0.1:8188',
                     '--out', 'profile.json', '--reference-slots', '2',
                     '--quality-level', '1', '--workflow-out', 'local/current.json']
        result = self.run_cli('--project', str(self.project), 'comfy_workflow.py', *arguments)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('--reference-slots', json.loads(result.stdout))
        (self.project / 'run-runtime.json').unlink()
        result = self.run_cli('--project', str(self.project), '--skill', str(self.runtime),
                              'comfy_workflow.py', *arguments)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('', result.stdout)

    def workflow_parser_fixture(self):
        script = self.runtime / 'scripts/runninghub_workflow.py'
        script.write_text("""import argparse,json
parser=argparse.ArgumentParser()
parser.add_argument('--config')
commands=parser.add_subparsers(dest='command',required=True)
for command in ('check','status','submit','recover','prepare','prepare-factory','profile'):
    child=commands.add_parser(command)
    if command in ('prepare','prepare-factory','profile'): child.add_argument('--project',required=True)
    for option in ('window','video','image','prompt-file','seed','aspect-ratio','megapixels','instance-type',
                   'request','approve-digest','production-request','attempt','task-id'):
        child.add_argument('--'+option)
print(json.dumps(vars(parser.parse_args())))
""")
        write(self.runtime / 'manifest.json', {'files': self.rb.production_files(self.runtime)})
        return script

    def test_actual_runninghub_status_keeps_global_config_and_omits_target_project(self):
        launcher = self.copied_cli('runninghub_workflow.py', 'rh_runner.py', 'factory.py', 'media.py')
        (self.project / 'run-runtime.json').unlink()
        config = self.root / 'offline-connection.json'; write(config, {})
        environment = dict(os.environ, CODEX_HOME=str(self.root / 'isolated-private-state'))
        result = subprocess.run([sys.executable, str(launcher), '--project', str(self.project),
                                 'runninghub_workflow.py', '--config', str(config), 'status'],
                                cwd=self.root, env=environment, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], json.loads(result.stdout)['attempts'])
        self.assertFalse((self.root / 'isolated-private-state').exists())

    def test_runninghub_recover_routes_without_binding_and_without_target_project(self):
        self.workflow_parser_fixture(); (self.project / 'run-runtime.json').unlink()
        result = self.run_cli('--project', str(self.project), '--skill', str(self.runtime),
                              'runninghub_workflow.py', '--config', 'offline.json', 'recover',
                              '--attempt', 'original-ledger-id', '--task-id', 'original-paid-id')
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual('offline.json', report['config'])
        self.assertEqual('original-paid-id', report['task_id'])
        self.assertNotIn('project', report)

    def test_runninghub_profile_forwards_project_and_preserves_config_before_command(self):
        self.workflow_parser_fixture()
        self.rb.bind(self.project, self.runtime, adopt=True, source_message='fixture adds workflow CLI')
        result = self.run_cli('--project', str(self.project), 'runninghub_workflow.py',
                              '--config', 'offline.json', 'profile', '--seed', '42', '--instance-type', 'plus')
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(str(self.project.resolve()), report['project'])
        self.assertEqual('offline.json', report['config'])

    def test_wrong_runtime_runninghub_submit_is_rejected_before_target_execution(self):
        import shutil
        other = self.root / 'other-runtime'; shutil.copytree(self.runtime, other)
        (other / 'scripts/runninghub_workflow.py').write_text('print("UNEXPECTED PAID SUBMISSION")')
        write(other / 'manifest.json', {'files': self.rb.production_files(other)})
        result = self.run_cli('--project', str(self.project), '--skill', str(other),
                              'runninghub_workflow.py', '--config', 'status', 'submit', '--request', 'request.json',
                              '--approve-digest', 'current-sha', '--production-request', 'current user authorization')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('', result.stdout)

    def test_bound_runtime_selected_and_actual_project_forwarded(self):
        result = self.run_cli('--project', str(self.project), 'factory.py', 'prepare', '--output', 'draft.mp4')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['prepare', '--output', 'draft.mp4', '--project', str(self.project.resolve())], json.loads(result.stdout))

    def test_explicit_other_runtime_cannot_bypass_existing_binding(self):
        other = self.root / 'other'; import shutil; shutil.copytree(self.runtime, other)
        result = self.run_cli('--project', str(self.project), '--skill', str(other), 'factory.py', 'prepare')
        self.assertNotEqual(0, result.returncode)

    def test_unlisted_script_or_path_escape_is_rejected(self):
        for target in ('arbitrary.py', '../factory.py', '/tmp/factory.py'):
            with self.subTest(target=target):
                self.assertNotEqual(0, self.run_cli('--project', str(self.project), target, 'prepare').returncode)

    def test_stale_manifest_refuses_even_current_rebound_runtime(self):
        (self.runtime / 'scripts/factory.py').write_text('print("changed")')
        self.rb.bind(self.project, self.runtime, adopt=True, source_message='migrate changed fixture')
        result = self.run_cli('--project', str(self.project), 'factory.py', 'prepare')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn('changed', result.stdout)

    def test_changed_runtime_blocks_new_generation_before_script_execution(self):
        (self.runtime / 'scripts/factory.py').write_text('print("should not execute")')
        result = self.run_cli('--project', str(self.project), 'factory.py', 'prepare')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn('should not execute', result.stdout)

    def test_original_id_recovery_can_run_without_binding(self):
        (self.project / 'run-runtime.json').unlink()
        (self.runtime / 'scripts/rh_runner.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        write(self.runtime / 'manifest.json', {'files': self.rb.production_files(self.runtime)})
        result = self.run_cli('--project', str(self.project), '--skill', str(self.runtime), 'rh_runner.py', 'recover-unknown', '--attempt', 'original', '--task-id', 'known')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('known', result.stdout)

    def test_known_id_rh_recovery_only_command_routes_without_legacy_binding(self):
        (self.project / 'run-runtime.json').unlink()
        (self.runtime / 'scripts/rh_runner.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        write(self.runtime / 'manifest.json', {'files': self.rb.production_files(self.runtime)})
        result = self.run_cli('--project', str(self.project), '--skill', str(self.runtime),
                              'rh_runner.py', '--account', 'status', 'recover', '--attempt', 'original-paid-id')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('original-paid-id', result.stdout)

    def test_option_values_cannot_impersonate_read_only_commands(self):
        import shutil
        other = self.root / 'other'; shutil.copytree(self.runtime, other)
        (other / 'scripts/rh_runner.py').write_text('print("WRONG RUNTIME EXECUTED")')
        write(other / 'manifest.json', {'files': self.rb.production_files(other)})
        result = self.run_cli('--project', str(self.project), '--skill', str(other), 'rh_runner.py',
                              '--account', 'status', 'resume')
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn('WRONG RUNTIME EXECUTED', result.stdout)

    def test_library_modules_and_nonexistent_cli_commands_are_rejected(self):
        for script, arguments in (('postproduction.py', []), ('identity_clock.py', ['restore']),
                                  ('factory.py', ['status']), ('rh_runner.py', ['query'])):
            with self.subTest(script=script, arguments=arguments):
                result = self.run_cli('--project', str(self.project), script, *arguments)
                self.assertNotEqual(0, result.returncode)

    def test_explicit_runtime_binding_adoption_bootstrap_reaches_module_checks(self):
        (self.project / 'run-runtime.json').unlink()
        import shutil
        shutil.copy2(SCRIPTS / 'runtime_binding.py', self.runtime / 'scripts/runtime_binding.py')
        write(self.runtime / 'manifest.json', {'files': self.rb.production_files(self.runtime)})
        result = self.run_cli('--project', str(self.project), '--skill', str(self.runtime),
                              'runtime_binding.py', 'adopt', '--source-message', 'user adopts fixture')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('user adopts fixture', json.loads(result.stdout)['adoption']['source_message'])

    def test_ingest_bootstrap_requires_empty_new_project_and_explicit_runtime(self):
        new_project = self.root / 'new-run'; new_project.mkdir()
        allowed = self.run_cli('--project', str(new_project), '--skill', str(self.runtime),
                               'factory.py', 'ingest', '--video', 'input.mp4')
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        denied = self.run_cli('--project', str(new_project), 'factory.py', 'ingest', '--video', 'input.mp4')
        self.assertNotEqual(0, denied.returncode)
        (new_project / 'existing.txt').write_text('not a fresh run')
        denied = self.run_cli('--project', str(new_project), '--skill', str(self.runtime),
                              'factory.py', 'ingest', '--video', 'input.mp4')
        self.assertNotEqual(0, denied.returncode)

    def test_typed_parser_rejects_unknown_options_before_any_script_runs(self):
        result = self.run_cli('--project', str(self.project), 'factory.py', '--unknown', 'status', 'prepare')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('', result.stdout)


if __name__ == '__main__': unittest.main()
