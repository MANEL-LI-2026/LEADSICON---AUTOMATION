"""Inputs verified against the selected Actors' latest published build schemas."""
from urllib.parse import urlencode, urlsplit

ACTORS = {"facebook": "JJghSZmShuco4j9gJ", "youtube": "iRsL8PTQjmWC1SaPQ"}
REGIONS = {"", "US", "AR", "MX", "ES", "GB", "CA"}


def search_plan(body):
    if not isinstance(body, dict) or body.get("platform") not in ACTORS:
        raise ValueError("Selecciona Facebook o YouTube.")
    if body.get("mode", "paid") != "paid":
        raise ValueError("Los Actors elegidos extraen anuncios pagados. La búsqueda orgánica está pendiente.")
    platform = body["platform"]
    limit = body.get("limit", 10)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Usa un límite de 1 a 100 resultados por búsqueda.")
    region = body.get("region", "US")
    if region not in REGIONS:
        raise ValueError("Selecciona una región válida.")
    search_by = body.get("searchBy", "keywords")
    if search_by not in {"keywords", "advertiser"}:
        raise ValueError("Selecciona búsqueda por keywords o anunciante.")
    text = body.get("queries")
    if not isinstance(text, str):
        raise ValueError("Escribe las keywords o los anunciantes.")
    queries = list(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))
    if not 1 <= len(queries) <= 10 or any(len(query) > 1000 for query in queries):
        raise ValueError("Indica entre 1 y 10 búsquedas, una por línea (máximo 1000 caracteres cada una).")
    if platform == "facebook":
        if search_by == "advertiser":
            for query in queries:
                url = urlsplit(query)
                if (url.scheme != "https" or url.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"}
                        or url.username or url.password or url.port not in (None, 443) or not url.path.strip("/")):
                    raise ValueError("Para Facebook, introduce URLs HTTPS de páginas o de Meta Ad Library.")
            urls = queries
        else:
            urls = ["https://www.facebook.com/ads/library/?" + urlencode({
                "active_status": "active", "ad_type": "all", "country": region or "ALL",
                "q": query, "search_type": "keyword_unordered", "media_type": "all",
                "publisher_platforms[0]": "facebook",
            }) for query in queries]
        runs = [{"label": "Meta · " + str(len(queries)) + " búsquedas", "input": {
            "startUrls": [{"url": url} for url in urls], "resultsLimit": limit,
            "enrichWithEcommerceData": False,
        }}]
    else:
        # searchQuery is a single string: do not concatenate independent keywords.
        runs = [{"label": query, "input": {"searchQuery": query, "platform": "youtube",
                 "maxResults": limit, "region": region}} for query in queries]
    return {"platform": platform, "actor": ACTORS[platform], "runs": runs,
            "queryCount": len(queries), "maximumResults": len(queries) * limit}
