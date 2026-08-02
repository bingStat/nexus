#!/usr/bin/env python3
from __future__ import annotations

import http.server
import socket
import urllib.error
import urllib.request

UPSTREAMS = (
    ("http://100.116.89.65:19082", 8, True),
    ("https://iyqzgmzlykufsbtmykpw.supabase.co", 12, False),
)
DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DEFAULT_OPENER = urllib.request.build_opener()
FORWARD_HEADERS = {
    "authorization", "apikey", "content-type", "prefer",
    "range", "accept", "if-match", "if-none-match",
}
RESPONSE_HEADERS = {
    "content-type", "content-range", "range-unit",
    "preference-applied", "location", "etag",
}

class Relay(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        super().log_message(fmt, *args)

    def _request_upstream(self, base: str, timeout: int, direct: bool, body: bytes | None, headers: dict):
        request = urllib.request.Request(base + self.path, data=body, headers=headers, method=self.command)
        opener = DIRECT_OPENER if direct else DEFAULT_OPENER
        try:
            return opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            return exc

    def _handle(self) -> None:
        length = int(self.headers.get("content-length", "0") or 0)
        body = self.rfile.read(length) if length else None
        headers = {key: value for key, value in self.headers.items() if key.lower() in FORWARD_HEADERS}
        response = None
        errors = []
        for base, timeout, direct in UPSTREAMS:
            try:
                response = self._request_upstream(base, timeout, direct, body, headers)
                break
            except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
                errors.append(f"{base}:{type(exc).__name__}")
        if response is None:
            payload = ("relay upstream unavailable: " + ",".join(errors)).encode()
            self.send_response(502)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(payload)))
            self.send_header("connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            return
        payload = response.read()
        self.send_response(int(response.status))
        for key, value in response.headers.items():
            if key.lower() in RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle
    do_PUT = _handle
    do_DELETE = _handle
    do_HEAD = _handle
    do_OPTIONS = _handle

if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("100.103.12.14", 19080), Relay).serve_forever()
