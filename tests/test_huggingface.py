import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from sqlalchemy import select
from hf_transcription import transcribe_video, endpoint_url, configured
from transcription import TranscriptionUnavailable, analysis_origin, transcribe_video as dispatch
from library_store import LibraryStore, Transcript
from library_worker import run_once
from integrations.huggingface.alignment import align_words, scene_windows
from integrations.huggingface.handler import EndpointHandler

HF_ENV = {'TRANSCRIPTION_PROVIDER': 'huggingface', 'HF_TOKEN': 'test-hf-private-token',
          'HF_TRANSCRIPTION_ENDPOINT': 'https://test.us-east-1.aws.endpoints.huggingface.cloud', 'HF_TRANSCRIPTION_ENABLED': '1'}
SPEECH = [{'start': 0, 'end': 2, 'speaker': 'Persona 1', 'role': 'unknown', 'text': 'Hello.'}]
SCENES = [{'start': 0, 'end': 3, 'description': 'Una persona está dentro de un vehículo.'}]
VIDEO = b'\x00\x00\x00\x18ftypmp42test-mp4-fixture'


class HuggingFaceTests(unittest.TestCase):
    def test_endpoint_safety_and_configuration(self):
        for value in ['http://test.endpoints.huggingface.cloud', 'https://evil.test',
                      'https://test.endpoints.huggingface.cloud.evil.test',
                      'https://user@test.endpoints.huggingface.cloud', 'https://test.endpoints.huggingface.cloud?secret=x',
                      'https://test.endpoints.huggingface.cloud:444', 'https://test.endpoints.huggingface.cloud/path']:
            with patch.dict(os.environ, {**HF_ENV, 'HF_TRANSCRIPTION_ENDPOINT': value}):
                self.assertFalse(configured())
                with self.assertRaises(TranscriptionUnavailable): endpoint_url()
        with patch.dict(os.environ, HF_ENV):
            self.assertTrue(configured())
            self.assertTrue(analysis_origin('asset').startswith('hf:'))
        with patch.dict(os.environ, {**HF_ENV, 'HF_TOKEN': ''}): self.assertFalse(configured())

    def mock_response(self, result):
        response = MagicMock(); response.read.return_value = json.dumps(result).encode()
        response.__enter__.return_value = response
        return response

    def test_private_request_and_validated_response(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.mp4'; path.write_bytes(VIDEO)
            with patch.dict(os.environ, HF_ENV), patch('hf_transcription.build_opener') as opener:
                opener.return_value.open.return_value = self.mock_response({'schemaVersion': 1, 'duration': 3, 'speech': SPEECH, 'scenes': SCENES})
                speech, scenes = transcribe_video(path)
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.get_header('Authorization'), 'Bearer test-hf-private-token')
                body = json.loads(request.data)
                self.assertEqual(base64.b64decode(body['inputs']['video_base64']), VIDEO)
                self.assertNotIn('test-hf-private-token', request.data.decode())
                self.assertEqual(speech, SPEECH); self.assertEqual(scenes, SCENES)

    def test_invalid_durations_errors_and_incomplete_whisper_only_response(self):
        invalid = [{'text': 'Whisper alone is not enough'},
                   {'schemaVersion': 1, 'duration': 3, 'speech': SPEECH, 'scenes': []},
                   {'schemaVersion': 1, 'duration': 1, 'speech': SPEECH, 'scenes': SCENES},
                   {'schemaVersion': 1, 'duration': float('nan'), 'speech': SPEECH, 'scenes': SCENES},
                   {'error': 'private-token-and-details'}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.mp4'; path.write_bytes(VIDEO)
            for result in invalid:
                with patch.dict(os.environ, HF_ENV), patch('hf_transcription.build_opener') as opener:
                    opener.return_value.open.return_value = self.mock_response(result)
                    with self.assertRaises(TranscriptionUnavailable) as error: transcribe_video(path)
                    self.assertNotIn('private-token-and-details', str(error.exception))

    def test_disabled_or_oversized_never_sends_video(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.mp4'; path.write_bytes(VIDEO)
            for env in [{'HF_MAX_VIDEO_BYTES': '5'}, {'HF_TRANSCRIPTION_ENABLED': '0'}]:
                with patch.dict(os.environ, {**HF_ENV, **env}), patch('hf_transcription.build_opener') as opener:
                    with self.assertRaises(TranscriptionUnavailable): transcribe_video(path)
                    opener.assert_not_called()

    def test_http_error_is_safe_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'video.mp4'; path.write_bytes(VIDEO)
            with patch.dict(os.environ, HF_ENV), patch('hf_transcription.build_opener') as opener:
                opener.return_value.open.side_effect = HTTPError(HF_ENV['HF_TRANSCRIPTION_ENDPOINT'], 401, 'private-detail', {}, None)
                with self.assertRaises(TranscriptionUnavailable) as error: transcribe_video(path)
                self.assertIn('rechazó', str(error.exception)); self.assertNotIn('private-detail', str(error.exception))
                self.assertEqual(opener.return_value.open.call_count, 1)

    def test_dispatch_huggingface_never_calls_kie(self):
        with patch.dict(os.environ, HF_ENV), patch('hf_transcription.transcribe_video', return_value=(SPEECH, SCENES)) as hf, patch('transcription.transcribe_kie_video') as kie:
            self.assertEqual(dispatch('video.mp4'), (SPEECH, SCENES))
            hf.assert_called_once(); kie.assert_not_called()

    def test_words_aligned_to_real_speaker_turns(self):
        words = [{'timestamp': (0., 1.), 'text': 'Hello'}, {'timestamp': (1., 2.), 'text': 'there.'},
                 {'timestamp': (2., 3.), 'text': 'My turn.'}]
        turns = [{'start': 0, 'end': 2, 'speaker': 'SPEAKER_04'}, {'start': 2, 'end': 3, 'speaker': 'SPEAKER_01'}]
        speech = align_words(words, turns, 3)
        self.assertEqual([item['speaker'] for item in speech], ['Persona 1', 'Persona 2'])
        self.assertEqual(speech[0]['text'], 'Hello there.')
        self.assertEqual(speech[1]['start'], 2)
        self.assertTrue(all(item['role'] == 'unknown' for item in speech))
        overlap = align_words(words[:1], [{'start': 0, 'end': 1, 'speaker': 'a'}, {'start': 0, 'end': 1, 'speaker': 'b'}], 3)
        self.assertEqual(overlap[0]['speaker'], 'Voces superpuestas')
        self.assertEqual(align_words(words[:1], [], 3)[0]['speaker'], 'Sin identificar')
        for timestamp in [(None, 1), (1, 0), (float('nan'), 1), (3, 4)]:
            with self.assertRaises(ValueError): align_words([{'timestamp': timestamp, 'text': 'Bad'}], turns, 3)

    def test_scene_windows_cover_video_and_limit_descriptions(self):
        windows = scene_windows([3, 5, -1, float('nan')], 20)
        self.assertEqual(windows[0]['start'], 0)
        self.assertEqual(windows[-1]['end'], 20)
        self.assertIn(3, [item['end'] for item in windows])
        for previous, current in zip(windows, windows[1:]): self.assertEqual(previous['end'], current['start'])
        self.assertLessEqual(len(scene_windows(list(range(1, 150)), 150)), 24)

    def test_handler_rejects_bad_inputs_without_loading_models(self):
        handler = EndpointHandler.__new__(EndpointHandler)
        for body in [{}, {'inputs': {'schema_version': 1, 'video_base64': 'not base64'}},
                     {'inputs': {'schema_version': 1, 'video_base64': base64.b64encode(b'html').decode()}}]:
            self.assertIn('error', handler(body))

    def test_hf_worker_stores_source_and_skips_duplicate_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LibraryStore('sqlite:///' + directory + '/test.db'); self.addCleanup(store.engine.dispose)
            path = Path(directory) / 'video.mp4'; path.write_bytes(VIDEO)
            ad_id = store.save_ad('facebook', {'adArchiveId': 'hf-test', 'videoUrl': 'https://cdn.fbcdn.net/video.mp4'}, liked=True)
            with patch('library_worker.download_video', return_value=(str(path), 'sha', len(VIDEO))): run_once(store)
            with patch.dict(os.environ, HF_ENV), patch('hf_transcription.transcribe_video', return_value=(SPEECH, SCENES)) as hf:
                run_once(store)
                ad = store.get_ad(ad_id)
                self.assertTrue(ad['transcript']['origin'].startswith('hf:whisper-pyannote-vlm:'))
                self.assertEqual(ad['transcript']['sourceAssetId'], ad['assets'][0]['id'])
                self.assertFalse(ad['transcript']['reviewed'])
                store.enqueue('transcribe', 'recovered-copy', {'asset_id': ad['assets'][0]['id'], 'ad_id': ad_id})
                # Hold Drive until the recovered transcript job has been checked.
                with patch('library_worker.DriveClient.from_store') as drive:
                    drive.return_value.upload.return_value = {'id': 'drive-test'}
                    run_once(store); run_once(store); run_once(store)
                hf.assert_called_once()
            with store.session() as db: self.assertEqual(len(db.scalars(select(Transcript)).all()), 1)
