"""Rotas da API. `dispatch` é independente de HTTP para facilitar os testes."""
import hmac
from datetime import datetime, timezone

from . import storage

try:  # módulos do Tucano; podem não existir ainda
    from . import tmdb
except ImportError:  # pragma: no cover
    tmdb = None
try:
    from . import recommender
except ImportError:  # pragma: no cover
    recommender = None

HUMORES = {"rir", "chorar", "tensao", "pensar", "aventura", "romance", "medo"}
EPOCAS = {"classicos", "80_90", "2000_2010", "recentes"}
IDIOMAS = {"pt", "en", "es", "outros"}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _tmdb_error():
    return getattr(tmdb, "TMDBError", None) if tmdb else None


# ---------- validação ----------

def _name(body):
    name = str(body.get("name") or "").strip()
    if not name or len(name) > 40:
        raise ApiError(400, "Informe um nome com até 40 caracteres.")
    return name


def _int(value, label="tmdb_id"):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ApiError(400, f"{label} inválido.")
    try:
        return int(value)
    except ValueError:
        raise ApiError(400, f"{label} inválido.")


def _int_list(value, label, max_len=None):
    if not isinstance(value, list):
        raise ApiError(400, f"{label} deve ser uma lista.")
    out = []
    for v in value:
        n = _int(v, label)
        if n not in out:
            out.append(n)
    if max_len and len(out) > max_len:
        raise ApiError(400, f"{label}: no máximo {max_len} itens.")
    return out


def _str_list(value, label, allowed):
    if not isinstance(value, list):
        raise ApiError(400, f"{label} deve ser uma lista.")
    out = []
    for v in value:
        if v not in allowed:
            raise ApiError(400, f"{label}: valor inválido '{v}'.")
        if v not in out:
            out.append(v)
    return out


def validate_quiz(body):
    if not isinstance(body, dict):
        raise ApiError(400, "Questionário inválido.")
    duracao = body.get("duracao_max")
    if duracao is not None:
        duracao = _int(duracao, "duracao_max")
        if duracao <= 0:
            raise ApiError(400, "duracao_max deve ser positiva ou nulo.")
    nota = body.get("nota_min", 5.0)
    try:
        if isinstance(nota, bool):
            raise ValueError
        nota = float(nota)
    except (TypeError, ValueError):
        raise ApiError(400, "nota_min inválida.")
    if not 5.0 <= nota <= 8.0:
        raise ApiError(400, "nota_min deve estar entre 5.0 e 8.0.")
    amo = _int_list(body.get("generos_amo", []), "generos_amo", 5)
    veto = _int_list(body.get("generos_veto", []), "generos_veto")
    return {
        "generos_amo": amo,
        "generos_veto": veto,
        "humores": _str_list(body.get("humores", []), "humores", HUMORES),
        "epocas": _str_list(body.get("epocas", []), "epocas", EPOCAS),
        "duracao_max": duracao,
        "idiomas": _str_list(body.get("idiomas", []), "idiomas", IDIOMAS),
        "streamings": _int_list(body.get("streamings", []), "streamings"),
        "nota_min": nota,
    }


# ---------- helpers ----------

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_tmdb():
    if tmdb is None:
        raise ApiError(503, "Serviço de filmes indisponível.")
    return tmdb


def _tmdb_call(fn, *args):
    mod = _require_tmdb()
    try:
        return getattr(mod, fn)(*args)
    except Exception as exc:
        if _tmdb_error() and isinstance(exc, _tmdb_error()):
            raise ApiError(502, f"Erro ao consultar o TMDB: {exc}")
        raise


def _auth(headers):
    code = (headers.get("X-Code") or "").strip().upper()
    token = headers.get("X-Token") or ""
    if not code or not token:
        raise ApiError(401, "Credenciais ausentes.")
    couple = storage.get_couple(code)
    if couple is None:
        raise ApiError(404, "Casal não encontrado.")
    for member_id, m in couple["members"].items():
        if hmac.compare_digest(str(m.get("token", "")), token):
            return couple, member_id
    raise ApiError(401, "Token inválido.")


def _public_member(member_id, m):
    return {
        "id": member_id,
        "name": m["name"],
        "quiz_done": m.get("quiz") is not None,
        "ratings_count": len(m.get("ratings", {})),
    }


def _changed(couple):
    """Persiste o casal e invalida o cache de recomendações."""
    storage.save_couple(couple)
    storage.invalidate_recs(couple["code"])


def _new_member(name):
    return {"name": name, "token": storage.new_token(), "quiz": None, "ratings": {}}


# ---------- handlers ----------

def create_couple(ctx):
    name = _name(ctx["body"])
    with storage.lock:
        code = storage.new_code()
        member_id = storage.new_member_id()
        member = _new_member(name)
        storage.save_couple({
            "code": code, "created_at": _now(),
            "members": {member_id: member}, "watchlist": {}, "dismissed": [],
        })
    return 201, {"code": code, "member_id": member_id, "token": member["token"]}


def join_couple(ctx):
    body = ctx["body"]
    name = _name(body)
    code = str(body.get("code") or "").strip().upper()
    if not code:
        raise ApiError(400, "Informe o código do casal.")
    with storage.lock:
        couple = storage.get_couple(code)
        if couple is None:
            raise ApiError(404, "Casal não encontrado.")
        if len(couple["members"]) >= 2:
            raise ApiError(409, "Este casal já está completo.")
        member_id = storage.new_member_id()
        member = _new_member(name)
        couple["members"][member_id] = member
        _changed(couple)
    return 200, {"code": code, "member_id": member_id, "token": member["token"]}


def get_couple(ctx):
    couple, me = _auth(ctx["headers"])
    return 200, {
        "code": couple["code"], "me": me,
        "members": [_public_member(i, m) for i, m in couple["members"].items()],
    }


