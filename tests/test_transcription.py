import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from sqlalchemy import select
from library_store import LibraryStore, Transcript, Job
from library_worker import run_once, resume_configured_transcriptions
from transcription import transcribe_video, upload_video, provider_json, TranscriptionUnavailable, ENDPOINT, UPLOAD_ENDPOINT
from urllib.request import Request

SPEECH = [{'start': 0, 'end': 2, 'speaker': 'Persona 1', 'role': 'on_camera', 'text': 'Hello there.'},
          {'start': 2, 'end': 4, 'speaker': 'Narrador', 'role': 'voiceover', 'text': 'Save today.'}]
SCENES = [{'start': 0, 'end': 4, 'description': 'Persona en cámara dentro de un vehículo.'}]


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        provider_env = patch.dict(os.environ, {'TRANSCRIPTION_PROVIDER': 'kie', 'HF_TRANSCRIPTION_ENDPOINT': '', 'HF_TOKEN': ''})
        provider_env.start(); self.addCleanup(provider_env.stop)

    def test_kie_contract_video_input_and_structured_response(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'speech': SPEECH, 'scenes': SCENES})}}]}
        with patch.dict(os.environ, {'KIE_API_KEY': 'test-secret', 'KIE_TRANSCRIPTION_ENABLED': '1'}), patch('transcription.upload_video', return_value='https://tempfile.redpandaai.co/video.mp4'), patch('transcription.provider_json', return_value=response) as provider:
            speech, scenes = transcribe_video('/fake/video.mp4')
            request = provider.call_args.args[0]
            self.assertEqual(request.full_url, ENDPOINT)
            body = json.loads(request.data)
            self.assertFalse(body['stream'])
            self.assertEqual(body['messages'][1]['content'][1]['type'], 'image_url')
            self.assertEqual(body['response_format']['json_schema']['schema']['required'], ['speech', 'scenes'])
            self.assertEqual(speech, SPEECH)
            self.assertEqual(scenes, SCENES)

    def test_disabled_never_uploads_or_calls_paid_model(self):
        with patch.dict(os.environ, {'KIE_API_KEY': '', 'KIE_TRANSCRIPTION_ENABLED': '1'}), patch('transcription.upload_video') as upload:
            with self.assertRaises(TranscriptionUnavailable): transcribe_video('/fake/video.mp4')
            upload.assert_not_called()

    def test_stream_upload_content_length_and_documented_response(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private-name.mp4'; path.write_bytes(b'mp4-test-bytes')
            with patch('transcription.provider_json', return_value={'success': True, 'code': 200, 'data': {'downloadUrl': 'https://tempfile.redpandaai.co/temp/file.mp4'}}) as provider:
                url = upload_video(path, 'test-key')
                request = provider.call_args.args[0]
                self.assertEqual(request.full_url, UPLOAD_ENDPOINT)
                payload = b''.join(request.data)
                self.assertEqual(len(payload), int(request.get_header('Content-length')))
                self.assertIn(b'name="file"', payload)
                self.assertIn(b'mp4-test-bytes', payload)
                self.assertNotIn(b'private-name', payload)
                self.assertEqual(url, 'https://tempfile.redpandaai.co/temp/file.mp4')
            with patch('transcription.provider_json', return_value={'success': True, 'data': {'downloadUrl': 'https://evil.test/a'}}):
                with self.assertRaises(TranscriptionUnavailable): upload_video(path, 'test-key')

    def test_invalid_or_truncated_analysis_not_saved(self):
        for content, finish in [({'speech': [{'start': 4, 'end': 1, 'text': 'Bad'}], 'scenes': SCENES}, 'stop'),
                                ({'speech': SPEECH, 'scenes': []}, 'stop'),
                                ({'speech': SPEECH, 'scenes': SCENES}, 'length')]:
            response = {'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(content)}}]}
            with patch.dict(os.environ, {'KIE_API_KEY': 'test', 'KIE_TRANSCRIPTION_ENABLED': '1'}), patch('transcription.upload_video', return_value='https://tempfile.redpandaai.co/file.mp4'), patch('transcription.provider_json', return_value=response):
                with self.assertRaises(TranscriptionUnavailable): transcribe_video('/fake/video.mp4')

    def test_provider_http200_error_never_exposes_error_body(self):
        fake = MagicMock(); fake.headers = {}; fake.read.return_value = b'{"code":401,"msg":"private-secret"}'; fake.__enter__.return_value = fake
        with patch('transcription.build_opener') as opener:
            opener.return_value.open.return_value = fake
            with self.assertRaises(TranscriptionUnavailable) as error: provider_json(Request(ENDPOINT), 1)
        self.assertNotIn('private-secret', str(error.exception))

    def test_worker_like_download_transcription_drive_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LibraryStore('sqlite:///' + directory + '/library.db')
            self.addCleanup(store.engine.dispose)
            file = Path(directory) / 'video.mp4'; file.write_bytes(b'mp4')
            ad_id = store.save_ad('facebook', {'adArchiveId': 'auto', 'videoUrl': 'https://cdn.fbcdn.net/v.mp4'}, liked=True)
            with patch('library_worker.download_video', return_value=(str(file), 'sha', 3)):
                run_once(store)
            with patch.dict(os.environ, {'KIE_API_KEY': 'test', 'KIE_TRANSCRIPTION_ENABLED': '1'}), patch('library_worker.transcribe_video', return_value=(SPEECH, SCENES)) as transcribe:
                run_once(store)
                result = store.get_ad(ad_id)
                self.assertEqual(result['transcript']['speech'], SPEECH)
                self.assertTrue(result['transcript']['origin'].startswith('kie:gemini-2.5-pro:'))
                self.assertFalse(result['transcript']['reviewed'])
                self.assertEqual(result['transcript']['sourceAssetId'], result['assets'][0]['id'])
                with store.session.begin() as db:
                    job = db.scalar(select(Job).where(Job.kind == 'transcribe')); job.status = 'pending'; job.available_at = 0
                run_once(store)
                transcribe.assert_called_once()
            with store.session.begin() as db:
                for job in db.scalars(select(Job).where(Job.kind == 'drive_video')): job.available_at = 0
            with patch('library_worker.DriveClient.from_store') as drive:
                drive.return_value.upload.return_value = {'id': 'drive-file', 'webViewLink': 'https://drive.google.com/file/d/drive-file/view'}
                run_once(store); run_once(store)
            result = store.get_ad(ad_id)
            self.assertIsNotNone(result['assets'][0]['driveUrl'])
            self.assertIsNotNone(result['transcript']['driveUrl'])
            self.assertFalse(file.exists())
            with store.session() as db: self.assertEqual(len(db.scalars(select(Transcript)).all()), 1)

    def test_resume_only_missing_configuration_not_paid_provider_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LibraryStore('sqlite:///' + directory + '/library.db'); self.addCleanup(store.engine.dispose)
            for key, error in [('missing', 'Configura KIE_API_KEY en el worker.'), ('failed', 'Kie no confirmó el análisis.')]:
                store.enqueue('transcribe', key, {}); job = store.claim_job(); store.finish_job(job['id'], 'blocked', error)
            with patch.dict(os.environ, {'KIE_API_KEY': 'test', 'KIE_TRANSCRIPTION_ENABLED': '1'}): resume_configured_transcriptions(store)
            with store.session() as db:
                jobs = {job.key: job.status for job in db.scalars(select(Job))}
                self.assertEqual(jobs, {'missing': 'pending', 'failed': 'blocked'})
