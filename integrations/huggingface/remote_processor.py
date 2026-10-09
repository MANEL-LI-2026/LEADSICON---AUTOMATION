"""Durable processing hosted inside the always-on GPU endpoint, not in Render."""
import math
import os
import threading
from library_store import LibraryStore
from library_worker import run_once
from transcript_validation import validated_transcript
from transcription import TranscriptionUnavailable


class RemoteProcessor:
    def __init__(self, handler, database_url):
        self.handler = handler
        self.store = LibraryStore(database_url)
        self.wakeup = threading.Event()
        self.stopping = threading.Event()
        self.thread = None

    def analyze(self, path):
        if os.environ.get('HF_TRANSCRIPTION_ENABLED', '1') != '1':
            raise TranscriptionUnavailable('Configura HF_TRANSCRIPTION_ENABLED=1 en el endpoint para activar las transcripciones.')
        result = self.handler.analyze_path(path)
        if not isinstance(result, dict) or result.get('error') or result.get('schemaVersion') != 1:
            raise TranscriptionUnavailable('El endpoint de Hugging Face no pudo analizar el video. Revisa sus logs privados antes de reintentar.')
        speech, scenes, _ = validated_transcript({**result, 'reviewed': False})
        duration = result.get('duration')
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0 or not scenes or any(segment['end'] > duration + .1 for segment in speech + scenes):
            raise TranscriptionUnavailable('El endpoint devolvió tiempos o escenas incompletos. No se confirmó una transcripción válida.')
        return speech, scenes

    def process_one(self):
        return run_once(self.store, analyzer=self.analyze,
                        origin_factory=lambda asset_id: 'hf:whisper-pyannote-vlm:' + asset_id)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        # No remote inference call is needed: models are loaded in this process.
        from sqlalchemy import select
        from library_store import Job
        with self.store.session.begin() as db:
            for job in db.scalars(select(Job).where(Job.kind == 'transcribe', Job.status == 'blocked')):
                if job.error and job.error.startswith(('Configura HF_TOKEN', 'Configura KIE_API_KEY', 'Configura HF_TRANSCRIPTION_ENABLED', 'Proveedor de transcripción')):
                    job.status, job.error, job.available_at = 'pending', None, 0
        def loop():
            while not self.stopping.is_set():
                try:
                    processed = self.process_one()
                except Exception:
                    # Keep the runner alive during database outages; never log connection strings.
                    processed = False
                if not processed:
                    self.wakeup.wait(5)
                    self.wakeup.clear()
        self.thread = threading.Thread(target=loop, name='leadsicon-hf-processing', daemon=True)
        self.thread.start()

    def notify(self):
        self.wakeup.set()

    def stop(self):
        self.stopping.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=2)
