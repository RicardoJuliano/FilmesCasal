"""Servidor local: serve public/ e /api/* em http://localhost:8000."""
import mimetypes
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"


def load_env():
    env = ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
sys.path.insert(0, str(ROOT / "api"))
from index import handler as ApiHandler  # noqa: E402


class DevHandler(ApiHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api"):
            return self._handle()
        rel = unquote(path).lstrip("/") or "index.html"
        target = (PUBLIC / rel).resolve()
        if PUBLIC.resolve() not in target.parents and target != PUBLIC.resolve():
            return self._static_error(403)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            target = PUBLIC / "index.html"  # fallback SPA
            if not target.is_file():
                return self._static_error(404)
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _static_error(self, status):
        msg = b"Not found" if status == 404 else b"Forbidden"
        self.send_response(status)
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), DevHandler)
    print(f"Filmes a Dois em http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
