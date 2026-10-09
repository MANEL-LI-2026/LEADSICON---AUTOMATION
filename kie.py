"""Configurable Kie adapter for documented OpenAI-compatible chat routes."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def chat_models():
    """Only expose models explicitly configured by the server administrator."""
    raw = os.environ.get("KIE_CHAT_MODELS", "[]")
    try:
        models = json.loads(raw)
        if not isinstance(models, list) or len(models) > 30:
            raise ValueError()
        seen = set()
        for model in models:
            if not isinstance(model, dict):
                raise ValueError()
            for field in ("id", "name", "endpoint"):
                if not isinstance(model.get(field), str) or not model[field].strip():
                    raise ValueError()
            url = urlsplit(model["endpoint"])
            if (url.scheme != "https" or url.hostname != "api.kie.ai" or
                    url.username or url.password or url.port not in (None, 443) or
                    url.query or url.fragment or not url.path.strip("/")):
                raise ValueError()
            if model["id"] in seen:
                raise ValueError()
            seen.add(model["id"])
        return models
    except (ValueError, TypeError):
        raise RuntimeError("Revisa KIE_CHAT_MODELS: IDs únicos y endpoints HTTPS de api.kie.ai.") from None


def complete(model, messages, token):
    request = Request(
        model["endpoint"],
        data=json.dumps({"model": model["id"], "messages": messages,
                         "stream": False}).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            body = json.load(response)
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "\n".join(part["text"] for part in content
                                if isinstance(part, dict) and isinstance(part.get("text"), str))
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
        return content
    except HTTPError as error:
        if error.code in (401, 403):
            raise RuntimeError("Kie rechazó el acceso. Revisa la clave y los permisos del modelo.") from None
        if error.code == 429:
            raise RuntimeError("Kie limitó la petición. Revisa los límites y el saldo antes de reintentar.") from None
        raise RuntimeError(f"Kie respondió HTTP {error.code}. Revisa el endpoint y el modelo.") from None
    except (URLError, TimeoutError):
        raise RuntimeError("No se pudo confirmar la respuesta de Kie. La petición puede haber consumido crédito.") from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError("La respuesta no tiene el formato de chat esperado. Revisa la documentación del modelo.") from None
