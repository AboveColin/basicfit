"""
Token management for the Basic-Fit API.

:class:`AuthManager` owns the :class:`~basicfit.models.TokenSet`, keeps a valid
access token available, and refreshes it when needed. Basic-Fit rotates the
refresh token on every refresh, so the new token set is handed back through an
optional ``token_updated`` callback for the caller to persist.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Awaitable, Callable, Optional, Union

import aiohttp

from .constants import (
    AUTH_URL,
    CLIENT_ID,
    DEFAULT_TIMEOUT,
    REDIRECT_URI,
)
from .exceptions import BasicFitAuthError, BasicFitNetworkError
from .models import TokenSet

#: Callback invoked with the fresh :class:`TokenSet` after every rotation. May
#: be a plain function or a coroutine function.
TokenUpdatedCallback = Callable[[TokenSet], Union[None, Awaitable[None]]]


def _decode_jwt_exp(token: str) -> Optional[int]:
    """Return the ``exp`` (epoch seconds) claim of a JWT, or ``None``."""
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        exp = claims.get("exp")
        return int(exp) if isinstance(exp, (int, float)) else None
    except Exception:  # pragma: no cover - defensive
        return None


class AuthManager:
    """Keeps a valid access token, refreshing (and rotating) as needed."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: TokenSet,
        *,
        token_updated: Optional[TokenUpdatedCallback] = None,
        client_id: str = CLIENT_ID,
        redirect_uri: str = REDIRECT_URI,
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._token_updated = token_updated
        self._client_id = tokens.client_id or client_id
        self._redirect_uri = tokens.redirect_uri or redirect_uri
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> TokenSet:
        """The current (possibly just-rotated) token set."""
        return self._tokens

    async def async_get_access_token(self, force_refresh: bool = False) -> str:
        """Return a valid access token, refreshing if expired or forced."""
        async with self._lock:
            tk = self._tokens
            now = time.time()
            if (
                not force_refresh
                and tk.access_token
                and tk.access_expires_at
                and tk.access_expires_at - 60 > now
            ):
                return tk.access_token
            return (await self._refresh_locked()).access_token  # type: ignore[return-value]

    async def async_refresh(self) -> TokenSet:
        """Force a refresh and return the new token set."""
        async with self._lock:
            return await self._refresh_locked()

    async def _refresh_locked(self) -> TokenSet:
        """Perform the refresh grant. Caller must hold ``self._lock``."""
        if not self._tokens.refresh_token:
            raise BasicFitAuthError("no refresh token available")

        body = {
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "refresh_token": self._tokens.refresh_token,
        }
        data = await self._token_request(body)

        new_tokens = TokenSet(
            # Rotate: fall back to the old refresh token if none returned.
            refresh_token=data.get("refresh_token") or self._tokens.refresh_token,
            access_token=data["access_token"],
            access_expires_at=_decode_jwt_exp(data["access_token"]),
            client_id=self._client_id,
            redirect_uri=self._redirect_uri,
            obtained_at=_now_iso(),
        )
        self._tokens = new_tokens
        await self._emit_update(new_tokens)
        return new_tokens

    async def _token_request(self, body: dict) -> dict:
        """POST to the token endpoint and return the parsed JSON body."""
        try:
            async with self._session.post(
                f"{AUTH_URL}/token",
                json=body,
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    data = {}
                if resp.status != 200 or not data.get("access_token"):
                    msg = data.get("message") or text[:120]
                    raise BasicFitAuthError(
                        f"Basic-Fit token request failed ({resp.status}): {msg}. "
                        "You may need to sign in again."
                    )
                return data
        except aiohttp.ClientError as err:
            raise BasicFitNetworkError(f"token request failed: {err}") from err

    async def _emit_update(self, tokens: TokenSet) -> None:
        if self._token_updated is None:
            return
        result = self._token_updated(tokens)
        if asyncio.iscoroutine(result):
            await result

    @classmethod
    async def async_exchange_code(
        cls,
        session: aiohttp.ClientSession,
        code: str,
        code_verifier: str,
        *,
        client_id: str = CLIENT_ID,
        redirect_uri: str = REDIRECT_URI,
    ) -> TokenSet:
        """Exchange a PKCE authorization ``code`` for an initial token set."""
        body = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        }
        # Reuse the request/parse logic without an existing token set.
        manager = cls(session, TokenSet(refresh_token=""), client_id=client_id,
                      redirect_uri=redirect_uri)
        data = await manager._token_request(body)
        if not data.get("refresh_token"):
            raise BasicFitAuthError("authorization code exchange returned no refresh token")
        return TokenSet(
            refresh_token=data["refresh_token"],
            access_token=data["access_token"],
            access_expires_at=_decode_jwt_exp(data["access_token"]),
            client_id=client_id,
            redirect_uri=redirect_uri,
            obtained_at=_now_iso(),
        )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
