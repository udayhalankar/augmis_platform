"""Development-only companion relay. Binds 18080 inside a dedicated container.

No credentials or signing keys. Windows Docker loopback is the only published
listener, and the dashboard independently validates gateway assertions.
"""
from __future__ import annotations
import http.client
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ALLOWED = frozenset({"/", "/app.js", "/app.css", "/healthz", "/api/dashboard"})
MAX_RESPONSE = 1_048_576
TARGET_RE = re.compile(r"augmis-[a-z0-9][a-z0-9-]{0,160}\Z")


def validate_target(target):
    if not isinstance(target, str) or not TARGET_RE.fullmatch(target):
        raise ValueError("Invalid approved dashboard upstream")
    return target


def create_handler(target):
    validate_target(target)
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "AugmisDevIngress/0.1"
        def log_message(self, fmt, *args):
            return  # No paths, assertions, cookies or credentials in logs.
        def reply(self, status, data=b"", content_type="text/plain"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            if data:
                self.wfile.write(data)
            self.close_connection = True
        def do_GET(self):
            url = urlsplit(self.path)
            if (url.scheme or url.netloc or url.query or url.fragment
                    or url.path not in ALLOWED):
                return self.reply(404, b"Not found")
            values = self.headers.get_all("X-Augmis-Runtime-Assertion", [])
            if len(values) > 1 or (values and (not values[0] or len(values[0]) > 8192)):
                return self.reply(400, b"Invalid request")
            headers = {"Accept-Encoding": "identity"}
            if values:
                headers["X-Augmis-Runtime-Assertion"] = values[0]
            try:
                connection = http.client.HTTPConnection(target, 8080, timeout=5)
                try:
                    connection.request("GET", url.path, headers=headers)
                    upstream = connection.getresponse()
                    data = upstream.read(MAX_RESPONSE + 1)
                    if len(data) > MAX_RESPONSE:
                        return self.reply(502, b"Upstream response too large")
                    content = upstream.getheader("Content-Type", "application/octet-stream")
                    # Do not reflect arbitrary headers from a container.
                    if "\r" in content or "\n" in content:
                        return self.reply(502, b"Invalid upstream response")
                    return self.reply(upstream.status, data, content)
                finally:
                    connection.close()
            except (OSError, http.client.HTTPException, TimeoutError):
                return self.reply(502, b"Upstream unavailable")
        def do_POST(self): self.reply(405, b"Method not allowed")
        def do_PUT(self): self.reply(405, b"Method not allowed")
        def do_PATCH(self): self.reply(405, b"Method not allowed")
        def do_DELETE(self): self.reply(405, b"Method not allowed")
        def do_HEAD(self): self.reply(405, b"Method not allowed")
        def do_OPTIONS(self): self.reply(405, b"Method not allowed")
    return Handler


def main():
    target = validate_target(os.environ.get("AUGMIS_RELAY_UPSTREAM", ""))
    ThreadingHTTPServer(("0.0.0.0", 18080), create_handler(target)).serve_forever()

if __name__ == "__main__": main()
