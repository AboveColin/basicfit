"""Tests for token handling.

Basic-Fit rotates the refresh token on every refresh, so a caller that fails to
persist the new one is locked out. The rotation and the callback that carries it
back are therefore the important cases here.
"""

from __future__ import annotations

import time

import pytest

from basicfit import AuthManager, BasicFitAuthError, BasicFitClient, TokenSet
from basicfit.auth import _decode_jwt_exp

from .conftest import FakeBasicFit, make_jwt

TOKEN = "/token"


class TestJwtExpiry:
    """The access token's lifetime is read out of the JWT itself."""

    def test_reads_the_exp_claim(self) -> None:
        assert _decode_jwt_exp(make_jwt(exp=1800000000)) == 1800000000

    def test_a_token_without_an_exp_claim_yields_none(self) -> None:
        import base64
        import json

        body = base64.urlsafe_b64encode(json.dumps({"sub": "x"}).encode()).rstrip(b"=").decode()
        assert _decode_jwt_exp(f"h.{body}.s") is None

    def test_something_that_is_not_a_jwt_yields_none(self) -> None:
        assert _decode_jwt_exp("not-a-jwt") is None

    def test_an_empty_string_yields_none(self) -> None:
        assert _decode_jwt_exp("") is None


class TestRefresh:
    """The refresh grant, and the rotation it performs."""

    async def test_a_valid_access_token_is_reused_without_a_request(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        manager = AuthManager(session, tokens)
        assert await manager.async_get_access_token() == tokens.access_token
        assert api.requests == []

    async def test_an_expired_access_token_triggers_a_refresh(
        self, api: FakeBasicFit, session
    ) -> None:
        expired = TokenSet(
            refresh_token="r1", access_token=make_jwt(), access_expires_at=int(time.time()) - 10
        )
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "r2"})
        manager = AuthManager(session, expired)
        await manager.async_get_access_token()
        assert len(api.requests) == 1

    async def test_a_token_expiring_within_the_minute_is_refreshed_early(
        self, api: FakeBasicFit, session
    ) -> None:
        # Handing out a token with 30 seconds left invites a 401 mid-request.
        nearly = TokenSet(
            refresh_token="r1", access_token=make_jwt(), access_expires_at=int(time.time()) + 30
        )
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "r2"})
        manager = AuthManager(session, nearly)
        await manager.async_get_access_token()
        assert len(api.requests) == 1

    async def test_the_refresh_token_rotates(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "rotated"})
        manager = AuthManager(session, tokens)
        new = await manager.async_refresh()
        assert new.refresh_token == "rotated"
        assert manager.tokens.refresh_token == "rotated"

    async def test_the_old_refresh_token_is_kept_when_none_is_returned(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        # Dropping the old one here would lock the account out on the next run.
        api.json(TOKEN, {"access_token": make_jwt()})
        manager = AuthManager(session, tokens)
        new = await manager.async_refresh()
        assert new.refresh_token == "refresh-1"

    async def test_the_grant_sends_the_refresh_token(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "r2"})
        await AuthManager(session, tokens).async_refresh()
        body = api.bodies[-1]
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "refresh-1"

    async def test_the_new_expiry_comes_from_the_new_token(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.json(TOKEN, {"access_token": make_jwt(exp=1900000000), "refresh_token": "r2"})
        new = await AuthManager(session, tokens).async_refresh()
        assert new.access_expires_at == 1900000000

    async def test_a_forced_refresh_ignores_a_valid_token(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "r2"})
        manager = AuthManager(session, tokens)
        await manager.async_get_access_token(force_refresh=True)
        assert len(api.requests) == 1


class TestRotationCallback:
    """The caller has to be told about the new token, or it is lost."""

    async def test_a_plain_callback_receives_the_new_tokens(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        seen: list[TokenSet] = []
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "rotated"})
        manager = AuthManager(session, tokens, token_updated=seen.append)
        await manager.async_refresh()
        assert [t.refresh_token for t in seen] == ["rotated"]

    async def test_an_async_callback_is_awaited(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        seen: list[TokenSet] = []

        async def remember(new: TokenSet) -> None:
            seen.append(new)

        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "rotated"})
        await AuthManager(session, tokens, token_updated=remember).async_refresh()
        assert [t.refresh_token for t in seen] == ["rotated"]

    async def test_no_callback_is_not_an_error(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "rotated"})
        await AuthManager(session, tokens).async_refresh()


