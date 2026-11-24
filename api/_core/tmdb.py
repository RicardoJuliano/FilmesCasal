"""Cliente TMDB (só biblioteca padrão). Idioma pt-BR, região BR."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://api.themoviedb.org/3"
POSTER = "https://image.tmdb.org/t/p/w342"
LOGO = "https://image.tmdb.org/t/p/w92"
LANG = "pt-BR"
REGION = "BR"
TIMEOUT = 6
TTL = 1800  # segundos

_cache = {}
_lock = threading.Lock()


class TMDBError(Exception):
    def __init__(self, msg="Erro ao consultar o TMDB."):
        super().__init__(msg)
        self.msg = msg


def _auth():
    key = os.environ.get("TMDB_API_KEY", "").strip()
    token = os.environ.get("TMDB_READ_TOKEN", "").strip()
    if key:
        return {"api_key": key}, {}
    if token:
        return {}, {"Authorization": "Bearer " + token}
    raise TMDBError("TMDB não configurado: defina TMDB_API_KEY ou TMDB_READ_TOKEN.")


def _fetch(url, headers):
    """Único ponto de rede (mockado nos testes)."""
    req = urllib.request.Request(url, headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise TMDBError("Chave do TMDB inválida.") from e
        if e.code == 404:
            raise TMDBError("Filme não encontrado no TMDB.") from e
        if e.code == 429:
            raise TMDBError("Muitas consultas ao TMDB. Tente de novo em instantes.") from e
        raise TMDBError(f"TMDB respondeu com erro {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TMDBError("Não foi possível falar com o TMDB agora.") from e
    except ValueError as e:
        raise TMDBError("Resposta inválida do TMDB.") from e


def _get(path, params=None, ttl=TTL):
    params = {k: v for k, v in (params or {}).items() if v is not None}
    params.setdefault("language", LANG)
    key = (path, tuple(sorted((k, str(v)) for k, v in params.items())))
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    auth_q, headers = _auth()
    url = API + path + "?" + urllib.parse.urlencode({**params, **auth_q})
    data = _fetch(url, headers)
    with _lock:
        _cache[key] = (now + ttl, data)
    return data


def genres_map():
    data = _get("/genre/movie/list")
    return {g["id"]: g["name"] for g in data.get("genres", [])}


def _movie(raw, gmap, providers=None):
    if raw.get("genres"):
        pairs = [(g["id"], g["name"]) for g in raw["genres"]]
    else:
        pairs = [(i, gmap[i]) for i in raw.get("genre_ids", []) if i in gmap]
    date = raw.get("release_date") or ""
    year = int(date[:4]) if date[:4].isdigit() else None
    poster = raw.get("poster_path")
    return {
        "tmdb_id": raw["id"],
        "title": raw.get("title") or raw.get("original_title") or "",
        "year": year,
        "poster_url": POSTER + poster if poster else None,
        "overview": raw.get("overview") or "",
        "genres": [n for _, n in pairs],
        "runtime": raw.get("runtime") or None,
        "vote": round(float(raw.get("vote_average") or 0), 1),
        "providers": providers or [],
        # extras internos (úteis ao recomendador)
        "genre_ids": [i for i, _ in pairs],
        "language": raw.get("original_language"),
        "vote_count": raw.get("vote_count") or 0,
    }


def _list(path, params=None):
    gmap = genres_map()
    data = _get(path, params)
    return [_movie(r, gmap) for r in data.get("results", []) if r.get("id")]


def get_options():
    genres = [{"id": i, "name": n} for i, n in genres_map().items()]
    genres.sort(key=lambda g: g["name"])
    data = _get("/watch/providers/movie", {"watch_region": REGION})
    items = data.get("results", [])
    items.sort(key=lambda p: (p.get("display_priorities", {}).get(REGION, 999), p["provider_id"]))
    providers = [
        {"id": p["provider_id"], "name": p["provider_name"],
         "logo_url": LOGO + p["logo_path"] if p.get("logo_path") else None}
        for p in items[:20]
    ]
    return {"genres": genres, "providers": providers}


# (with_genres, ano_min, ano_max, idioma original)
_SEED_BUCKETS = [
    ("35", 2011, None, None), ("18", 2000, 2010, None), ("28", 2011, None, None),
    ("10749", 1980, 2010, None), ("878", None, None, None), ("27", 2000, None, None),
    ("16", None, None, None), ("53", 2000, None, None), ("12", None, 1999, None),
    ("80", None, None, None), ("14", None, None, None), (None, None, None, "pt"),
]


def seed_movies():
    def bucket(b):
        g, lo, hi, lang = b
        return _list("/discover/movie", {
            "sort_by": "popularity.desc", "include_adult": "false", "region": REGION,
            "vote_average.gte": 7, "vote_count.gte": 300 if lang else 2000,
            "with_genres": g, "with_original_language": lang,
            "primary_release_date.gte": f"{lo}-01-01" if lo else None,
            "primary_release_date.lte": f"{hi}-12-31" if hi else None,
        })
    with ThreadPoolExecutor(max_workers=6) as ex:
        buckets = list(ex.map(bucket, _SEED_BUCKETS))
    out, seen = [], set()
    for rnd in range(4):
        for b in buckets:
            for m in b[rnd * 2:(rnd + 1) * 2]:
                if m["poster_url"] and m["tmdb_id"] not in seen and len(out) < 20:
                    seen.add(m["tmdb_id"])
                    out.append(m)
    return out


def search(q):
    q = (q or "").strip()
    if not q:
        return []
    movies = _list("/search/movie", {"query": q, "include_adult": "false", "region": REGION})
    return movies[:10]


def movie(tmdb_id):
    data = _get(f"/movie/{int(tmdb_id)}", {"append_to_response": "watch/providers"})
    flat = (data.get("watch/providers", {}).get("results", {}).get(REGION, {}) or {}).get("flatrate", [])
    flat = sorted(flat, key=lambda p: (p.get("display_priority", 999), p["provider_id"]))
    providers = [{"id": p["provider_id"], "name": p["provider_name"],
                  "logo_url": LOGO + p["logo_path"] if p.get("logo_path") else None} for p in flat]
    return _movie(data, {}, providers)


def discover(params=None, page=1):
    q = {"sort_by": "popularity.desc", "include_adult": "false", "region": REGION, "page": page}
    q.update(params or {})
    return _list("/discover/movie", q)


def recommendations(tmdb_id):
    return _list(f"/movie/{int(tmdb_id)}/recommendations")
