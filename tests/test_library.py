import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from sqlalchemy import select
from werkzeug.security import generate_password_hash
from web import create_app
from library_store import LibraryStore, Job, Integration, Asset
from library_worker import run_once, valid_video_url, download_video, Blocked
from drive_client import connect, cipher, DriveClient


class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('test-password')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.url = 'sqlite:///' + self.directory.name + '/library.db'
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-secret', 'PASSWORD_HASH': self.password_hash,
                               'SESSION_COOKIE_SECURE': False, 'DATABASE_URL': self.url})
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session.update(authenticated=True, csrf='test-csrf')
        self.store = self.app.extensions['library_store']()
        self.addCleanup(self.store.engine.dispose)
        self.headers = {'X-CSRF-Token': 'test-csrf'}

    def post(self, path, body):
        return self.client.post(path, json=body, headers=self.headers)

    def save(self, raw=None):
        return self.post('/api/library/ads', {'platform': 'facebook', 'raw': raw or {'adArchiveId': '123', 'pageName': 'Test'}}).get_json()

    def test_persistence_idempotence_and_favorite_survives_import(self):
        first = self.save()
        duplicate = self.save()
        self.assertEqual(first['id'], duplicate['id'])
        self.store.save_ad('facebook', {'adArchiveId': '123', 'pageName': 'Updated'})
        fresh = LibraryStore(self.url)
        try:
            self.assertEqual(len(fresh.list_ads()), 1)
            self.assertTrue(fresh.get_ad(first['id'])['liked'])
            self.assertEqual(fresh.get_ad(first['id'])['raw']['pageName'], 'Updated')
        finally:
            fresh.engine.dispose()

    def test_api_login_and_csrf(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/api/library').status_code, 401)
        self.assertEqual(anonymous.get('/library').status_code, 302)
        self.assertEqual(self.client.post('/api/library/ads', json={}).status_code, 403)
        self.assertEqual(self.client.get('/library').status_code, 200)

    def test_missing_database_never_claims_saved(self):
        app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'PASSWORD_HASH': self.password_hash, 'SESSION_COOKIE_SECURE': False})
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(authenticated=True, csrf='test')
        with patch.dict(os.environ, {'DATABASE_URL': ''}):
            self.assertEqual(client.get('/api/library').status_code, 503)
            self.assertFalse(client.get('/api/library/config').get_json()['databaseConfigured'])

    def test_like_queues_assets_once(self):
        item = self.save({'adArchiveId': 'video', 'snapshot': {'videos': [{'video_hd_url': 'https://cdn.fbcdn.net/a.mp4'}]}})
        self.post('/api/library/ads/' + item['id'] + '/like', {'liked': True})
        stored = self.store.get_ad(item['id'])
        self.assertEqual(len(stored['assets']), 1)
        self.assertEqual(len(stored['jobs']), 1)
        self.post('/api/library/ads/' + item['id'] + '/like', {'liked': False})
        self.assertFalse(self.store.get_ad(item['id'])['liked'])
        self.assertEqual(len(self.client.get('/api/library?liked=1').get_json()['items']), 0)

    def test_versions_separate_voices_scenes_and_reviewed_knowledge(self):
        item = self.save()
        path = '/api/library/ads/' + item['id'] + '/transcript'
        body = {'speech': [{'start': 0, 'end': 3, 'speaker': 'Persona 1', 'role': 'on_camera', 'text': 'Hola'},
                           {'start': 3, 'end': 5, 'speaker': 'Narrador', 'role': 'voiceover', 'text': 'Ahorra'}],
                'scenes': [{'start': 0, 'end': 5, 'description': 'Una persona dentro del auto'}]}
        self.assertEqual(self.post(path, body).get_json()['transcript']['version'], 1)
        self.assertEqual(self.client.get('/api/library/knowledge').get_json()['items'], [])
        body['reviewed'] = True
        saved = self.post(path, body).get_json()
        self.assertEqual(saved['transcript']['version'], 2)
        knowledge = self.client.get('/api/library/knowledge').get_json()['items']
        self.assertEqual(knowledge[0]['transcript']['speech'][1]['role'], 'voiceover')
        self.assertEqual(len(knowledge[0]['transcript']['scenes']), 1)
        self.assertEqual(self.client.get('/api/library/ads/' + item['id'] + '/export').status_code, 200)

    def test_invalid_times_and_empty_review_rejected(self):
        item = self.save(); path = '/api/library/ads/' + item['id'] + '/transcript'
        for start, end in [(2, 1), (-1, 3), (float('nan'), 3), (True, 3)]:
            self.assertEqual(self.post(path, {'scenes': [{'start': start, 'end': end, 'description': 'Test'}]}).status_code, 400)
        self.assertEqual(self.post(path, {'reviewed': True}).status_code, 400)
        self.assertIsNone(self.store.get_ad(item['id'])['transcript'])

    def test_organic_link_validation_and_persistence(self):
        for url in ['http://facebook.com/a', 'https://facebook.com.evil.test/a', 'https://user@facebook.com/a', 'https://facebook.com:8080/a']:
            self.assertEqual(self.post('/api/library/references', {'url': url}).status_code, 400)
        response = self.post('/api/library/references', {'url': 'https://www.facebook.com/reel/123', 'title': 'Reference'})
        self.assertEqual(response.status_code, 201)
        item = response.get_json()
        self.assertEqual(item['kind'], 'organic')
        self.assertEqual(item['assets'], [])
        self.assertTrue(item['liked'])

    def test_import_all_pages_without_duplicate_runs_or_ads(self):
        self.store.import_run('run-test', 'facebook', 'actor', {})
        self.store.import_run('run-test', 'facebook', 'actor', {})
        with patch.dict(os.environ, {'APIFY_TOKEN': 'test-token'}), patch('library_worker.ApifyClient') as client:
            client.return_value.request.side_effect = [
                {'data': {'status': 'SUCCEEDED', 'defaultDatasetId': 'dataset'}},
                [{'adArchiveId': str(i)} for i in range(1001)], [{'adArchiveId': '1001'}], []]
            self.assertTrue(run_once(self.store))
            self.assertEqual(client.return_value.request.call_args_list[2].args[0], 'datasets/dataset/items?format=json&offset=1001&limit=1000')
        self.assertEqual(len(self.store.list_ads(limit=2000)), 1002)
        with self.store.session() as db:
            self.assertEqual(len(db.scalars(select(Job)).all()), 1)
            self.assertEqual(db.scalar(select(Job)).status, 'done')

    def test_worker_download_upload_and_transcription_blocked(self):
        item = self.save({'adArchiveId': 'video', 'videoUrl': 'https://cdn.fbcdn.net/a.mp4'})
        file = Path(self.directory.name) / 'file.mp4'; file.write_bytes(b'media')
        with patch('library_worker.download_video', return_value=(str(file), 'sha', 5)):
            self.assertTrue(run_once(self.store))
        with patch('library_worker.DriveClient.from_store') as drive:
            drive.return_value.upload.return_value = {'id': 'drive-id', 'webViewLink': 'https://drive.google.com/file/d/drive-id/view'}
            self.assertTrue(run_once(self.store))
        self.assertFalse(file.exists())
        self.assertTrue(run_once(self.store))
        updated = self.store.get_ad(item['id'])
        self.assertIsNotNone(updated['assets'][0]['driveUrl'])
        self.assertEqual([j['status'] for j in updated['jobs']], ['done', 'done', 'blocked'])
        self.assertIsNone(updated['transcript'])
        self.post('/api/library/ads/' + item['id'] + '/retry', {})
        self.assertEqual(self.store.get_ad(item['id'])['jobs'][-1]['status'], 'pending')

    def test_expired_lease_recovered_and_job_not_claimed_twice(self):
        self.store.enqueue('test', 'one', {})
        claimed = self.store.claim_job()
        self.assertIsNotNone(claimed)
        self.assertIsNone(self.store.claim_job())
        with self.store.session.begin() as db:
            db.get(Job, claimed['id']).lease_until = 0
        self.assertEqual(self.store.claim_job()['id'], claimed['id'])

    def test_oauth_state_and_encrypted_authorization(self):
        environment = {'GOOGLE_CLIENT_ID': 'test-id', 'GOOGLE_CLIENT_SECRET': 'test-secret',
                       'GOOGLE_REDIRECT_URI': 'https://example.test/integrations/google/callback', 'DRIVE_ENCRYPTION_SECRET': 'test-encryption-secret'}
        self.store.enqueue('drive_video', 'pending-drive', {})
        job = self.store.claim_job(); self.store.finish_job(job['id'], 'blocked')
        with patch.dict(os.environ, environment), patch('drive_client.token_request', return_value={'refresh_token': 'private-refresh', 'access_token': 'private-access'}), patch.object(DriveClient, 'ensure_folder', return_value='folder'):
            connect(self.store, 'test-code')
            with self.store.session() as db:
                row = db.get(Integration, 'google-drive')
                self.assertNotIn('private-refresh', row.encrypted_token)
                self.assertEqual(cipher().decrypt(row.encrypted_token.encode()), b'private-refresh')
                self.assertEqual(db.get(Job, job['id']).status, 'pending')
            response = self.post('/api/drive/connect', {})
            self.assertEqual(response.status_code, 200)
            self.assertIn('drive.file', response.get_json()['url'])
            self.assertNotIn('test-secret', response.get_json()['url'])
            self.assertEqual(self.client.get('/integrations/google/callback?state=wrong&code=x').status_code, 403)
        self.assertEqual(self.client.get('/api/library/config').get_json()['driveConnected'], True)

    def test_start_registers_durable_import_without_restarting_paid_run(self):
        with patch.dict(os.environ, {'APIFY_TOKEN': 'test'}), patch('web.ApifyClient') as apify:
            apify.return_value.request.return_value = {'data': {'id': 'new-run', 'status': 'RUNNING'}}
            response = self.post('/api/runs', {'platform': 'facebook', 'input': {}})
        self.assertEqual(response.status_code, 201)
        with self.store.session() as db:
            self.assertEqual(db.scalar(select(Job)).payload['run_id'], 'new-run')

    def test_retry_import_does_not_start_another_paid_run(self):
        self.store.import_run('retry-run', 'facebook', 'actor', {})
        job = self.store.claim_job(); self.store.finish_job(job['id'], 'failed')
        self.assertEqual(self.client.get('/api/library/runs').get_json()['items'][0]['status'], 'failed')
        with patch('web.ApifyClient') as apify:
            self.assertEqual(self.post('/api/library/runs/retry-run/retry', {}).status_code, 200)
            apify.assert_not_called()
        self.assertEqual(self.client.get('/api/library/runs').get_json()['items'][0]['status'], 'pending')

    def test_cdn_validation_and_html_rejection(self):
        self.assertTrue(valid_video_url('https://video.xx.fbcdn.net/a.mp4'))
        for url in ['http://cdn.fbcdn.net/a', 'https://fbcdn.net.evil.test/a', 'https://127.0.0.1/a', 'https://user@fbcdn.net/a']:
            self.assertFalse(valid_video_url(url))
        fake = MagicMock(); fake.headers = {}; fake.read.side_effect = [b'<html>not mp4</html>', b'']
        fake.__enter__.return_value = fake
        with patch.dict(os.environ, {'MEDIA_DIR': self.directory.name}), patch('library_worker.build_opener') as opener:
            opener.return_value.open.return_value = fake
            with self.assertRaises(Blocked):
                download_video('https://cdn.fbcdn.net/a', 'asset')
        self.assertFalse((Path(self.directory.name) / 'asset.part').exists())
        self.assertFalse((Path(self.directory.name) / 'asset.mp4').exists())
