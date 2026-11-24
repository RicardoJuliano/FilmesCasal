import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _core import routes  # noqa: E402

MAX_BODY = 256 * 1024


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Code, X-Token")

    def _send(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _handle(self):
        try:
            parts = urlsplit(self.path)
            path = parts.path
            if path.startswith("/api"):
                path = path[4:]
            query = dict(parse_qsl(parts.query))
            if "path" in query:  # vercel.json reescreve /api/X para /api/index?path=X
                path = "/" + query.pop("path")
            body = None
            if self.command in ("POST", "PUT"):
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, {"error": "Corpo da requisição grande demais."})
                raw = self.rfile.read(length) if length else b""
                if raw.strip():
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        return self._send(400, {"error": "JSON inválido."})
                else:
                    body = {}
            status, payload = routes.dispatch(self.command, path, query, self.headers, body)
        except Exception as exc:
            status, payload = 500, {"error": f"Erro interno: {exc}"}
        self._send(status, payload)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()
