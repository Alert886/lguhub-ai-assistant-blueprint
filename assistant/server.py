"""Local-only demo server; deliberately not a production auth/payment service."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from .engine import Engine
from .pipeline import build, PACK

WEB = Path(__file__).resolve().parents[1] / "web"


def handler_for(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if self.path == "/api/health":
                return self.respond(200, {"ok": True, "records": len(engine.records), "data": "synthetic"})
            if self.path not in files:
                return self.respond(404, {"error": "not_found"})
            path = WEB / files[self.path]
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[path.suffix] + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/api/assistant/query":
                return self.respond(404, {"error": "not_found"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.respond(415, {"error": "JSON required"})
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return self.respond(403, {"error": "origin_rejected"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    return self.respond(413, {"error": "request_size"})
                payload = json.loads(self.rfile.read(length))
                return self.respond(200, engine.ask(payload))
            except (ValueError, TypeError):
                return self.respond(400, {"error": "invalid_request"})
            except Exception:
                return self.respond(500, {"error": "internal_error"})
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--vectors", action="store_true")
    args = parser.parse_args()
    if not PACK.exists():
        build()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(Engine(vectors=args.vectors)))
    print(f"Local synthetic demo: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
