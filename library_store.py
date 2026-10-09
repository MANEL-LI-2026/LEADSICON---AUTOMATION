"""Persistent ad library and durable job queue (PostgreSQL in production)."""
from pathlib import Path
from functools import wraps
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Float, Integer, JSON, String, Text, UniqueConstraint, create_engine, select, update, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Ad(Base):
    __tablename__ = 'leadsicon_ads'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), unique=True)
    platform: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20), default='paid')
    raw: Mapped[dict] = mapped_column(JSON)
    liked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class Asset(Base):
    __tablename__ = 'leadsicon_assets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ad_id: Mapped[str] = mapped_column(String(36), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    source_key: Mapped[str] = mapped_column(String(64), unique=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    drive_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class Transcript(Base):
    __tablename__ = 'leadsicon_transcripts'
    __table_args__ = (UniqueConstraint('ad_id', 'version'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ad_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    speech: Mapped[list] = mapped_column(JSON)
    scenes: Mapped[list] = mapped_column(JSON)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(80), default='manual')
    drive_file_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    drive_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(Base):
    __tablename__ = 'leadsicon_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[float] = mapped_column(Float, default=0)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))


class Run(Base):
    __tablename__ = 'leadsicon_runs'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(100))
    input: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))


class Integration(Base):
    __tablename__ = 'leadsicon_integrations'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    encrypted_token: Mapped[str] = mapped_column(Text)
    folder_id: Mapped[str] = mapped_column(String(200))


def video_urls(raw):
    snapshot = raw.get('snapshot') if isinstance(raw.get('snapshot'), dict) else {}
    candidates = [raw] + [item for key in ('videos', 'cards') for item in (snapshot.get(key) if isinstance(snapshot.get(key), list) else [])]
    result = []
    for part in candidates:
        if not isinstance(part, dict):
            continue
        url = next((part.get(key) for key in ('videoUrl', 'videoHdUrl', 'video_hd_url', 'videoSdUrl', 'video_sd_url') if part.get(key)), None)
        if isinstance(url, str) and url not in result:
            result.append(url)
    return result[:20]


