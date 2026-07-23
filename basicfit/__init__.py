"""
basicfit — an unofficial async Python client for the Basic-Fit app API.

Exposes the member data endpoints (membership, visit history, body
measurements, badges) and the public content library (workouts, recipes,
clubs), plus the one-time PKCE browser login used to obtain a refresh token.
"""

from .auth import AuthManager, TokenUpdatedCallback
from .client import BasicFitClient
from .constants import (
    API_BASE,
    AUTH_URL,
    CLIENT_ID,
    CONTENTFUL_LOCALES,
    DEFAULT_LOCALE,
    LOGIN_URL,
    REDIRECT_URI,
)
from .exceptions import (
    BasicFitAPIError,
    BasicFitAuthError,
    BasicFitError,
    BasicFitNetworkError,
    BasicFitValidationError,
)
from .models import (
    Activity,
    Badge,
    BodyMeasurement,
    Club,
    Member,
    Recipe,
    TokenSet,
    Workout,
)
from .pkce import (
    PkceChallenge,
    build_authorize_url,
    code_challenge_for,
    generate_code_verifier,
    parse_redirect,
    random_state,
    start_login,
)

__version__ = "1.0.0"

__all__ = [
    # Main client
    "BasicFitClient",
    # Auth
    "AuthManager",
    "TokenUpdatedCallback",
    "TokenSet",
    # PKCE login
    "PkceChallenge",
    "start_login",
    "build_authorize_url",
    "generate_code_verifier",
    "code_challenge_for",
    "random_state",
    "parse_redirect",
    # Exceptions
    "BasicFitError",
    "BasicFitAPIError",
    "BasicFitAuthError",
    "BasicFitNetworkError",
    "BasicFitValidationError",
    # Models
    "Member",
    "Activity",
    "BodyMeasurement",
    "Badge",
    "Workout",
    "Recipe",
    "Club",
    # Constants
    "AUTH_URL",
    "LOGIN_URL",
    "API_BASE",
    "CLIENT_ID",
    "REDIRECT_URI",
    "CONTENTFUL_LOCALES",
    "DEFAULT_LOCALE",
]