def get_options(ctx):
    return 200, _tmdb_call("get_options")


def get_quiz(ctx):
    couple, me = _auth(ctx["headers"])
    return 200, {"quiz": couple["members"][me].get("quiz")}


def put_quiz(ctx):
    _auth(ctx["headers"])
    quiz = validate_quiz(ctx["body"])
    with storage.lock:
        couple, me = _auth(ctx["headers"])
        couple["members"][me]["quiz"] = quiz
        _changed(couple)
    return 200, {"ok": True}


def get_seed(ctx):
    _auth(ctx["headers"])
    return 200, {"movies": _tmdb_call("seed_movies")}


def search(ctx):
    _auth(ctx["headers"])
    q = (ctx["query"].get("q") or "").strip()
    if not q:
        raise ApiError(400, "Informe um termo de busca.")
    return 200, {"movies": list(_tmdb_call("search", q))[:10]}


def post_rating(ctx):
    _auth(ctx["headers"])
    body = ctx["body"]
    tmdb_id = _int(body.get("tmdb_id"))
    rating = _int(body.get("rating"), "rating")
    if not 0 <= rating <= 5:
        raise ApiError(400, "rating deve ser de 0 a 5.")
    with storage.lock:
        couple, me = _auth(ctx["headers"])
        ratings = couple["members"][me].setdefault("ratings", {})
        if rating == 0:
            ratings.pop(str(tmdb_id), None)
        else:
            ratings[str(tmdb_id)] = rating
        _changed(couple)
    return 200, {"ok": True}


def get_recommendations(ctx):
    couple, _ = _auth(ctx["headers"])
    refresh = ctx["query"].get("refresh") == "1"
    members = couple["members"]
    waiting = [m["name"] for m in members.values() if m.get("quiz") is None]
    if len(members) < 2:
        waiting.append("seu par")
    if waiting:
        return 200, {"ready": False, "waiting_for": waiting, "movies": []}
    if not refresh:
        cached = storage.get_recs(couple["code"])
        if cached is not None:
            return 200, cached
    if recommender is None:
        raise ApiError(503, "Serviço de recomendações indisponível.")
    try:
        movies = recommender.recommend(couple, 20)
    except Exception as exc:
        if _tmdb_error() and isinstance(exc, _tmdb_error()):
            raise ApiError(502, f"Erro ao consultar o TMDB: {exc}")
        raise
    result = {"ready": True, "waiting_for": [], "movies": movies}
    storage.save_recs(couple["code"], result)
    return 200, result


def get_watchlist(ctx):
    couple, _ = _auth(ctx["headers"])
    items = []
    for key, item in couple.get("watchlist", {}).items():
        ratings = {mid: m["ratings"][key] for mid, m in couple["members"].items()
                   if key in m.get("ratings", {})}
        items.append({**item, "ratings": ratings})
    return 200, {"items": items}


def post_watchlist(ctx):
    _auth(ctx["headers"])
    body = ctx["body"]
    tmdb_id = _int(body.get("tmdb_id"))
    action = body.get("action")
    if action not in ("add", "remove", "watched"):
        raise ApiError(400, "action deve ser add, remove ou watched.")
    key = str(tmdb_id)
    with storage.lock:
        couple, me = _auth(ctx["headers"])
        wl = couple.setdefault("watchlist", {})
        if action == "remove":
            wl.pop(key, None)
        else:
            if key not in wl:
                movie = _tmdb_call("movie", tmdb_id)
                wl[key] = {**movie, "status": "quero_ver", "added_by": me, "ratings": {}}
            if action == "watched":
                wl[key]["status"] = "assistido"
            elif wl[key].get("status") != "assistido":
                wl[key]["status"] = "quero_ver"
        _changed(couple)
    return 200, {"ok": True}


def post_dismiss(ctx):
    _auth(ctx["headers"])
    tmdb_id = _int(ctx["body"].get("tmdb_id"))
    with storage.lock:
        couple, _ = _auth(ctx["headers"])
        dismissed = couple.setdefault("dismissed", [])
        if tmdb_id not in dismissed:
            dismissed.append(tmdb_id)
        _changed(couple)
    return 200, {"ok": True}


ROUTES = {
    ("POST", "/couple"): create_couple,
    ("POST", "/couple/join"): join_couple,
    ("GET", "/couple"): get_couple,
    ("GET", "/options"): get_options,
    ("GET", "/quiz"): get_quiz,
    ("PUT", "/quiz"): put_quiz,
    ("GET", "/seed"): get_seed,
    ("GET", "/search"): search,
    ("POST", "/rating"): post_rating,
    ("GET", "/recommendations"): get_recommendations,
    ("GET", "/watchlist"): get_watchlist,
    ("POST", "/watchlist"): post_watchlist,
    ("POST", "/dismiss"): post_dismiss,
}


def dispatch(method, path, query, headers, body):
    """Retorna (status, dict). `path` sem o prefixo /api; `query` dict str->str."""
    try:
        path = "/" + path.strip("/")
        fn = ROUTES.get((method, path))
        if fn is None:
            if any(p == path for _, p in ROUTES):
                raise ApiError(405, "Método não permitido.")
            raise ApiError(404, "Rota não encontrada.")
        if method in ("POST", "PUT") and not isinstance(body, dict):
            raise ApiError(400, "Corpo da requisição deve ser um objeto JSON.")
        return fn({"query": query, "headers": headers, "body": body or {}})
    except ApiError as e:
        return e.status, {"error": e.message}
    except storage.StorageError as e:
        return 503, {"error": str(e)}
    except Exception as e:  # nunca derruba o servidor
        return 500, {"error": f"Erro interno: {e}"}
