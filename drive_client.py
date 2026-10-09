"""Private Google Drive storage using a one-time OAuth consent and encrypted refresh token."""
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from cryptography.fernet import Fernet
from sqlalchemy import update
from library_store import Integration, Job


class DriveUnavailable(RuntimeError):
    pass


def cipher():
    secret = os.environ.get('DRIVE_ENCRYPTION_SECRET')
    if not secret:
        raise DriveUnavailable('Configura DRIVE_ENCRYPTION_SECRET en Render.')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def oauth_config():
    names = ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI')
    values = [os.environ.get(name) for name in names]
    if not all(values):
        raise DriveUnavailable('Configura las credenciales OAuth de Google y GOOGLE_REDIRECT_URI en Render.')
    url = urlsplit(values[2])
    if url.scheme != 'https' and not (os.environ.get('WEB_LOCAL_HTTP') == '1' and url.hostname in ('localhost', '127.0.0.1')):
        raise DriveUnavailable('La URL de retorno de Google debe usar HTTPS.')
    return values


def token_request(payload):
    try:
        request = Request('https://oauth2.googleapis.com/token', data=urlencode(payload).encode(), method='POST')
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError):
        raise DriveUnavailable('Google rechazó o no confirmó la autorización. Vuelve a conectar Drive.') from None


def connect(store, code):
    client_id, client_secret, redirect_uri = oauth_config()
    token = token_request({'code': code, 'client_id': client_id, 'client_secret': client_secret,
                           'redirect_uri': redirect_uri, 'grant_type': 'authorization_code'})
    refresh_token = token.get('refresh_token')
    if not refresh_token:
        raise DriveUnavailable('Google no entregó autorización permanente. Vuelve a conectar y aceptar el acceso.')
    client = DriveClient(token['access_token'])
    folder = client.ensure_folder()
    encrypted = cipher().encrypt(refresh_token.encode()).decode()
    with store.session.begin() as db:
        row = db.get(Integration, 'google-drive')
        if not row:
            db.add(Integration(id='google-drive', encrypted_token=encrypted, folder_id=folder))
        else:
            row.encrypted_token, row.folder_id = encrypted, folder
        db.execute(update(Job).where(Job.kind.in_(['drive_video', 'drive_transcript']), Job.status.in_(['blocked', 'failed']))
                   .values(status='pending', error=None, available_at=0))


class DriveClient:
    def __init__(self, token, folder_id=None):
        self.token, self.folder_id = token, folder_id

    @classmethod
    def from_store(cls, store):
        with store.session() as db:
            row = db.get(Integration, 'google-drive')
            if not row:
                raise DriveUnavailable('Conecta Google Drive desde la biblioteca una vez.')
            encrypted, folder_id = row.encrypted_token, row.folder_id
        try:
            refresh_token = cipher().decrypt(encrypted.encode()).decode()
        except DriveUnavailable:
            raise
        except Exception:
            raise DriveUnavailable('No se pudo leer la autorización cifrada de Drive. Vuelve a conectar.') from None
        client_id, client_secret, _ = oauth_config()
        token = token_request({'refresh_token': refresh_token, 'client_id': client_id,
                               'client_secret': client_secret, 'grant_type': 'refresh_token'})
        return cls(token['access_token'], folder_id)

    def request(self, path, payload=None):
        try:
            request = Request('https://www.googleapis.com/drive/v3/' + path,
                              data=json.dumps(payload).encode() if payload is not None else None,
                              headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError):
            raise DriveUnavailable('No se pudo completar la operación en Google Drive. Revisa conexión, permisos y espacio.') from None

    def ensure_folder(self):
        query = "mimeType = 'application/vnd.google-apps.folder' and trashed = false and appProperties has { key='leadsicon' and value='ugc-library' }"
        found = self.request('files?' + urlencode({'q': query, 'fields': 'files(id)', 'pageSize': 10}))['files']
        if found:
            return found[0]['id']
        return self.request('files', {'name': 'Leadsicon UGC', 'mimeType': 'application/vnd.google-apps.folder',
                                     'appProperties': {'leadsicon': 'ugc-library'}})['id']

    def upload(self, path, name, mime, key):
        if not self.folder_id:
            raise DriveUnavailable('La carpeta de Drive no está configurada.')
        query = f"'{self.folder_id}' in parents and trashed = false and appProperties has {{ key='leadsicon_key' and value='{key}' }}"
        files = self.request('files?' + urlencode({'q': query, 'fields': 'files(id,webViewLink)', 'pageSize': 10}))['files']
        if files:
            return files[0]
        path = Path(path)
        size = path.stat().st_size
        metadata = {'name': name, 'parents': [self.folder_id], 'appProperties': {'leadsicon_key': key}}
        try:
            request = Request('https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,webViewLink',
                              data=json.dumps(metadata).encode(), method='POST', headers={
                                  'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json',
                                  'X-Upload-Content-Type': mime, 'X-Upload-Content-Length': str(size)})
            with urlopen(request, timeout=30) as response:
                location = response.headers['Location']
            url = urlsplit(location)
            if url.scheme != 'https' or url.hostname != 'www.googleapis.com' or url.username or url.password:
                raise DriveUnavailable('Google devolvió un destino de subida inesperado.')
            with path.open('rb') as handle:
                offset = 0
                while offset < size:
                    chunk = handle.read(8 * 1024 * 1024)
                    request = Request(location, data=chunk, method='PUT', headers={
                        'Authorization': 'Bearer ' + self.token, 'Content-Type': mime,
                        'Content-Range': f'bytes {offset}-{offset + len(chunk) - 1}/{size}'})
                    try:
                        with urlopen(request, timeout=60) as response:
                            result = json.load(response)
                    except HTTPError as error:
                        if error.code != 308 or offset + len(chunk) >= size:
                            raise
                    offset += len(chunk)
            return result
        except (HTTPError, URLError, TimeoutError, ValueError, OSError, KeyError):
            raise DriveUnavailable('No se pudo confirmar la subida a Drive. El reintento comprobará si el archivo ya existe.') from None
