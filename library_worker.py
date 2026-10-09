"""Run durable library jobs: python library_worker.py [--once]."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from sqlalchemy import select
from library_store import Asset, LibraryStore, Transcript, Job
from drive_client import DriveClient, DriveUnavailable
from scraper import ApifyClient
from transcription import transcribe_video, TranscriptionUnavailable, MODEL


class Blocked(RuntimeError):
    pass


def valid_video_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and parsed.port in (None, 443)
            and any(host == suffix or host.endswith('.' + suffix)
                    for suffix in ('fbcdn.net', 'googlevideo.com', 'googleusercontent.com')))


class TrustedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not valid_video_url(newurl):
            raise Blocked('El video redirige fuera de las CDN admitidas.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def media_dir():
    directory = Path(os.environ.get('MEDIA_DIR', '/tmp/leadsicon-media'))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def download_video(url, asset_id):
    if not valid_video_url(url):
        raise Blocked('No hay una URL directa de video admitida. Los previews externos de Google no son archivos descargables.')
    maximum = int(os.environ.get('MAX_MEDIA_BYTES', str(200 * 1024 * 1024)))
    directory = media_dir()
    maximum_cache = int(os.environ.get('MAX_MEDIA_CACHE_BYTES', str(1024 * 1024 * 1024)))
    remaining = maximum_cache - sum(path.stat().st_size for path in directory.glob('*.mp4'))
    maximum = min(maximum, remaining)
    if maximum <= 0:
        raise Blocked('La caché local está llena. Conecta Drive y reintenta después de las subidas.')
    destination = directory / (asset_id + '.mp4')
    temporary = destination.with_suffix('.part')
    digest, size = hashlib.sha256(), 0
    try:
        with build_opener(TrustedRedirect()).open(Request(url, headers={'User-Agent': 'LeadsiconLibrary/1.0'}), timeout=30) as response:
            if int(response.headers.get('Content-Length', '0')) > maximum:
                raise Blocked('El video supera el límite de tamaño configurado.')
            with temporary.open('wb') as handle:
                first = True
                while chunk := response.read(1024 * 1024):
                    if first:
                        # Refuse HTML/JS even if the URL ends in .mp4.
                        if len(chunk) < 12 or chunk[4:8] != b'ftyp':
                            raise Blocked('El recurso no es un archivo MP4 reconocido.')
                        first = False
                    size += len(chunk)
                    if size > maximum:
                        raise Blocked('El video supera el límite de tamaño configurado.')
                    digest.update(chunk)
                    handle.write(chunk)
        if not size:
            raise Blocked('El archivo de video está vacío.')
        temporary.replace(destination)
        return str(destination), digest.hexdigest(), size
    except (HTTPError, URLError, TimeoutError):
        raise Blocked('No se pudo descargar el video. Su enlace puede haber expirado; vuelve a obtener el anuncio.') from None
    finally:
        temporary.unlink(missing_ok=True)


def process_job(store, job):
    payload = job['payload']
    if job['kind'] == 'import_run':
        token = os.environ.get('APIFY_TOKEN')
        if not token:
            raise Blocked('Configura APIFY_TOKEN en el worker.')
        client = ApifyClient(token)
        run = client.request('actor-runs/' + payload['run_id'])['data']
        if run['status'] in {'READY', 'RUNNING', 'TIMING-OUT', 'ABORTING'}:
            return False
        if run['status'] != 'SUCCEEDED':
            raise Blocked('El run de Apify terminó con estado ' + run['status'] + '.')
        offset = 0
        while True:
            page = client.request(f"datasets/{run['defaultDatasetId']}/items?format=json&offset={offset}&limit=1000")
            if not page:
                break
            for raw in page:
                store.save_ad(payload['platform'], raw)
            offset += len(page)
    elif job['kind'] == 'download':
        with store.session() as db:
            asset = db.get(Asset, payload['asset_id'])
            if not asset:
                raise Blocked('No se encontró el archivo solicitado.')
            source_url, asset_id = asset.source_url, asset.id
            previous = asset.local_path
        if not previous or not Path(previous).is_file():
            path, sha, size = download_video(source_url, asset_id)
            with store.session.begin() as db:
                asset = db.get(Asset, asset_id)
                asset.local_path, asset.sha256, asset.size = path, sha, size
        store.enqueue('transcribe', 'transcribe:' + asset_id, {'asset_id': asset_id, 'ad_id': payload['ad_id']})
        store.enqueue('drive_video', 'drive:' + asset_id, {'asset_id': asset_id, 'ad_id': payload['ad_id']})
    elif job['kind'] == 'drive_video':
        with store.session() as db:
            transcription = db.scalar(select(Job).where(Job.key == 'transcribe:' + payload['asset_id']))
            if transcription and transcription.status in ('pending', 'running'):
                return False
            asset = db.get(Asset, payload['asset_id'])
            path, asset_id, source_url = asset.local_path, asset.id, asset.source_url
        if not path or not Path(path).is_file():
            path, sha, size = download_video(source_url, asset_id)
            with store.session.begin() as db:
                asset = db.get(Asset, asset_id)
                asset.local_path, asset.sha256, asset.size = path, sha, size
        result = DriveClient.from_store(store).upload(path, payload['ad_id'] + '-' + asset_id + '.mp4',
                                                     'video/mp4', 'video-' + asset_id)
        with store.session.begin() as db:
            asset = db.get(Asset, asset_id)
            asset.drive_file_id, asset.drive_url = result['id'], result.get('webViewLink') or 'https://drive.google.com/file/d/' + result['id'] + '/view'
            asset.local_path = None
        Path(path).unlink(missing_ok=True)
    elif job['kind'] == 'drive_transcript':
        with store.session() as db:
            transcript = db.get(Transcript, payload['transcript_id'])
            document = store.transcript_json(transcript)
        client = DriveClient.from_store(store)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'transcript.json'
            path.write_text(json.dumps({'adId': payload['ad_id'], **document}, ensure_ascii=False, indent=2))
            result = client.upload(path, payload['ad_id'] + '-transcripcion-v' + str(document['version']) + '.json',
                                   'application/json', 'transcript-' + document['id'])
        with store.session.begin() as db:
            transcript = db.get(Transcript, payload['transcript_id'])
            transcript.drive_file_id, transcript.drive_url = result['id'], result.get('webViewLink') or 'https://drive.google.com/file/d/' + result['id'] + '/view'
    elif job['kind'] == 'transcribe':
        origin = 'kie:' + MODEL + ':' + payload['asset_id']
        with store.session() as db:
            if db.scalar(select(Transcript.id).where(Transcript.ad_id == payload['ad_id'], Transcript.origin == origin)):
                return True  # A saved analysis is never charged again on a recovered job.
            asset = db.get(Asset, payload['asset_id'])
            if not asset:
                raise Blocked('No se encontró el video para transcribir.')
            path, source_url, file_id = asset.local_path, asset.source_url, asset.drive_file_id
        from transcription import configured
        if not configured():
            raise TranscriptionUnavailable('Configura KIE_API_KEY en el worker para transcribir automáticamente. KIE_TRANSCRIPTION_ENABLED=0 desactiva el análisis.')
        if not path or not Path(path).is_file():
            if file_id:
                path = str(media_dir() / (payload['asset_id'] + '.mp4'))
                sha, size = DriveClient.from_store(store).download(file_id, path)
            else:
                path, sha, size = download_video(source_url, payload['asset_id'])
            with store.session.begin() as db:
                asset = db.get(Asset, payload['asset_id'])
                asset.local_path, asset.sha256, asset.size = path, sha, size
        speech, scenes = transcribe_video(path)
        store.save_transcript(payload['ad_id'], speech, scenes, reviewed=False, origin=origin)
        # Drive may already hold this video if AI was enabled after its upload.
        if file_id:
            with store.session.begin() as db:
                db.get(Asset, payload['asset_id']).local_path = None
            Path(path).unlink(missing_ok=True)
    else:
        raise Blocked('Tipo de tarea no configurado.')
    return True


def run_once(store):
    job = store.claim_job()
    if not job:
        return False
    try:
        finished = process_job(store, job)
        store.finish_job(job['id'], 'done' if finished else 'pending', delay=0 if finished else 30)
    except (Blocked, DriveUnavailable, TranscriptionUnavailable) as error:
        store.finish_job(job['id'], 'blocked', str(error))
    except Exception:
        # Never log provider bodies, connection strings, tokens or raw exceptions.
        store.finish_job(job['id'], 'failed', 'No se pudo completar la tarea. Revisa la configuración y reintenta.')
    return True


def resume_configured_transcriptions(store):
    from transcription import configured
    if not configured():
        return
    with store.session.begin() as db:
        jobs = db.scalars(select(Job).where(Job.kind == 'transcribe', Job.status == 'blocked')).all()
        for job in jobs:
            if job.error and (job.error.startswith('Configura KIE_API_KEY') or job.error.startswith('Proveedor de transcripción de voz')):
                job.status, job.error, job.available_at = 'pending', None, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('Configura DATABASE_URL para ejecutar el worker.')
    try:
        store = LibraryStore(url)
    except Exception:
        raise SystemExit('No se pudo conectar la base de datos. Revisa DATABASE_URL.') from None
    resume_configured_transcriptions(store)
    while True:
        processed = run_once(store)
        if args.once:
            return
        if not processed:
            time.sleep(5)


if __name__ == '__main__':
    main()
