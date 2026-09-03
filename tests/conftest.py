"""Shared fixtures for the Basic-Fit client tests.

The library talks to three fixed hosts held in module constants, so the tests
redirect those constants at one loopback server rather than mocking aiohttp.
Mocking libraries for aiohttp lag its releases and break the suite on an
unrelated bump; a real server does not.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from aiohttp import ClientSession, web

from basicfit import AuthManager, BasicFitClient, TokenSet


def make_jwt(exp: int | None = None) -> str:
    """Build a JWT whose only meaningful claim is ``exp``.

    Nothing verifies the signature; the library only base64-decodes the middle
    segment to learn when the access token stops being usable.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    claims = {"exp": exp if exp is not None else int(time.time()) + 3600}
    body = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    )
    return f"{header}.{body}.signature"


class FakeBasicFit:
    """A loopback server standing in for the token, data and Contentful hosts.

    ``requests`` records every request, and ``bodies`` the decoded JSON of each
    POST, so a test can assert on what the client actually sent.
    """

    def __init__(self) -> None:
        self.app = web.Application()
        self.requests: list[web.Request] = []
        self.bodies: list[dict] = []
        self._routes: dict[str, Callable[[web.Request], web.StreamResponse]] = {}
        self.app.router.add_route("*", "/{tail:.*}", self._dispatch)
        self.url = ""

    def handle(self, path: str, handler: Callable[[web.Request], web.StreamResponse]) -> None:
        """Answer ``path`` with ``handler``."""
        self._routes[path] = handler

    def json(self, path: str, payload: object, status: int = 200) -> None:
        """Answer ``path`` with a JSON body."""
        self.handle(path, lambda _r: web.json_response(payload, status=status))

    def text(self, path: str, body: str, status: int = 200) -> None:
        """Answer ``path`` with a plain body, whatever it contains."""
        self.handle(path, lambda _r: web.Response(text=body, status=status))

    def sequence(self, path: str, *responses: object) -> None:
        """Answer ``path`` with each response in turn, repeating the last."""
        remaining = list(responses)

        def handler(_request: web.Request) -> web.StreamResponse:
            item = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            status, payload = item if isinstance(item, tuple) else (200, item)
            return web.json_response(payload, status=status)

        self.handle(path, handler)

    async def _dispatch(self, request: web.Request) -> web.StreamResponse:
        self.requests.append(request)
        if request.method == "POST":
            try:
                self.bodies.append(await request.json())
            except Exception:  # noqa: BLE001  a non-JSON body is a valid case
                self.bodies.append({})
        handler = self._routes.get(request.path)
        if handler is None:
            return web.Response(status=404, text="{}")
        result = handler(request)
        return await result if hasattr(result, "__await__") else result


@pytest_asyncio.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeBasicFit]:
    """A running fake, with every hard-coded host pointed at it."""
    fake = FakeBasicFit()
    runner = web.AppRunner(fake.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    fake.url = f"http://127.0.0.1:{runner.addresses[0][1]}"

    monkeypatch.setattr("basicfit.auth.AUTH_URL", fake.url)
    monkeypatch.setattr("basicfit.client.API_BASE", f"{fake.url}/api")
    monkeypatch.setattr("basicfit.client.CONTENTFUL_URL", f"{fake.url}/graphql")
    try:
        yield fake
    finally:
        await runner.cleanup()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[ClientSession]:
    """A session the test owns, so client.close() must leave it open."""
    async with ClientSession() as open_session:
        yield open_session


@pytest.fixture(name="tokens")
def fixture_tokens() -> TokenSet:
    """A token set whose access token is still valid for an hour."""
    return TokenSet(refresh_token="refresh-1", access_token=make_jwt(), access_expires_at=int(time.time()) + 3600)


@pytest_asyncio.fixture
async def client(
    api: FakeBasicFit, session: ClientSession, tokens: TokenSet
) -> AsyncIterator[BasicFitClient]:
    """A client with a valid access token, so no refresh happens by accident."""
    auth = AuthManager(session, tokens)
    instance = BasicFitClient(auth, session)
    yield instance
    await instance.close()
