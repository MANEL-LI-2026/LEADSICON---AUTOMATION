"""Authenticated client for a private HF endpoint running the bundled video handler."""
import base64
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from kie import NoRedirect
from transcription import TranscriptionUnavailable


def endpoint_url():
    value = os.environ.get('HF_TRANSCRIPTION_ENDPOINT', '').strip()
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.endpoints.huggingface.cloud')
                or url.username or url.password or url.port not in (None, 443) or url.query or url.fragment
                or url.path not in ('', '/')):
            raise ValueError()
    except ValueError:
        raise TranscriptionUnavailable('HF_TRANSCRIPTION_ENDPOINT debe ser la URL HTTPS raíz de tu endpoint privado de Hugging Face.') from None
    return value.rstrip('/')


def configured():
    if not os.environ.get('HF_TOKEN') or not os.environ.get('HF_TRANSCRIPTION_ENDPOINT'):
        return False
    try:
        endpoint_url()
        return os.environ.get('HF_TRANSCRIPTION_ENABLED', '1') == '1'
    except TranscriptionUnavailable:
        return False


def transcribe_video(path):
    endpoint = endpoint_url()
    if not os.environ.get('HF_TOKEN') or os.environ.get('HF_TRANSCRIPTION_ENABLED', '1') != '1':
        raise TranscriptionUnavailable('Configura HF_TOKEN en el worker y habilita HF_TRANSCRIPTION_ENABLED=1.')
    path = Path(path)
    maximum = int(os.environ.get('HF_MAX_VIDEO_BYTES', str(20 * 1024 * 1024)))
    if path.stat().st_size > maximum:
        raise TranscriptionUnavailable('El video supera HF_MAX_VIDEO_BYTES. Ajusta el límite compatible con tu endpoint o usa un video más pequeño.')
    with path.open('rb') as handle:
        content = handle.read(maximum + 1)
    if not content or len(content) > maximum or len(content) < 12 or content[4:8] != b'ftyp':
        raise TranscriptionUnavailable('Hugging Face necesita un MP4 válido dentro del límite configurado.')
    payload = json.dumps({'inputs': {'video_base64': base64.b64encode(content).decode(), 'schema_version': 1}}).encode()
    request = Request(endpoint, data=payload, method='POST', headers={
        'Authorization': 'Bearer ' + os.environ['HF_TOKEN'], 'Content-Type': 'application/json',
        'X-Scale-Up-Timeout': '60'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=600) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError()
        document = json.loads(raw)
        if not isinstance(document, dict) or document.get('schemaVersion') != 1 or document.get('error'):
            raise ValueError()
        duration = document.get('duration')
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError()
        from transcript_validation import validated_transcript
        if not isinstance(document.get('speech'), list) or not isinstance(document.get('scenes'), list):
            raise ValueError()
        speech, scenes, _ = validated_transcript({**document, 'reviewed': False})
        if not scenes or any(segment['end'] > duration + .1 for segment in speech + scenes):
            raise ValueError()
        return speech, scenes
    except HTTPError as error:
        if error.code in (401, 403):
            raise TranscriptionUnavailable('Hugging Face rechazó el acceso. Revisa HF_TOKEN y los permisos del endpoint privado.') from None
        if error.code in (429, 503):
            raise TranscriptionUnavailable('El endpoint de Hugging Face está ocupado o arrancando. Revisa su estado antes de reintentar.') from None
        raise TranscriptionUnavailable('Hugging Face no confirmó el análisis. Revisa el endpoint y sus logs privados antes de reintentar.') from None
    except (URLError, TimeoutError):
        raise TranscriptionUnavailable('No se confirmó el análisis de Hugging Face. Puede seguir activo; revisa el endpoint antes de reintentar.') from None
    except (ValueError, TypeError, KeyError):
        raise TranscriptionUnavailable('Hugging Face no devolvió voz, hablantes y escenas con tiempos válidos. Instala el handler de este repositorio; no sirve un endpoint de Whisper solo.') from None


def remote_mode():
    from transcription import provider_name
    return provider_name() == 'huggingface' and os.environ.get('HF_PROCESSING_MODE', 'remote') == 'remote'


def notify_remote():
    if not configured():
        return {'status': 'pending_configuration', 'message': 'Guardado en Supabase. Configura el endpoint de Hugging Face y HF_TOKEN para procesarlo sin worker de Render.'}
    request = Request(endpoint_url(), data=json.dumps({'inputs': {'action': 'process_pending', 'schema_version': 1}}).encode(),
                      method='POST', headers={'Authorization': 'Bearer ' + os.environ['HF_TOKEN'], 'Content-Type': 'application/json'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            result = json.loads(response.read(65536))
        if not isinstance(result, dict) or result.get('accepted') is not True or result.get('storage') != 'supabase':
            raise ValueError()
        return {'status': 'accepted', 'message': 'Guardado en Supabase. Hugging Face procesará el video y guardará la transcripción automáticamente.'}
    except Exception:
        # The durable jobs still exist. A timeout never resets/repeats a possibly-running job.
        return {'status': 'unconfirmed', 'message': 'Guardado en Supabase, pero no se confirmó el aviso a Hugging Face. Revisa su configuración; el endpoint activo recupera la cola automáticamente.'}
