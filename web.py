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


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("WEB_SESSION_SECRET"),
        PASSWORD_HASH=os.environ.get("WEB_PASSWORD_HASH"),
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
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
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
            if check_password_hash(app.config["PASSWORD_HASH"], request.form.get("password", "")):
                session.clear()
                session.update(authenticated=True, csrf=secrets.token_urlsafe(32))
                session.permanent = True
                return redirect("/")
            error = "Contraseña incorrecta."
        return render_template("login.html", error=error), 401 if error else 200

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/")
    def index():
        return render_template("index.html", configured={
            p: bool(os.environ.get("APIFY_TOKEN") and os.environ.get(f"APIFY_{p.upper()}_ACTOR"))
            for p in ("facebook", "youtube")
        })

    @app.post("/api/runs")
    def start():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get("platform") not in {"facebook", "youtube"}:
            return jsonify(error="Selecciona Facebook o YouTube."), 400
        if not isinstance(body.get("input"), dict):
            return jsonify(error="El input del Actor debe ser un objeto JSON."), 400
        platform = body["platform"]
        actor = os.environ.get(f"APIFY_{platform.upper()}_ACTOR")
        token = os.environ.get("APIFY_TOKEN")
        if not actor or not token:
            return jsonify(error="Falta configurar el Actor o el token de Apify en el servidor."), 503
        try:
            run = ApifyClient(token).request(
                f"acts/{quote(actor.replace('/', '~'), safe='')}/runs", body["input"]
            )["data"]
        except (RuntimeError, KeyError):
            return jsonify(error="No se pudo confirmar el inicio. Revisa Apify antes de repetir."), 502
        session["runs"] = (session.get("runs", []) + [run["id"]])[-20:]
        return jsonify(id=run["id"], status=run["status"]), 201

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

    return app
