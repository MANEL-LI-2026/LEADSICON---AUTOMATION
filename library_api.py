"""Authenticated library routes, registered inside the application's existing session guard."""
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from flask import Response, abort, jsonify, redirect, render_template, request, send_file, session, stream_with_context
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from library_store import Ad, Asset, Integration, LibraryStore, Transcript, Run, Job
from drive_client import DriveClient, DriveUnavailable, connect, oauth_config
from transcription import TranscriptionUnavailable


class LibraryUnavailable(RuntimeError):
    pass


def connection_failure(error):
    # Inspect internally, return only fixed messages; never expose URLs or provider errors.
    original = getattr(error, 'orig', error)
    state = getattr(original, 'sqlstate', None)
    detail = str(original).lower()
    if state in ('28P01', '28000') or 'password authentication failed' in detail:
        return 'Supabase rechazó el usuario o la contraseña. Revisa la contraseña de la base de datos y su codificación en DATABASE_URL.'
    if 'tenant or user not found' in detail:
        return 'El pooler no reconoce el proyecto o usuario. Copia el host y usuario exactos desde Connect → Session pooler de tu proyecto.'
    if state == '42501' or 'permission denied' in detail or 'must be owner' in detail:
        return 'Se alcanzó Supabase, pero faltan permisos para crear tablas o activar RLS. Usa la conexión PostgreSQL del propietario del proyecto.'
    if 'could not translate host name' in detail or 'name or service not known' in detail or 'failed to resolve' in detail:
        return 'No se pudo resolver el servidor de Supabase. Revisa el host de Session pooler y que el proyecto esté activo.'
    if 'timeout' in detail or 'timed out' in detail or 'connection refused' in detail or 'network is unreachable' in detail:
        return 'No se pudo alcanzar Supabase. Comprueba que el proyecto esté activo y las restricciones de red permitan la conexión desde Render.'
    if 'ssl' in detail or 'certificate' in detail:
        return 'Falló la conexión TLS a Supabase. Usa la cadena oficial con sslmode=require.'
    if isinstance(error, (ValueError, TypeError)) or 'could not parse' in detail:
        return 'DATABASE_URL tiene un formato inválido. Usa una URL PostgreSQL sin comillas y codifica los caracteres especiales de la contraseña.'
    return 'No se pudo inicializar Supabase. La causa puede ser conexión o creación de tablas; revisa la configuración sin compartir DATABASE_URL.'


def validated_transcript(body):
    if not isinstance(body, dict):
        raise ValueError('Revisa la transcripción.')
    channels = []
    for channel in ('speech', 'scenes'):
        segments = body.get(channel, [])
        if not isinstance(segments, list) or len(segments) > 200:
            raise ValueError('Máximo 200 segmentos por capa.')
        clean = []
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError('Revisa los segmentos.')
            start, end = segment.get('start'), segment.get('end')
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start):
                raise ValueError('Los tiempos deben ser segundos válidos: inicio ≥ 0 y fin > inicio.')
            field = 'text' if channel == 'speech' else 'description'
            text = segment.get(field)
            if not isinstance(text, str) or not text.strip() or len(text) > 6000:
                raise ValueError('Cada segmento necesita texto (máximo 6000 caracteres).')
            item = {'start': start, 'end': end, field: text.strip()}
            if channel == 'speech':
                speaker = segment.get('speaker', 'Sin identificar')
                role = segment.get('role', 'unknown')
                if not isinstance(speaker, str) or not speaker.strip() or len(speaker) > 80 or role not in ('on_camera', 'voiceover', 'unknown'):
                    raise ValueError('Revisa el hablante y el tipo de voz.')
                item.update(speaker=speaker.strip(), role=role)
            clean.append(item)
        channels.append(sorted(clean, key=lambda segment: segment['start']))
    if type(body.get('reviewed', False)) is not bool:
        raise ValueError('El estado revisado debe ser verdadero o falso.')
    return *channels, body.get('reviewed', False)


