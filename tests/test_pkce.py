"""Tests for the PKCE login helpers.

These are pure functions, and they are the part of the library a user touches
by hand: they paste a redirect URL out of a browser address bar. The parser
therefore has to accept both a full custom-scheme URL and a bare code, and it
has to refuse a state that does not match.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest

from basicfit import (
    BasicFitValidationError,
    build_authorize_url,
    code_challenge_for,
    generate_code_verifier,
    parse_redirect,
    random_state,
    start_login,
)
from basicfit.constants import CLIENT_ID, LOGIN_URL, REDIRECT_URI

URL_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")

# RFC 7636 appendix B, the worked S256 example.
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class TestCodeVerifier:
    """The verifier has hard length bounds in the spec."""

    def test_the_default_length_is_inside_the_spec(self) -> None:
        assert len(generate_code_verifier()) == 64

    @pytest.mark.parametrize("length", [43, 64, 128])
    def test_an_allowed_length_is_honoured(self, length: int) -> None:
        assert len(generate_code_verifier(length)) == length

    @pytest.mark.parametrize("length", [0, 42, 129, 1000])
    def test_a_length_outside_43_to_128_is_refused(self, length: int) -> None:
        with pytest.raises(BasicFitValidationError, match="43-128"):
            generate_code_verifier(length)

    def test_the_verifier_is_url_safe_and_unpadded(self) -> None:
        assert URL_SAFE.match(generate_code_verifier())

    def test_two_verifiers_differ(self) -> None:
        assert generate_code_verifier() != generate_code_verifier()


class TestCodeChallenge:
    """S256, checked against the worked example in the RFC."""

    def test_matches_the_rfc_7636_vector(self) -> None:
        assert code_challenge_for(RFC_VERIFIER) == RFC_CHALLENGE

    def test_the_challenge_is_url_safe_and_unpadded(self) -> None:
        assert URL_SAFE.match(code_challenge_for(generate_code_verifier()))

    def test_the_same_verifier_gives_the_same_challenge(self) -> None:
        verifier = generate_code_verifier()
        assert code_challenge_for(verifier) == code_challenge_for(verifier)


class TestRandomState:
    """Opaque tokens for state and nonce."""

    def test_the_state_is_url_safe(self) -> None:
        assert URL_SAFE.match(random_state())

    def test_two_states_differ(self) -> None:
        assert random_state() != random_state()


class TestAuthorizeUrl:
    """The URL the user opens in a real browser."""

    def test_carries_every_parameter_the_flow_needs(self) -> None:
        url = build_authorize_url("chal", "st", "no")
        query = parse_qs(urlparse(url).query)
        assert query["client_id"] == [CLIENT_ID]
        assert query["redirect_uri"] == [REDIRECT_URI]
        assert query["response_type"] == ["code"]
        assert query["code_challenge"] == ["chal"]
        assert query["state"] == ["st"]
        assert query["nonce"] == ["no"]

    def test_the_challenge_method_is_s256_not_plain(self) -> None:
        # Plain would send the verifier itself, which defeats PKCE.
        query = parse_qs(urlparse(build_authorize_url("c", "s", "n")).query)
        assert query["code_challenge_method"] == ["S256"]

    def test_it_points_at_the_login_host(self) -> None:
        assert build_authorize_url("c", "s", "n").startswith(LOGIN_URL + "?")

    def test_a_caller_can_override_the_client(self) -> None:
        url = build_authorize_url("c", "s", "n", client_id="other", redirect_uri="app:/cb")
        query = parse_qs(urlparse(url).query)
        assert query["client_id"] == ["other"]
        assert query["redirect_uri"] == ["app:/cb"]


class TestStartLogin:
    """The bundle handed to the user in one call."""

    def test_the_challenge_belongs_to_the_verifier(self) -> None:
        bundle = start_login()
        assert bundle.challenge == code_challenge_for(bundle.verifier)

    def test_the_state_and_nonce_are_different_values(self) -> None:
        bundle = start_login()
        assert bundle.state != bundle.nonce

    def test_the_url_carries_the_generated_challenge(self) -> None:
        bundle = start_login()
        query = parse_qs(urlparse(bundle.authorize_url).query)
        assert query["code_challenge"] == [bundle.challenge]
        assert query["state"] == [bundle.state]


class TestParseRedirect:
    """What the user pastes back, in every shape they might paste it."""

    def test_reads_a_full_custom_scheme_redirect(self) -> None:
        value = "com.basicfit.trainingapp:/oauthredirect?code=abc123&state=xyz"
        assert parse_redirect(value) == "abc123"

    def test_reads_a_bare_code(self) -> None:
        assert parse_redirect("abc123") == "abc123"

    def test_surrounding_whitespace_is_stripped(self) -> None:
        assert parse_redirect("  abc123  ") == "abc123"

    def test_an_https_redirect_works_too(self) -> None:
        assert parse_redirect("https://example.test/cb?code=abc123") == "abc123"

    def test_a_matching_state_is_accepted(self) -> None:
        value = "com.basicfit.trainingapp:/oauthredirect?code=abc&state=xyz"
        assert parse_redirect(value, expected_state="xyz") == "abc"

    def test_a_mismatched_state_is_refused(self) -> None:
        # A wrong state is the signal that the response belongs to a different
        # login attempt, so accepting the code would be accepting a stranger's.
        value = "com.basicfit.trainingapp:/oauthredirect?code=abc&state=wrong"
        with pytest.raises(BasicFitValidationError, match="state mismatch"):
            parse_redirect(value, expected_state="xyz")

    def test_an_empty_value_is_refused(self) -> None:
        with pytest.raises(BasicFitValidationError, match="empty"):
            parse_redirect("")

    def test_a_redirect_carrying_an_error_instead_of_a_code_is_refused(self) -> None:
        value = "com.basicfit.trainingapp:/oauthredirect?error=access_denied"
        with pytest.raises(BasicFitValidationError, match="no authorization code"):
            parse_redirect(value)
