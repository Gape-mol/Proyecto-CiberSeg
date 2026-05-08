#!/usr/bin/env python3
"""
Servidor local para el visualizer.
Sirve el HTML desde este directorio y el dataset desde DATA_ROOT.

Optimizaciones:
  - ThreadingHTTPServer: atiende múltiples conexiones en paralelo.
  - ETag basado en mtime: responde 304 Not Modified cuando el archivo
    no cambió, evitando transferir el JSON completo en cada poll.
  - Gzip automático: comprime respuestas cuando el cliente lo soporta.

Uso dentro del container:
    python /workspace/data-visualizer/serve.py

En el host:
    DATA_ROOT=/ruta/al/data python serve.py
"""
import gzip
import http.server
import os
import urllib.parse
from pathlib import Path
from socketserver import ThreadingMixIn

PORT      = int(os.environ.get("PORT", 4173))
_default  = Path("/data") if Path("/data/secpipeline.json").exists() else Path("/workspace/data")
DATA_ROOT = Path(os.environ.get("DATA_ROOT", str(_default)))
SERVE_DIR = Path(__file__).parent


class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        clean  = parsed.path.split("?")[0]

        if clean.startswith("/data/"):
            self._serve_data(clean[len("/data/"):])
            return

        super().do_GET()

    def _serve_data(self, rel: str) -> None:
        filepath = DATA_ROOT / rel
        if not filepath.exists():
            self.send_error(404, f"Not found: {filepath}")
            return

        stat = filepath.stat()
        etag = f'"{int(stat.st_mtime * 1000)}"'

        # 304 Not Modified — el cliente ya tiene la versión actual
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return

        data = filepath.read_bytes()

        # Comprimir si el cliente acepta gzip
        accept_enc = self.headers.get("Accept-Encoding", "")
        use_gzip   = "gzip" in accept_enc

        if use_gzip:
            body = gzip.compress(data, compresslevel=1)  # nivel 1 = rápido
        else:
            body = data

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        self.send_header("Access-Control-Allow-Origin", "*")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        # Silenciar polling frecuente de /data/
        if args and "GET /data/" in str(args[0]):
            return
        super().log_message(fmt, *args)


if __name__ == "__main__":
    os.chdir(SERVE_DIR)
    print(f"Visualizer → http://localhost:{PORT}")
    print(f"Dataset    → {DATA_ROOT}/secpipeline.json")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
