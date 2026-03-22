"""
Singleton localhost HTTP server for the analytical map HTML document.

Serves only 127.0.0.1 so tile subrequests get a normal http Referer (OSM policy).
Process lifetime: one listener thread; HTML buffer swapped on refresh (thread-safe).
"""

from __future__ import annotations

import atexit
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

_server: Optional[HTTPServer] = None
_server_thread: Optional[threading.Thread] = None
_port: int = 0
_init_lock = threading.Lock()
_shutdown_registered = False


class _MapDocHandler(BaseHTTPRequestHandler):
    _html_bytes = b""
    _lock = threading.Lock()

    @classmethod
    def set_html(cls, html: str) -> None:
        data = html.encode("utf-8")
        with cls._lock:
            cls._html_bytes = data

    def do_GET(self) -> None:
        if self.path not in ("/map.html", "/"):
            self.send_error(404)
            return
        with self._lock:
            body = bytes(self._html_bytes)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def ensure_map_document_server() -> str:
    """
    Start singleton server on first use. Returns URL to map.html (http://127.0.0.1:PORT/map.html).
    """
    global _server, _server_thread, _port, _shutdown_registered
    with _init_lock:
        if _server is not None:
            return f"http://127.0.0.1:{_port}/map.html"
        _server = HTTPServer(("127.0.0.1", 0), _MapDocHandler)
        _port = int(_server.server_address[1])
        _server_thread = threading.Thread(target=_server.serve_forever, name="MapDocumentHTTPServer", daemon=True)
        _server_thread.start()
        if not _shutdown_registered:
            atexit.register(_shutdown_server)
            _shutdown_registered = True
        return f"http://127.0.0.1:{_port}/map.html"


def set_map_document_html(html: str) -> None:
    """Update the served HTML (UTF-8). Thread-safe."""
    ensure_map_document_server()
    _MapDocHandler.set_html(html)


def map_document_server_url() -> str:
    """Return base URL for map document (starts server if needed)."""
    return ensure_map_document_server()


def _shutdown_server() -> None:
    global _server
    srv = _server
    if srv is None:
        return
    try:
        srv.shutdown()
    except Exception:
        pass
    try:
        srv.server_close()
    except Exception:
        pass
    _server = None
