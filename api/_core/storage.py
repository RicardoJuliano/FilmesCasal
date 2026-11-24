"""Armazenamento: Redis REST do Upstash (produção) ou arquivo JSON (local)."""
import json
import os
import secrets
import threading
import urllib.request
from pathlib import Path

# Evita 0/O e 1/I/L (ambíguos).
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6

# Serializa leitura-modificação-escrita dentro do processo.
lock = threading.RLock()

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "dev-db.json"


class StorageError(Exception):
    pass


def _redis_conf():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return url.rstrip("/"), token
    return None


def _redis(*command):
    url, token = _redis_conf()
    req = urllib.request.Request(
        url,
        data=json.dumps(list(command)).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise StorageError(f"Falha ao acessar o armazenamento: {exc}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise StorageError(f"Erro do armazenamento: {payload['error']}")
    return payload.get("result") if isinstance(payload, dict) else None


def _file_read():
    try:
        return json.loads(_DB_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise StorageError(f"Arquivo de dados ilegível: {exc}") from exc


def _file_write(db):
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _DB_PATH)


def get(key):
    if _redis_conf():
        raw = _redis("GET", key)
        return json.loads(raw) if raw else None
    with lock:
        return _file_read().get(key)


def set(key, value):  # noqa: A001 - nome pedido pelo contrato interno
    if _redis_conf():
        _redis("SET", key, json.dumps(value, ensure_ascii=False))
        return
    with lock:
        db = _file_read()
        db[key] = value
        _file_write(db)


def delete(key):
    if _redis_conf():
        _redis("DEL", key)
        return
    with lock:
        db = _file_read()
        if key in db:
            del db[key]
            _file_write(db)


def get_couple(code):
    return get(f"couple:{code}")


def save_couple(couple):
    set(f"couple:{couple['code']}", couple)


def get_recs(code):
    return get(f"recs:{code}")


def save_recs(code, data):
    set(f"recs:{code}", data)


def invalidate_recs(code):
    delete(f"recs:{code}")


def new_code():
    """Gera um code de 6 caracteres que ainda não existe."""
    for _ in range(50):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if get_couple(code) is None:
            return code
    raise StorageError("Não foi possível gerar um código único.")


def new_token():
    return secrets.token_urlsafe(24)


def new_member_id():
    return secrets.token_hex(4)
