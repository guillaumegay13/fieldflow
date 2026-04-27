"""Browser-based OAuth handlers for the MCP ``OAuthClientProvider``.

Spawns a one-shot loopback HTTP server to capture the authorization-code
redirect, then opens the user's browser at the authorization URL. Used during
``fieldflow mcp add`` and ``fieldflow mcp reauth``.
"""

from __future__ import annotations

import logging
import socket
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Awaitable, Callable, Optional

import anyio
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata

from .config import UpstreamEntry
from .tokens import KeychainTokenStorage

logger = logging.getLogger(__name__)

CALLBACK_PATH = "/callback"
CLIENT_NAME = "FieldFlow MCP Proxy"


class _CallbackServer:
    """Bind a loopback socket up front so we know the redirect URI before
    starting the OAuth flow, then accept exactly one request when the user
    completes the consent screen."""

    def __init__(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        self._sock = sock
        self.port: int = sock.getsockname()[1]
        self._result: Optional[tuple[str, Optional[str]]] = None
        self._error: Optional[str] = None
        self._done = threading.Event()
        self._server: Optional[HTTPServer] = None

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}{CALLBACK_PATH}"

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                logger.debug(fmt, *args)

            def do_GET(self) -> None:  # noqa: N802 - stdlib naming
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != CALLBACK_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return
                params = urllib.parse.parse_qs(parsed.query)
                code = params.get("code", [None])[0]
                state = params.get("state", [None])[0]
                error = params.get("error", [None])[0]
                error_desc = params.get("error_description", [None])[0]
                if error:
                    outer._error = error_desc or error
                    body = (
                        f"<h1>Authorization failed</h1><p>{error}: {error_desc or ''}</p>"
                    )
                    self.send_response(400)
                elif code is None:
                    outer._error = "Missing authorization code in callback"
                    body = "<h1>Authorization failed</h1><p>Missing code.</p>"
                    self.send_response(400)
                else:
                    outer._result = (code, state)
                    body = (
                        "<h1>FieldFlow connected</h1>"
                        "<p>You can close this tab and return to your terminal.</p>"
                    )
                    self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
                outer._done.set()

        return Handler

    def start(self) -> None:
        self._sock.listen(1)
        self._sock.setblocking(True)
        # Hand the bound socket to HTTPServer so we don't race the rebind.
        server = HTTPServer.__new__(HTTPServer)
        BaseHTTPRequestHandler  # ensure import survives lint
        HTTPServer.__init__(
            server,
            ("127.0.0.1", self.port),
            self._make_handler(),
            bind_and_activate=False,
        )
        server.socket = self._sock
        self._server = server
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

    def wait(self, timeout: float) -> tuple[str, Optional[str]]:
        completed = self._done.wait(timeout=timeout)
        try:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
        finally:
            self._sock.close()
        if not completed:
            raise TimeoutError("Timed out waiting for OAuth callback")
        if self._error:
            raise RuntimeError(f"OAuth callback returned error: {self._error}")
        assert self._result is not None
        return self._result


def build_oauth_provider(
    entry: UpstreamEntry,
    *,
    redirect_handler: Callable[[str], Awaitable[None]],
    callback_handler: Callable[[], Awaitable[tuple[str, Optional[str]]]],
    redirect_uri: str,
    scope: Optional[str] = None,
) -> OAuthClientProvider:
    """Build an :class:`OAuthClientProvider` for an HTTP upstream.

    The redirect URI must match what the loopback callback server is bound to
    (see :class:`_CallbackServer`).
    """

    if not entry.url:
        raise ValueError(f"Upstream '{entry.namespace}' has no url")

    metadata = OAuthClientMetadata(
        client_name=CLIENT_NAME,
        redirect_uris=[redirect_uri],  # type: ignore[arg-type]
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope=scope,
    )
    storage = KeychainTokenStorage(entry.namespace)
    return OAuthClientProvider(
        server_url=entry.url,
        client_metadata=metadata,
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


async def interactive_oauth_provider(
    entry: UpstreamEntry,
    *,
    open_browser: bool = True,
    timeout: float = 300.0,
    scope: Optional[str] = None,
) -> tuple[OAuthClientProvider, _CallbackServer]:
    """Wire up an :class:`OAuthClientProvider` for the *interactive* CLI flow:
    binds a loopback callback server, opens the browser, and returns the
    provider plus the server (so the caller can keep the port alive until the
    redirect completes).
    """

    callback = _CallbackServer()
    callback.start()

    async def redirect_handler(authorization_url: str) -> None:
        message = (
            f"\nOpen this URL in your browser to authorize {entry.namespace}:\n"
            f"  {authorization_url}\n"
        )
        if open_browser:
            opened = webbrowser.open(authorization_url, new=1, autoraise=True)
            if not opened:
                print(message, flush=True)
        else:
            print(message, flush=True)

    async def callback_handler() -> tuple[str, Optional[str]]:
        return await anyio.to_thread.run_sync(callback.wait, timeout)

    provider = build_oauth_provider(
        entry,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        redirect_uri=callback.redirect_uri,
        scope=scope,
    )
    return provider, callback


async def runtime_oauth_provider(entry: UpstreamEntry) -> OAuthClientProvider:
    """Provider for the *running* proxy: refresh-only, no browser. If the
    refresh token has been revoked, the upstream will return 401 and we'll
    surface a structured error instructing the user to run ``fieldflow mcp
    reauth``.
    """

    async def redirect_handler(_url: str) -> None:
        raise RuntimeError(
            f"Upstream '{entry.namespace}' requires re-authentication. "
            f"Run: fieldflow mcp reauth {entry.namespace}"
        )

    async def callback_handler() -> tuple[str, Optional[str]]:
        raise RuntimeError(
            f"Upstream '{entry.namespace}' requires re-authentication. "
            f"Run: fieldflow mcp reauth {entry.namespace}"
        )

    return build_oauth_provider(
        entry,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        redirect_uri="http://127.0.0.1:0/callback",  # placeholder; never used
    )
