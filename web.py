"""Private web interface. Configure secrets before starting this app."""
from collections import deque
from datetime import timedelta
import os
import secrets
import threading
import time
from urllib.parse import quote

from flask import Flask, abort, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash

from scraper import ApifyClient
from kie import chat_models, complete
from ad_inputs import ACTORS, search_plan
from library_api import register_library


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("WEB_SESSION_SECRET"),
        PASSWORD_HASH=os.environ.get("WEB_PASSWORD_HASH"),
        USERNAME=os.environ.get("WEB_USERNAME", "leadsicon"),
        SESSION_COOKIE_SECURE=os.environ.get("WEB_LOCAL_HTTP") != "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=65536,
    )
    if config:
        app.config.update(config)
    if not app.config["SECRET_KEY"] or not app.config["PASSWORD_HASH"]:
        raise RuntimeError("Configura WEB_SESSION_SECRET y WEB_PASSWORD_HASH antes de iniciar.")
    attempts = deque()
    attempt_lock = threading.Lock()

    @app.before_request
    def protect():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        if request.endpoint not in {"login", "static"} and not session.get("authenticated"):
            if request.path.startswith("/api/"):
                abort(401)
            return redirect("/login")
        if request.method == "POST":
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
            if not secrets.compare_digest(supplied, session["csrf"]):
                abort(403)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' https:; media-src 'self' https:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            # Single private instance: global limit avoids trusting proxy IP headers.
            with attempt_lock:
                now = time.monotonic()
                while attempts and attempts[0] < now - 300:
                    attempts.popleft()
                if len(attempts) >= 10:
                    return render_template("login.html", error="Demasiados intentos. Espera cinco minutos."), 429
                attempts.append(now)
            password_valid = check_password_hash(app.config["PASSWORD_HASH"], request.form.get("password", ""))
            username_valid = secrets.compare_digest(
                request.form.get("username", "").encode(), app.config["USERNAME"].encode()
            )
            if username_valid and password_valid:
                session.clear()
                session.update(authenticated=True, csrf=secrets.token_urlsafe(32))
                session.permanent = True
                return redirect("/")
            error = "Usuario o contraseña incorrectos."
        return render_template("login.html", error=error), 401 if error else 200

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/")
    def index():
        return render_template("studio.html")

    @app.get("/ads")
    def ads():
        return render_template("index.html", configured={
            p: bool(os.environ.get("APIFY_TOKEN"))
            for p in ("facebook", "youtube")
        }, actors=ACTORS)

    @app.post("/api/scraper/plan")
    def scraper_plan():
        try:
            return jsonify(search_plan(request.get_json(silent=True)))
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400

    @app.get("/chat")
    def chat():
        error = None
        try:
            models = chat_models()
        except RuntimeError as exc:
            models, error = [], str(exc)
        return render_template("chat.html", models=models, configuration_error=error,
                               configured=bool(models and os.environ.get("KIE_API_KEY")))

    @app.post("/api/chat")
    def chat_reply():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="Envía una conversación válida."), 400
        messages = body.get("messages")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 20:
            return jsonify(error="La conversación debe contener entre 1 y 20 mensajes."), 400
        total = 0
        for index, message in enumerate(messages):
            if (not isinstance(message, dict) or message.get("role") != ("user" if index % 2 == 0 else "assistant")
                    or not isinstance(message.get("content"), str) or not message["content"].strip()
                    or len(message["content"]) > 6000):
                return jsonify(error="Revisa el orden y el tamaño de los mensajes (máximo 6000 caracteres)."), 400
            total += len(message["content"])
        if messages[-1]["role"] != "user" or total > 24000:
            return jsonify(error="Termina con tu pregunta y limita el historial a 24000 caracteres."), 400
        try:
            models = chat_models()
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 503
        model = next((model for model in models if model["id"] == body.get("model")), None)
        if model is None:
            return jsonify(error="Selecciona un modelo configurado en el servidor."), 400
        token = os.environ.get("KIE_API_KEY")
        if not token:
            return jsonify(error="Configura KIE_API_KEY en los secretos de Render."), 503
        instruction = (
            "Eres el asistente de contenido UGC de Leadsicon. Responde en español. "
            "Ayuda a desarrollar ideas, hooks, guiones y variantes manteniendo el ángulo. "
            "Pregunta por información necesaria que falte. No inventes resultados, cifras, "
            "testimonios ni características de la empresa. No afirmes haber producido videos."
        )
        safe_messages = [{"role": message["role"], "content": message["content"]} for message in messages]
        try:
            reply = complete(model, [{"role": "system", "content": instruction}] + safe_messages, token)
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(content=reply, model=model["id"])

    @app.post("/api/runs")
    def start():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get("platform") not in {"facebook", "youtube"}:
            return jsonify(error="Selecciona Facebook o YouTube."), 400
        if not isinstance(body.get("input"), dict):
            return jsonify(error="El input del Actor debe ser un objeto JSON."), 400
        platform = body["platform"]
        actor = ACTORS[platform]
        token = os.environ.get("APIFY_TOKEN")
        if not token:
            return jsonify(error="Configura APIFY_TOKEN en los secretos de Render."), 503
        try:
            run = ApifyClient(token).request(
                f"acts/{quote(actor.replace('/', '~'), safe='')}/runs", body["input"]
            )["data"]
        except (RuntimeError, KeyError):
            return jsonify(error="No se pudo confirmar el inicio. Revisa Apify antes de repetir."), 502
        session["runs"] = (session.get("runs", []) + [run["id"]])[-20:]
        result = {"id": run["id"], "status": run["status"]}
        if app.config.get("DATABASE_URL") or os.environ.get("DATABASE_URL"):
            try:
                app.extensions['library_store']().import_run(run['id'], platform, actor, body['input'])
            except Exception:
                result['libraryWarning'] = 'La búsqueda empezó, pero no se confirmó su guardado en Supabase. No repitas la búsqueda; revisa la biblioteca.'
        else:
            result['libraryWarning'] = 'Falta configurar Supabase; estos resultados aún no se guardan automáticamente en la biblioteca.'
        return jsonify(result), 201

    @app.get("/api/runs/<run_id>")
    def status(run_id):
        if run_id not in session.get("runs", []):
            abort(404)
        token = os.environ.get("APIFY_TOKEN")
        if not token:
            return jsonify(error="Apify no está configurado."), 503
        try:
            run = ApifyClient(token).request(f"actor-runs/{quote(run_id, safe='')}")["data"]
            result = {"id": run_id, "status": run["status"]}
            if run["status"] == "SUCCEEDED":
                # Bounded preview; full exports remain available in the CLI.
                dataset = quote(run["defaultDatasetId"], safe="")
                result["items"] = ApifyClient(token).request(f"datasets/{dataset}/items?format=json&limit=100")
            return jsonify(result)
        except (RuntimeError, KeyError):
            return jsonify(error="No se pudo consultar Apify."), 502

    register_library(app)
    return app