def register_library(app):
    lock = threading.Lock()
    store_cache = None

    def store():
        nonlocal store_cache
        if store_cache is not None:
            return store_cache
        url = app.config.get('DATABASE_URL') or os.environ.get('DATABASE_URL')
        if not url:
            raise LibraryUnavailable('Configura DATABASE_URL de Supabase en Render para guardar anuncios de forma permanente.')
        with lock:
            if store_cache is None:
                try:
                    store_cache = LibraryStore(url)
                except Exception as error:
                    raise LibraryUnavailable(connection_failure(error)) from None
        return store_cache

    app.extensions['library_store'] = store

    @app.errorhandler(LibraryUnavailable)
    @app.errorhandler(DriveUnavailable)
    @app.errorhandler(TranscriptionUnavailable)
    def unavailable(error):
        return jsonify(error=str(error)), 503

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        return jsonify(error='No se pudo guardar o leer la base de datos. Reintenta; no se han confirmado los cambios.'), 503

    @app.get('/library')
    def library():
        return render_template('library.html')

    @app.get('/library/<ad_id>')
    def library_detail(ad_id):
        return render_template('library-detail.html', ad_id=ad_id)

    @app.get('/api/library')
    def library_items():
        limit = min(100, max(1, request.args.get('limit', 50, type=int)))
        offset = max(0, request.args.get('offset', 0, type=int))
        return jsonify(items=store().list_ads(request.args.get('liked') == '1', limit, offset))

    @app.get('/api/library/runs')
    def library_runs():
        with store().session() as db:
            rows = db.execute(select(Run, Job).join(Job, Job.key == ('run:' + Run.id))
                              .order_by(Run.created_at.desc()).limit(20)).all()
            return jsonify(items=[{'id': run.id, 'platform': run.platform, 'status': job.status,
                                   'error': job.error} for run, job in rows])

    @app.post('/api/library/runs/<run_id>/retry')
    def retry_import(run_id):
        with store().session.begin() as db:
            job = db.scalar(select(Job).where(Job.key == 'run:' + run_id, Job.kind == 'import_run'))
            if not job:
                abort(404)
            if job.status in ('blocked', 'failed'):
                job.status, job.error, job.available_at = 'pending', None, 0
        return jsonify(ok=True)

    @app.get('/api/library/config')
    def library_config():
        configured = bool(app.config.get('DATABASE_URL') or os.environ.get('DATABASE_URL'))
        connected = False
        if configured:
            with store().session() as db:
                connected = db.get(Integration, 'google-drive') is not None
        from transcription import configured as transcription_configured, provider_name
        return jsonify(databaseConfigured=configured, driveConnected=connected, transcriptionProviderConfigured=transcription_configured(), transcriptionProvider=provider_name())

    @app.post('/api/library/ads')
    def library_save():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('platform') not in ('facebook', 'youtube') or not isinstance(body.get('raw'), dict):
            return jsonify(error='Revisa los datos del anuncio.'), 400
        if type(body.get('liked', True)) is not bool:
            return jsonify(error='Revisa el estado del favorito.'), 400
        try:
            ad_id = store().save_ad(body['platform'], body['raw'], liked=body.get('liked', True))
            return jsonify(store().get_ad(ad_id)), 201
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post('/api/library/references')
    def library_reference():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('url'), str):
            return jsonify(error='Añade un enlace de Facebook.'), 400
        try:
            url = urlsplit(body['url'])
            if (url.scheme != 'https' or url.hostname not in ('facebook.com', 'www.facebook.com', 'm.facebook.com', 'fb.watch')
                    or url.username or url.password or url.port not in (None, 443) or not url.path.strip('/')):
                raise ValueError()
        except ValueError:
            return jsonify(error='Usa un enlace HTTPS válido de Facebook o fb.watch.'), 400
        title = body.get('title', 'Referencia orgánica')
        if not isinstance(title, str) or len(title) > 200:
            return jsonify(error='El título debe tener hasta 200 caracteres.'), 400
        ad_id = store().save_ad('facebook', {'organicUrl': body['url'], 'adUrl': body['url'],
                                            'pageName': title or 'Referencia orgánica'}, kind='organic', liked=True)
        return jsonify(store().get_ad(ad_id)), 201

    @app.get('/api/library/ads/<ad_id>')
    def library_ad(ad_id):
        try:
            return jsonify(store().get_ad(ad_id))
        except KeyError:
            abort(404)

    @app.post('/api/library/ads/<ad_id>/like')
    def library_like(ad_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or type(body.get('liked')) is not bool:
            return jsonify(error='Revisa el estado del favorito.'), 400
        try:
            return jsonify(store().set_like(ad_id, body['liked']))
        except KeyError:
            abort(404)

    @app.get('/api/library/ads/<ad_id>/transcripts')
    def library_versions(ad_id):
        try:
            store().get_ad(ad_id)
        except KeyError:
            abort(404)
        with store().session() as db:
            versions = db.scalars(select(Transcript).where(Transcript.ad_id == ad_id)
                                  .order_by(Transcript.version.desc()).limit(100)).all()
            return jsonify(items=[store().transcript_json(version) for version in versions])

    @app.post('/api/library/ads/<ad_id>/transcript')
    def library_transcript(ad_id):
        try:
            body = request.get_json(silent=True)
            speech, scenes, reviewed = validated_transcript(body)
            source_id = body.get('sourceAssetId')
            origin = 'manual'
            if source_id is not None:
                if not isinstance(source_id, str):
                    raise ValueError('Revisa el video de origen de la transcripción.')
                with store().session() as db:
                    asset = db.get(Asset, source_id)
                    if not asset or asset.ad_id != ad_id:
                        raise ValueError('El video de origen no pertenece a este anuncio.')
                origin += ':' + source_id
            return jsonify(store().save_transcript(ad_id, speech, scenes, reviewed, origin=origin))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except KeyError:
            abort(404)

    @app.post('/api/library/ads/<ad_id>/retry')
    def library_retry(ad_id):
        try:
            store().get_ad(ad_id)
            store().prepare_assets(ad_id)
            store().retry_jobs(ad_id)
            return jsonify(store().get_ad(ad_id))
        except KeyError:
            abort(404)

    @app.get('/api/library/ads/<ad_id>/export')
    def library_export(ad_id):
        try:
            data = store().get_ad(ad_id)
        except KeyError:
            abort(404)
        return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype='application/json',
                        headers={'Content-Disposition': f'attachment; filename="anuncio-{ad_id}.json"'})

    @app.get('/api/library/knowledge')
    def knowledge():
        # Future skills can read reviewed examples; no automatic prompt rewriting/training.
        limit = min(100, max(1, request.args.get('limit', 50, type=int)))
        offset = max(0, request.args.get('offset', 0, type=int))
        with store().session() as db:
            ids = db.scalars(select(Ad.id).where(Ad.liked.is_(True)).order_by(Ad.created_at).limit(limit).offset(offset)).all()
        items = [store().get_ad(ad_id) for ad_id in ids]
        reviewed = [item for item in items if item['transcript'] and item['transcript']['reviewed']]
        return jsonify(schemaVersion=1, items=reviewed, nextOffset=offset + len(ids), scanned=len(ids))

    @app.post('/api/drive/connect')
    def drive_connect():
        store()  # Credentials are never persisted into browser storage.
        client_id, _, redirect_uri = oauth_config()
        from drive_client import cipher
        cipher()
        state = secrets.token_urlsafe(32)
        session['drive_state'] = state
        return jsonify(url='https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code',
            'scope': 'https://www.googleapis.com/auth/drive.file', 'access_type': 'offline',
            'prompt': 'consent', 'state': state}))

    @app.get('/integrations/google/callback')
    def drive_callback():
        expected = session.pop('drive_state', None)
        state = request.args.get('state', '')
        if not expected or not secrets.compare_digest(expected, state):
            abort(403)
        code = request.args.get('code')
        if not code:
            return redirect('/library?drive=cancelled')
        try:
            connect(store(), code)
        except DriveUnavailable:
            return redirect('/library?drive=error')
        return redirect('/library?drive=connected')

    @app.get('/api/library/assets/<asset_id>/media')
    def library_media(asset_id):
        with store().session() as db:
            asset = db.get(Asset, asset_id)
            if not asset:
                abort(404)
            path, file_id = asset.local_path, asset.drive_file_id
        attachment = request.args.get('download') == '1'
        if path and Path(path).is_file():
            return send_file(path, mimetype='video/mp4', as_attachment=attachment, download_name=asset_id + '.mp4', conditional=True)
        if not file_id:
            return jsonify(error='El video todavía no está descargado o subido a Drive.'), 409
        client = DriveClient.from_store(store())
        headers = {'Authorization': 'Bearer ' + client.token}
        requested_range = request.headers.get('Range')
        if requested_range and re.fullmatch(r'bytes=\d+-\d*', requested_range):
            headers['Range'] = requested_range
        try:
            remote = urlopen(Request('https://www.googleapis.com/drive/v3/files/' + quote(file_id, safe='') + '?alt=media', headers=headers), timeout=30)
        except Exception:
            raise DriveUnavailable('No se pudo recuperar el archivo de Drive.') from None
        def chunks():
            try:
                while chunk := remote.read(256 * 1024):
                    yield chunk
            finally:
                remote.close()
        response_headers = {'Content-Disposition': ('attachment' if attachment else 'inline') + '; filename="' + asset_id + '.mp4"'}
        for name in ('Content-Length', 'Content-Range', 'Accept-Ranges'):
            if remote.headers.get(name):
                response_headers[name] = remote.headers[name]
        return Response(stream_with_context(chunks()), status=remote.status, mimetype='video/mp4', headers=response_headers)
