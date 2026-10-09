import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
from werkzeug.security import generate_password_hash
from hf_transcription import notify_remote
from library_store import LibraryStore, Job
from integrations.huggingface.remote_processor import RemoteProcessor
from integrations.huggingface.handler import EndpointHandler
from integrations.huggingface.build_bundle import build, ENDPOINT_FILES, BACKEND_FILES
from web import create_app

HF_ENV = {'TRANSCRIPTION_PROVIDER': 'huggingface', 'HF_PROCESSING_MODE': 'remote', 'HF_TOKEN': 'test-token',
          'HF_TRANSCRIPTION_ENDPOINT': 'https://test.us-east-1.aws.endpoints.huggingface.cloud', 'HF_TRANSCRIPTION_ENABLED': '1'}
VIDEO = b'\x00\x00\x00\x18ftypmp42-test-video'
RESULT = {'schemaVersion': 1, 'duration': 5, 'speech': [{'start': 0, 'end': 2, 'speaker': 'Persona 1', 'role': 'unknown', 'text': 'Hola'}],
          'scenes': [{'start': 0, 'end': 5, 'description': 'Persona dentro de un auto.'}]}


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.database_url = 'sqlite:///' + self.directory.name + '/db.sqlite'

    def test_endpoint_control_accepts_without_blocking_on_inference(self):
        handler = EndpointHandler.__new__(EndpointHandler); handler.remote_processor = MagicMock()
        with patch.object(handler, 'analyze_path') as analyze:
            result = handler({'inputs': {'action': 'process_pending', 'schema_version': 1}})
        self.assertEqual(result, {'schemaVersion': 1, 'accepted': True, 'storage': 'supabase'})
        handler.remote_processor.notify.assert_called_once(); analyze.assert_not_called()
        handler.remote_processor = None
        self.assertIn('error', handler({'inputs': {'action': 'process_pending', 'schema_version': 1}}))

    def test_wakeup_sends_no_database_or_drive_secrets(self):
        response = MagicMock(); response.__enter__.return_value = response
        response.read.return_value = b'{"accepted":true,"storage":"supabase"}'
        with patch.dict(os.environ, {**HF_ENV, 'DATABASE_URL': 'private-db', 'DRIVE_ENCRYPTION_SECRET': 'private-drive'}), patch('hf_transcription.build_opener') as opener:
            opener.return_value.open.return_value = response
            result = notify_remote(); request = opener.return_value.open.call_args.args[0]
            self.assertEqual(result['status'], 'accepted')
            self.assertEqual(json.loads(request.data), {'inputs': {'action': 'process_pending', 'schema_version': 1}})
            self.assertNotIn('private-db', request.data.decode()); self.assertNotIn('private-drive', request.data.decode())

    def test_unconfirmed_wakeup_is_not_retried_or_reported_as_lost_save(self):
        with patch.dict(os.environ, HF_ENV), patch('hf_transcription.build_opener') as opener:
            opener.return_value.open.side_effect = TimeoutError('private-secret')
            result = notify_remote()
            self.assertEqual(result['status'], 'unconfirmed')
            self.assertNotIn('private-secret', result['message'])
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_like_is_saved_then_endpoint_persists_without_render_worker(self):
        app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'PASSWORD_HASH': generate_password_hash('test'),
                          'SESSION_COOKIE_SECURE': False, 'DATABASE_URL': self.database_url})
        store = app.extensions['library_store'](); self.addCleanup(store.engine.dispose)
        client = app.test_client()
        with client.session_transaction() as session: session.update(authenticated=True, csrf='test')
        with patch.dict(os.environ, HF_ENV), patch('hf_transcription.notify_remote', return_value={'status': 'accepted', 'message': 'Saved'}) as notify:
            response = client.post('/api/library/ads', json={'platform': 'facebook', 'raw': {'adArchiveId': 'remote', 'videoUrl': 'https://cdn.fbcdn.net/v.mp4'}, 'liked': True}, headers={'X-CSRF-Token': 'test'})
            self.assertEqual(response.status_code, 201); self.assertEqual(response.get_json()['processing']['status'], 'accepted')
            notify.assert_called_once()
        ad_id = response.get_json()['id']
        # A separate endpoint process connects to the same durable Supabase schema.
        handler = MagicMock(); handler.analyze_path.return_value = RESULT
        processor = RemoteProcessor(handler, self.database_url); self.addCleanup(processor.store.engine.dispose)
        video = Path(self.directory.name) / 'v.mp4'; video.write_bytes(VIDEO)
        with patch('library_worker.download_video', return_value=(str(video), 'sha', len(VIDEO))), patch('hf_transcription.transcribe_video') as remote_inference:
            self.assertTrue(processor.process_one()); self.assertTrue(processor.process_one())
            remote_inference.assert_not_called()  # Local models in HF, no recursive HTTP call.
        item = client.get('/api/library/ads/' + ad_id).get_json()
        self.assertEqual(item['transcript']['speech'][0]['text'], 'Hola')
        self.assertEqual(item['transcript']['scenes'][0]['description'], 'Persona dentro de un auto.')
        self.assertTrue(item['transcript']['origin'].startswith('hf:'))
        self.assertEqual(item['transcript']['sourceAssetId'], item['assets'][0]['id'])

    def test_endpoint_loop_survives_transient_database_outage(self):
        processor = RemoteProcessor(MagicMock(), self.database_url)
        self.addCleanup(processor.store.engine.dispose); self.addCleanup(processor.stop)
        progressed = threading.Event(); count = [0]
        def process():
            count[0] += 1
            if count[0] == 1:
                processor.wakeup.set(); raise RuntimeError('Database temporarily unavailable')
            progressed.set(); return False
        with patch.object(processor, 'process_one', side_effect=process):
            processor.start(); self.assertTrue(progressed.wait(2)); processor.stop()
        self.assertGreaterEqual(count[0], 2)

    def test_disabled_remote_inference_never_calls_models(self):
        handler = MagicMock()
        processor = RemoteProcessor(handler, self.database_url); self.addCleanup(processor.store.engine.dispose)
        with patch.dict(os.environ, {'HF_TRANSCRIPTION_ENABLED': '0'}):
            with self.assertRaises(RuntimeError): processor.analyze('/fake')
        handler.analyze_path.assert_not_called()

    def test_bad_model_result_not_saved(self):
        handler = MagicMock(); handler.analyze_path.return_value = {**RESULT, 'duration': float('nan')}
        processor = RemoteProcessor(handler, self.database_url); self.addCleanup(processor.store.engine.dispose)
        with self.assertRaises(RuntimeError): processor.analyze('/fake')

    def test_bundle_is_complete_and_never_overwrites_existing_files(self):
        path = Path(self.directory.name) / 'bundle'
        self.assertEqual(build(path), len(ENDPOINT_FILES) + len(BACKEND_FILES))
        self.assertTrue((path / 'transcript_validation.py').is_file())
        self.assertTrue((path / 'remote_processor.py').is_file())
        subprocess.run([sys.executable, '-c', "import remote_processor, handler, library_worker, sys; assert 'flask' not in sys.modules"], cwd=path, check=True, capture_output=True)
        with self.assertRaises(ValueError): build(path)