def retry_unique_conflict(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        for attempt in range(3):
            try:
                return method(*args, **kwargs)
            except IntegrityError:
                if attempt == 2:
                    raise
    return wrapped


class LibraryStore:
    def __init__(self, url):
        if url.startswith('postgres://'):
            url = 'postgresql+psycopg://' + url[len('postgres://'):]
        elif url.startswith('postgresql://'):
            url = 'postgresql+psycopg://' + url[len('postgresql://'):]
        self.engine = create_engine(url, pool_pre_ping=True,
                                    connect_args={'connect_timeout': 10} if url.startswith('postgresql') else {})
        Base.metadata.create_all(self.engine)
        if self.engine.dialect.name == 'postgresql':
            with self.engine.begin() as connection:
                for table in Base.metadata.sorted_tables:
                    connection.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def enqueue(self, kind, key, payload):
        try:
            with self.session.begin() as db:
                db.add(Job(id=str(uuid.uuid4()), key=key, kind=kind, payload=payload,
                           status='pending', attempts=0, created_at=now()))
        except IntegrityError:
            pass  # Existing jobs remain durable; only explicit retry resets failures.

    @retry_unique_conflict
    def import_run(self, run_id, platform, actor, actor_input):
        with self.session.begin() as db:
            if not db.get(Run, run_id):
                db.add(Run(id=run_id, platform=platform, actor=actor, input=actor_input, created_at=now()))
        self.enqueue('import_run', 'run:' + run_id, {'run_id': run_id, 'platform': platform})

    @retry_unique_conflict
    def save_ad(self, platform, raw, kind='paid', liked=None):
        if not isinstance(raw, dict) or not raw:
            raise ValueError('El anuncio debe contener datos.')
        identity = raw.get('adArchiveId') or raw.get('ad_archive_id') or raw.get('creativeId') or raw.get('adUrl') or raw.get('organicUrl')
        identity = str(identity) if identity else json.dumps(raw, sort_keys=True, ensure_ascii=False)
        key = hashlib.sha256((platform + ':' + kind + ':' + identity).encode()).hexdigest()
        with self.session.begin() as db:
            ad = db.scalar(select(Ad).where(Ad.source_key == key))
            if ad is None:
                ad = Ad(id=str(uuid.uuid4()), source_key=key, platform=platform, kind=kind,
                        raw=raw, liked=False, created_at=now(), updated_at=now())
                db.add(ad)
            else:
                ad.raw, ad.updated_at = raw, now()
            if liked is not None:
                ad.liked = liked
            ad_id, saved_like = ad.id, ad.liked
        if saved_like:
            self.prepare_assets(ad_id)
        return ad_id

    @retry_unique_conflict
    def prepare_assets(self, ad_id):
        with self.session.begin() as db:
            ad = db.get(Ad, ad_id)
            if not ad:
                raise KeyError(ad_id)
            for url in video_urls(ad.raw):
                key = hashlib.sha256((ad_id + ':' + url).encode()).hexdigest()
                asset = db.scalar(select(Asset).where(Asset.source_key == key))
                if not asset:
                    asset = Asset(id=str(uuid.uuid4()), ad_id=ad_id, source_url=url, source_key=key)
                    db.add(asset)
                asset_id = asset.id
                # enqueue after committing to avoid SQLite locking and orphan jobs.
                db.flush()
        with self.session() as db:
            assets = db.scalars(select(Asset).where(Asset.ad_id == ad_id)).all()
        for asset in assets:
            self.enqueue('download', 'download:' + asset.id, {'asset_id': asset.id, 'ad_id': ad_id})

    def get_ad(self, ad_id):
        with self.session() as db:
            ad = db.get(Ad, ad_id)
            if not ad:
                raise KeyError(ad_id)
            assets = db.scalars(select(Asset).where(Asset.ad_id == ad_id)).all()
            transcript = db.scalar(select(Transcript).where(Transcript.ad_id == ad_id).order_by(Transcript.version.desc()))
            relevant = db.scalars(select(Job).where(Job.payload['ad_id'].as_string() == ad_id)).all()
            return {'id': ad.id, 'platform': ad.platform, 'kind': ad.kind, 'raw': ad.raw,
                    'liked': ad.liked, 'createdAt': ad.created_at,
                    'assets': [{'id': a.id, 'driveUrl': a.drive_url, 'downloaded': bool(a.sha256),
                                'sourceUrl': a.source_url, 'available': bool(a.drive_file_id or a.local_path and Path(a.local_path).is_file()),
                                'sha256': a.sha256, 'size': a.size} for a in assets],
                    'jobs': [{'id': j.id, 'kind': j.kind, 'status': j.status, 'error': j.error} for j in relevant],
                    'transcript': None if not transcript else self.transcript_json(transcript),
                    'transcriptionStatus': 'saved' if transcript else 'provider_pending'}

    @staticmethod
    def transcript_json(transcript):
        return {'id': transcript.id, 'version': transcript.version, 'speech': transcript.speech,
                'scenes': transcript.scenes, 'reviewed': transcript.reviewed, 'origin': transcript.origin,
                'createdAt': transcript.created_at, 'driveUrl': transcript.drive_url,
                'sourceAssetId': transcript.origin.rsplit(':', 1)[-1] if transcript.origin.startswith(('kie:', 'manual:')) else None}

    def list_ads(self, liked_only=False, limit=50, offset=0):
        with self.session() as db:
            query = select(Ad.id).order_by(Ad.created_at.desc())
            if liked_only:
                query = query.where(Ad.liked.is_(True))
            ids = db.scalars(query.limit(limit).offset(offset)).all()
        return [self.get_ad(ad_id) for ad_id in ids]

    def set_like(self, ad_id, liked):
        with self.session.begin() as db:
            ad = db.get(Ad, ad_id)
            if not ad:
                raise KeyError(ad_id)
            ad.liked, ad.updated_at = liked, now()
        if liked:
            self.prepare_assets(ad_id)
        return self.get_ad(ad_id)

    @retry_unique_conflict
    def save_transcript(self, ad_id, speech, scenes, reviewed=False, origin='manual'):
        if reviewed and not (speech or scenes):
            raise ValueError('Una transcripción vacía no puede marcarse revisada.')
        with self.session.begin() as db:
            if not db.get(Ad, ad_id):
                raise KeyError(ad_id)
            latest = db.scalar(select(Transcript).where(Transcript.ad_id == ad_id).order_by(Transcript.version.desc()))
            transcript = Transcript(id=str(uuid.uuid4()), ad_id=ad_id, version=latest.version + 1 if latest else 1,
                                    speech=speech, scenes=scenes, reviewed=reviewed, created_at=now(), origin=origin)
            db.add(transcript)
            transcript_id = transcript.id
        self.enqueue('drive_transcript', 'transcript:' + transcript_id, {'transcript_id': transcript_id, 'ad_id': ad_id})
        return self.get_ad(ad_id)

    def claim_job(self):
        timestamp = time.time()
        with self.session.begin() as db:
            db.execute(update(Job).where(Job.status == 'running', Job.lease_until < timestamp)
                       .values(status='pending'))
            job = db.scalar(select(Job).where(Job.status == 'pending', Job.available_at <= timestamp)
                            .order_by(Job.created_at).limit(1))
            if not job:
                return None
            changed = db.execute(update(Job).where(Job.id == job.id, Job.status == 'pending')
                                 .values(status='running', lease_until=timestamp + 1800, attempts=Job.attempts + 1))
            if changed.rowcount != 1:
                return None
            return {'id': job.id, 'kind': job.kind, 'payload': job.payload}

    def finish_job(self, job_id, status, error=None, delay=0):
        with self.session.begin() as db:
            job = db.get(Job, job_id)
            job.status, job.error = status, error
            job.available_at, job.lease_until = time.time() + delay, 0

    def retry_jobs(self, ad_id):
        with self.session.begin() as db:
            jobs = db.scalars(select(Job).where(Job.status.in_(['blocked', 'failed']))).all()
            for job in jobs:
                if job.payload.get('ad_id') == ad_id:
                    job.status, job.error, job.available_at = 'pending', None, 0
