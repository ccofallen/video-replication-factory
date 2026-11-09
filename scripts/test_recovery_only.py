"""Exercise the real recovery CLI against an isolated ledger and fake provider I/O."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import rh_runner as rh


class LocalProvider:
    """Only the provider boundary is replaced; submit/upload are forbidden."""
    def __init__(self, task_id='original-paid-task'):
        self.task_id = task_id

    def query(self, task_id):
        if task_id != self.task_id:
            raise AssertionError('Recovery queried a different task')
        return {'taskId': task_id, 'status': 'SUCCESS',
                'results': [{'url': 'https://offline.invalid/result.mp4', 'outputType': 'mp4'}]}

    def download(self, url, destination):
        if url != 'https://offline.invalid/result.mp4':
            raise AssertionError('Recovery downloaded a different result')
        path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'recovered-original-output')

    def submit(self, *args, **kwargs):
        raise AssertionError('Recovery must never POST a new task')

    def upload(self, *args, **kwargs):
        raise AssertionError('Recovery must never upload generation inputs')


class RecoveryOnlyCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.project = self.root / 'legacy-project'; self.project.mkdir()
        self.ledger_path = self.root / 'private' / 'tasks.sqlite'
        self.key = self.root / 'fake-key.txt'; self.key.write_text('offline-fixture-key')
        ledger = rh.Ledger(self.ledger_path)
        self.attempt = ledger.reserve('offline-account', self.project, 'window-one', 'original-input-digest')
        ledger.update(self.attempt, state='RUNNING', task_id='original-paid-task', next_poll=0)
        ledger.close()
        self.provider = LocalProvider()

    def row(self):
        ledger = rh.Ledger(self.ledger_path)
        try:
            return ledger.row(self.attempt), ledger.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
        finally: ledger.close()

    def update(self, **values):
        ledger = rh.Ledger(self.ledger_path)
        try: ledger.update(self.attempt, **values)
        finally: ledger.close()

    def cli(self, command='recover', account='offline-account', project=None, task_id=None):
        args = ['rh_runner.py', command, '--account', account, '--project', str(project or self.project),
                '--ledger', str(self.ledger_path), '--key-file', str(self.key), '--attempt', self.attempt]
        if task_id: args.extend(('--task-id', task_id))
        output = io.StringIO(); code = 0
        with patch('sys.argv', args), patch.object(rh, 'Transport', return_value=self.provider), contextlib.redirect_stdout(output):
            try: rh.main()
            except SystemExit as error: code = error.code
        return code, json.loads(output.getvalue())

    def test_original_running_id_queries_and_downloads_without_post_or_new_attempt(self):
        self.assertFalse((self.project / 'run-runtime.json').exists())
        code, result = self.cli()
        self.assertEqual(0, code, result)
        row, count = self.row()
        self.assertEqual(1, count)
        self.assertEqual('original-paid-task', row['task_id'])
        self.assertEqual('original-input-digest', row['digest'])
        self.assertEqual('DOWNLOADED', row['state'])
        self.assertEqual(b'recovered-original-output', Path(row['output']).read_bytes())

    def test_recovery_rejects_account_and_project_mismatch_before_provider_io(self):
        for mismatch in ('account', 'project'):
            before, _ = self.row()
            with self.subTest(mismatch=mismatch):
                code, result = self.cli(account='different-account' if mismatch == 'account' else 'offline-account',
                                        project=self.root / 'different-project' if mismatch == 'project' else self.project)
                self.assertEqual(1, code, result)
                self.assertIn(mismatch, result.get('reason', '').lower())
                self.assertEqual(before, self.row()[0])
                self.assertEqual(1, self.row()[1])
                self.assertFalse((self.project / 'candidates').exists())

    def test_uncertain_submission_stays_uncertain_until_explicit_original_receipt(self):
        self.update(state='SUBMISSION_UNKNOWN', task_id=None)
        before, _ = self.row()
        code, result = self.cli()
        self.assertEqual(1, code, result)
        self.assertEqual(before, self.row()[0])
        self.assertEqual(1, self.row()[1])
        code, result = self.cli('recover-unknown', task_id='original-paid-task')
        self.assertEqual(0, code, result)
        row, count = self.row()
        self.assertEqual(1, count)
        self.assertEqual('original-paid-task', row['task_id'])
        self.assertEqual('DOWNLOADED', row['state'])
        self.assertEqual(b'recovered-original-output', Path(row['output']).read_bytes())

    def test_reconcile_command_rejects_already_known_running_state(self):
        before, _ = self.row()
        code, result = self.cli('recover-unknown', task_id='original-paid-task')
        self.assertEqual(1, code, result)
        self.assertEqual(before, self.row()[0])
        self.assertEqual(1, self.row()[1])

    def test_reconcile_rejects_account_and_project_mismatch(self):
        for mismatch in ('account', 'project'):
            self.update(state='SUBMISSION_UNKNOWN', task_id=None, output=None, next_poll=0)
            before, _ = self.row()
            with self.subTest(mismatch=mismatch):
                code, result = self.cli('recover-unknown', task_id='original-paid-task',
                    account='different-account' if mismatch == 'account' else 'offline-account',
                    project=self.root / 'different-project' if mismatch == 'project' else self.project)
                self.assertEqual(1, code, result)
                self.assertIn(mismatch, result.get('reason', '').lower())
                self.assertEqual(before, self.row()[0])
                self.assertEqual(1, self.row()[1])

    def test_existing_poll_schedule_never_turns_recovery_into_refill(self):
        self.update(next_poll=10**12)
        before, _ = self.row()
        code, result = self.cli()
        self.assertEqual(0, code, result)
        self.assertEqual(before, self.row()[0])
        self.assertEqual(1, self.row()[1])
        self.assertFalse((self.project / 'candidates').exists())


if __name__ == '__main__': unittest.main()
