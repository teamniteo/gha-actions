"""Check model-family selection and the CLI discovery protocol."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import models


class ModelTests(unittest.TestCase):
    def test_latest_uses_numeric_versions_and_requested_family(self):
        catalogue = [{'model': name} for name in ['gpt-6.9-sol', 'gpt-7-astra', 'gpt-6.10-sol', 'gpt-6-sol']]
        self.assertEqual(models.newest(catalogue, 'sol'), 'gpt-6.10-sol')
        self.assertEqual(models.newest(catalogue, 'astra'), 'gpt-7-astra')

    def test_hidden_and_preview_models_are_not_selected(self):
        catalogue = [{'model':'gpt-7-sol', 'hidden':True}, {'model':'gpt-7-sol-preview'}, {'model':'gpt-6-sol'}]
        self.assertEqual(models.newest(catalogue, 'sol'), 'gpt-6-sol')
        with self.assertRaises(RuntimeError):
            models.newest(catalogue, 'astra')

    def test_explicit_model_bypasses_discovery(self):
        with patch.object(models.subprocess, 'Popen') as start:
            self.assertEqual(models.resolve('gpt-6-sol', {}), 'gpt-6-sol')
            start.assert_not_called()

    def test_discovery_handshake_and_pagination(self):
        with tempfile.TemporaryDirectory() as directory:
            executable=Path(directory)/'codex'
            executable.write_text(f'#!{sys.executable}\n'+'''import json, sys
assert sys.argv[1:] == ['app-server']
for line in sys.stdin:
    msg=json.loads(line)
    if msg['method']=='initialized': continue
    if msg['method']=='initialize': result={}
    elif msg['params']['cursor'] is None:
        result={'data':[{'model':'gpt-6-sol'}], 'nextCursor':'page2'}
    else:
        assert msg['params']['cursor']=='page2'
        result={'data':[{'model':'gpt-6.1-sol'}], 'nextCursor':None}
    print(json.dumps({'method':'notification'}),flush=True)
    print(json.dumps({'id':msg['id'],'result':result}),flush=True)
''')
            executable.chmod(0o755)
            self.assertEqual(models.resolve('latest-sol',dict(os.environ,PATH=directory+':'+os.environ['PATH'])), 'gpt-6.1-sol')


if __name__ == '__main__':
    unittest.main()