class TestRefreshFailures:
    """A dead refresh token has to say so, because only a re-login fixes it."""

    async def test_no_refresh_token_at_all_is_an_auth_error(
        self, api: FakeBasicFit, session
    ) -> None:
        manager = AuthManager(session, TokenSet(refresh_token=""))
        with pytest.raises(BasicFitAuthError, match="no refresh token"):
            await manager.async_refresh()

    async def test_a_rejected_grant_is_an_auth_error(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.json(TOKEN, {"message": "invalid_grant"}, status=400)
        with pytest.raises(BasicFitAuthError, match="invalid_grant"):
            await AuthManager(session, tokens).async_refresh()

    async def test_the_error_tells_the_user_to_sign_in_again(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.json(TOKEN, {"message": "expired"}, status=400)
        with pytest.raises(BasicFitAuthError, match="sign in again"):
            await AuthManager(session, tokens).async_refresh()

    async def test_a_200_without_an_access_token_is_still_an_auth_error(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.json(TOKEN, {"token_type": "Bearer"})
        with pytest.raises(BasicFitAuthError):
            await AuthManager(session, tokens).async_refresh()

    async def test_a_non_json_body_is_still_an_auth_error(
        self, api: FakeBasicFit, session, tokens: TokenSet
    ) -> None:
        api.text(TOKEN, "<html>gateway timeout</html>", status=504)
        with pytest.raises(BasicFitAuthError, match="504"):
            await AuthManager(session, tokens).async_refresh()


class TestCodeExchange:
    """The one-time exchange after the browser login."""

    async def test_returns_a_full_token_set(self, api: FakeBasicFit, session) -> None:
        api.json(TOKEN, {"access_token": make_jwt(exp=1900000000), "refresh_token": "first"})
        result = await AuthManager.async_exchange_code(session, "code-1", "verifier-1")
        assert result.refresh_token == "first"
        assert result.access_expires_at == 1900000000

    async def test_sends_the_verifier_and_the_code(
        self, api: FakeBasicFit, session
    ) -> None:
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "first"})
        await AuthManager.async_exchange_code(session, "code-1", "verifier-1")
        body = api.bodies[-1]
        assert body["grant_type"] == "authorization_code"
        assert body["code"] == "code-1"
        assert body["code_verifier"] == "verifier-1"

    async def test_an_exchange_without_a_refresh_token_is_an_error(
        self, api: FakeBasicFit, session
    ) -> None:
        # An access token alone is useless: it expires within the hour and
        # there is nothing to renew it with.
        api.json(TOKEN, {"access_token": make_jwt()})
        with pytest.raises(BasicFitAuthError, match="no refresh token"):
            await AuthManager.async_exchange_code(session, "code-1", "verifier-1")


class TestClientConstruction:
    """The client's own token plumbing."""

    async def test_from_refresh_token_builds_a_usable_client(
        self, api: FakeBasicFit, session
    ) -> None:
        client = BasicFitClient.from_refresh_token("r1", session=session)
        assert client.tokens.refresh_token == "r1"
        await client.close()

    async def test_a_borrowed_session_survives_close(
        self, api: FakeBasicFit, session
    ) -> None:
        client = BasicFitClient.from_refresh_token("r1", session=session)
        await client.close()
        assert session.closed is False

    async def test_an_owned_session_is_closed(self, api: FakeBasicFit) -> None:
        client = BasicFitClient.from_refresh_token("r1")
        owned = client._session  # noqa: SLF001  ownership is the thing under test
        await client.close()
        assert owned.closed is True

    async def test_the_context_manager_closes_an_owned_session(
        self, api: FakeBasicFit
    ) -> None:
        async with BasicFitClient.from_refresh_token("r1") as client:
            owned = client._session  # noqa: SLF001
        assert owned.closed is True
