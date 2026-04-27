"""OS keychain-backed implementation of the MCP SDK ``TokenStorage`` protocol.

Tokens and DCR client info are stored as JSON blobs under the ``fieldflow-mcp``
keychain service, keyed by ``{namespace}:{kind}``. Falls back to a 0600 file at
``~/.config/fieldflow/secrets/{namespace}.json`` when the OS keyring is
unavailable (CI, headless servers).
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, Optional

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .config import default_config_path

logger = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "fieldflow-mcp"


def _secrets_dir() -> Path:
    return default_config_path().parent / "secrets"


def _fallback_path(namespace: str) -> Path:
    return _secrets_dir() / f"{namespace}.json"


class _Backend:
    """Tiny abstraction so we can swap keyring for a file fallback."""

    def get(self, namespace: str, kind: str) -> Optional[str]:
        raise NotImplementedError

    def set(self, namespace: str, kind: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, namespace: str, kind: str) -> None:
        raise NotImplementedError


class _KeyringBackend(_Backend):
    def __init__(self) -> None:
        import keyring  # imported lazily so the package stays optional

        self._keyring = keyring

    def _key(self, namespace: str, kind: str) -> str:
        return f"{namespace}:{kind}"

    def get(self, namespace: str, kind: str) -> Optional[str]:
        return self._keyring.get_password(KEYCHAIN_SERVICE, self._key(namespace, kind))

    def set(self, namespace: str, kind: str, value: str) -> None:
        self._keyring.set_password(KEYCHAIN_SERVICE, self._key(namespace, kind), value)

    def delete(self, namespace: str, kind: str) -> None:
        try:
            self._keyring.delete_password(KEYCHAIN_SERVICE, self._key(namespace, kind))
        except Exception:
            pass


class _FileBackend(_Backend):
    def _read(self, namespace: str) -> dict[str, Any]:
        path = _fallback_path(namespace)
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def _write(self, namespace: str, data: dict[str, Any]) -> None:
        path = _fallback_path(namespace)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def get(self, namespace: str, kind: str) -> Optional[str]:
        return self._read(namespace).get(kind)

    def set(self, namespace: str, kind: str, value: str) -> None:
        data = self._read(namespace)
        data[kind] = value
        self._write(namespace, data)

    def delete(self, namespace: str, kind: str) -> None:
        data = self._read(namespace)
        data.pop(kind, None)
        self._write(namespace, data)


def _build_backend() -> _Backend:
    if os.environ.get("FIELDFLOW_TOKEN_STORE") == "file":
        return _FileBackend()
    try:
        backend = _KeyringBackend()
        # Probe the keyring to surface missing-backend errors early.
        backend._keyring.get_keyring()
        return backend
    except Exception as exc:  # pragma: no cover - exercised only without keyring
        logger.warning("OS keychain unavailable (%s); falling back to file store", exc)
        return _FileBackend()


_BACKEND: Optional[_Backend] = None


def _backend() -> _Backend:
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _build_backend()
    return _BACKEND


class KeychainTokenStorage(TokenStorage):
    """Per-upstream MCP ``TokenStorage`` backed by the OS keychain."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace

    async def get_tokens(self) -> Optional[OAuthToken]:
        raw = _backend().get(self.namespace, "tokens")
        if raw is None:
            return None
        return OAuthToken.model_validate_json(raw)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        _backend().set(self.namespace, "tokens", tokens.model_dump_json())

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        raw = _backend().get(self.namespace, "client_info")
        if raw is None:
            return None
        return OAuthClientInformationFull.model_validate_json(raw)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        _backend().set(
            self.namespace, "client_info", client_info.model_dump_json()
        )

    def clear(self) -> None:
        backend = _backend()
        backend.delete(self.namespace, "tokens")
        backend.delete(self.namespace, "client_info")
