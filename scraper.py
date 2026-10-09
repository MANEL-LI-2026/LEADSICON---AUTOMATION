"""Run advertising Actors on Apify and export their datasets."""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from ad_inputs import ACTORS


class ApifyClient:
    def __init__(self, token):
        self.token = token

    def request(self, path, payload=None):
        request = Request(
            "https://api.apify.com/v2/" + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            # Do not print response bodies, which may contain sensitive input.
            raise RuntimeError(f"Apify respondió HTTP {error.code}.") from None
        except (URLError, TimeoutError):
            raise RuntimeError("No se pudo completar la conexión con Apify.") from None

    def run(self, actor, actor_input, timeout):
        actor_id = quote(actor.replace("/", "~"), safe="")
        run = self.request(f"acts/{actor_id}/runs", actor_input)["data"]
        run_id = quote(run["id"], safe="")
        deadline = time.monotonic() + timeout
        while run["status"] in {"READY", "RUNNING", "TIMING-OUT", "ABORTING"}:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Tiempo de espera agotado. Run {run['id']} puede seguir activo "
                    "y generar costes; revísalo en Apify antes de repetir."
                )
            time.sleep(min(2, max(0, deadline - time.monotonic())))
            run = self.request(f"actor-runs/{run_id}")["data"]
        if run["status"] != "SUCCEEDED":
            raise RuntimeError(f"Run {run['id']}: {run['status']}.")
        return run

    def items(self, dataset_id):
        result = []
        dataset_id = quote(dataset_id, safe="")
        while True:
            query = urlencode({"format": "json", "offset": len(result), "limit": 1000})
            page = self.request(f"datasets/{dataset_id}/items?{query}")
            if not page:
                return result
            result.extend(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=["facebook", "youtube"])
    parser.add_argument("--input", required=True, type=Path,
                        help="JSON con los parámetros del Actor elegido")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout debe ser positivo")
    try:
        token = os.environ.get("APIFY_TOKEN")
        actor = ACTORS[args.platform]
        if not token or not actor:
            raise ValueError("Configura APIFY_TOKEN en el entorno.")
        actor_input = json.loads(args.input.read_text())
        if not isinstance(actor_input, dict):
            raise ValueError("El input debe ser un objeto JSON.")
        client = ApifyClient(token)
        run = client.run(actor, actor_input, args.timeout)
        items = client.items(run["defaultDatasetId"])
        output = args.output or Path("output") / f"{args.platform}-{run['id']}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents overwriting an earlier export.
        with output.open("x") as handle:
            json.dump({"platform": args.platform, "actor": actor,
                       "run_id": run["id"], "items": items}, handle,
                      ensure_ascii=False, indent=2)
        print(f"Exportados {len(items)} registros a {output}")
        return 0
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
