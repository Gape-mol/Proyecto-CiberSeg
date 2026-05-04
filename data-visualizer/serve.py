#!/usr/bin/env python3
"""
Servidor local para el visualizer.
Sirve el HTML desde este directorio y el dataset desde DATA_ROOT.

Uso dentro del container:
    python /workspace/data-visualizer/serve.py

En el host (si tenés el JSON en otra ruta):
    DATA_ROOT=/ruta/al/data python serve.py
"""
import http.server
import os
import urllib.parse
from pathlib import Path

PORT      = int(os.environ.get("PORT", 4173))
_default_data = Path("/data") if Path("/data/secpipeline.json").exists() else Path("/workspace/data")
DATA_ROOT = Path(os.environ.get("DATA_ROOT", str(_default_data)))
SERVE_DIR = Path(__file__).parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def do_GET(self):
        # Peticiones a /data/... → servir desde DATA_ROOT
        parsed = urllib.parse.urlparse(self.path)
        clean  = parsed.path.split("?")[0]

        if clean.startswith("/data/"):
            rel      = clean[len("/data/"):]
            filepath = DATA_ROOT / rel
            if filepath.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(filepath.stat().st_size))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(filepath.read_bytes())
            else:
                self.send_error(404, f"Not found: {filepath}")
            return

        super().do_GET()

    def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        if args and "GET /data/" in str(args[0]):
            return
        super().log_message(fmt, *args)


if __name__ == "__main__":
    os.chdir(SERVE_DIR)
    print(f"Visualizer → http://localhost:{PORT}")
    print(f"Dataset    → {DATA_ROOT}/secpipeline.json")
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
