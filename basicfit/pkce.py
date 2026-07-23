"""
PKCE helpers for the one-time browser login.

Basic-Fit's login page (``login.basic-fit.com``) is protected by an Imperva
browser challenge, so it cannot be completed headlessly. The supported flow is:

1. Generate a PKCE verifier/challenge and a random ``state``/``nonce`` and build
   the authorize URL with :func:`build_authorize_url`.
2. The user opens that URL in a normal browser and signs in. The browser then
   redirects to ``com.basicfit.trainingapp:/oauthredirect?code=...&state=...``.
   The custom scheme won't open an app on a desktop, but the URL is visible in
   the address bar and can be copied.
3. Feed that redirect URL (or the bare ``code``) to :func:`parse_redirect` and
   exchange it with :meth:`basicfit.auth.AuthManager.async_exchange_code`.

The verifier must be kept between steps 1 and 3.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import NamedTuple
from urllib.parse import parse_qs, urlencode, urlparse

from .constants import CLIENT_ID, LOGIN_URL, REDIRECT_URI
from .exceptions import BasicFitValidationError


def _b64url(raw: bytes) -> str:
    """Base64-url encode without padding."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_code_verifier(length: int = 64) -> str:
    """Return a high-entropy PKCE code verifier (43-128 url-safe chars)."""
    if not 43 <= length <= 128:
        raise BasicFitValidationError("code verifier length must be 43-128")
    return _b64url(os.urandom(96))[:length]


def code_challenge_for(verifier: str) -> str:
    """Return the S256 code challenge for ``verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def random_state(nbytes: int = 24) -> str:
    """Return a random, url-safe opaque token (for ``state``/``nonce``)."""
    return secrets.token_urlsafe(nbytes)


class PkceChallenge(NamedTuple):
    """A generated PKCE + state/nonce bundle and its authorize URL."""

    verifier: str
    challenge: str
    state: str
    nonce: str
    authorize_url: str


def build_authorize_url(
    challenge: str,
    state: str,
    nonce: str,
    *,
    client_id: str = CLIENT_ID,
    redirect_uri: str = REDIRECT_URI,
) -> str:
    """Build the Basic-Fit login URL for a PKCE authorization-code request."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "app": "true",
        "auto_login": "false",
    }
    return f"{LOGIN_URL}?{urlencode(params)}"


def start_login(
    *, client_id: str = CLIENT_ID, redirect_uri: str = REDIRECT_URI
) -> PkceChallenge:
    """Generate a full PKCE bundle ready to present to the user."""
    verifier = generate_code_verifier()
    challenge = code_challenge_for(verifier)
    state = random_state()
    nonce = random_state()
    url = build_authorize_url(
        challenge, state, nonce, client_id=client_id, redirect_uri=redirect_uri
    )
    return PkceChallenge(verifier, challenge, state, nonce, url)


def parse_redirect(value: str, *, expected_state: str | None = None) -> str:
    """Extract the authorization ``code`` from a redirect URL or bare code.

    Accepts either the full ``com.basicfit.trainingapp:/oauthredirect?code=...``
    URL that the browser lands on, or just the ``code`` value pasted by hand.

    Raises :class:`BasicFitValidationError` if no code is present, or if
    ``expected_state`` is given and does not match the returned ``state``.
    """
    value = (value or "").strip()
    if not value:
        raise BasicFitValidationError("empty redirect value")

    code: str | None = None
    if "code=" in value or "?" in value or "://" in value or value.startswith(
        "com.basicfit"
    ):
        # urlparse handles the custom scheme; query lives after '?'.
        query = urlparse(value).query or value.split("?", 1)[-1]
        params = parse_qs(query)
        if expected_state is not None:
            got = (params.get("state") or [None])[0]
            if got is not None and got != expected_state:
                raise BasicFitValidationError("state mismatch in redirect")
        code = (params.get("code") or [None])[0]
    else:
        # Treat the whole thing as a bare code.
        code = value

    if not code:
        raise BasicFitValidationError("no authorization code found in input")
    return code
