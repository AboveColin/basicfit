"""
Endpoints, client identifiers and default headers for the Basic-Fit API.

All values are derived from the public Basic-Fit mobile application. They are
constants of the app itself (not personal credentials) and are required for the
API to accept requests.
"""

from __future__ import annotations

# --- OAuth2 / token endpoints -------------------------------------------------

#: Token endpoint host (Fastify, no WAF, headless-callable).
AUTH_URL = "https://auth.basic-fit.com"

#: Interactive login SPA. This host sits behind an Imperva browser challenge, so
#: it can only be completed in a real browser (see :mod:`basicfit.pkce`).
LOGIN_URL = "https://login.basic-fit.com/login"

#: Public OAuth2 client id of the Android app.
CLIENT_ID = "hMN33iw3DpHNg5VQaeNKoRUQKmIIvQV5vxOKba8AnrM"

#: Public OAuth2 client id of the iOS app (kept for completeness).
CLIENT_ID_IOS = "q6KqjlQINmjOC86rqt9JdU_i41nhD_Z4DwygpBxGiIs"

#: Redirect URI registered for the mobile app (custom scheme).
REDIRECT_URI = "com.basicfit.trainingapp:/oauthredirect"

# --- Data API -----------------------------------------------------------------

#: Base URL of the member data API.
API_BASE = "https://bfa.basic-fit.com/api"

#: App version advertised to the API. The API rejects a default/absent
#: ``User-Agent``; these headers make requests look like the real app.
APP_VERSION = "1.93.0"

APP_HEADERS: dict[str, str] = {
    "User-Agent": f"Basic Fit App/{APP_VERSION} (android)",
    "bfa-version": APP_VERSION,
    "app-os": "android",
    "os-version": "13",
    "locale": "nl-NL",
    "Accept": "application/json",
}

# --- Contentful content library ----------------------------------------------

#: Contentful GraphQL delivery endpoint (workouts / recipes / clubs).
CONTENTFUL_URL = (
    "https://graphql.contentful.com/content/v1/spaces/ztnn01luatek/environments/master"
)

#: Public Contentful *delivery* (read-only) token baked into the app.
CONTENTFUL_TOKEN = "wRd4zwNule_XU0IrbE-DSfF0IcFxSnDCilyboUhYLps"

#: Locales the Contentful space is published in. ``nl-NL`` is NOT valid here.
CONTENTFUL_LOCALES = ("en-US", "nl", "fr", "es", "de")
DEFAULT_LOCALE = "en-US"

# --- Misc ---------------------------------------------------------------------

#: Default locale id used for the badges endpoint (1043 == nl-NL).
DEFAULT_LCID = "1043"

#: Template for the public club "front / outside" image (brand CDN).
CLUB_IMAGE_TEMPLATE = (
    "https://brand.basic-fit.com/match/KP_Number/{kp}/Club_area/Front_club_outside/"
    "?io=transform:fill,height:{height},width:{width}"
)

#: Maximum span accepted by the activities endpoint.
MAX_ACTIVITY_RANGE_DAYS = 365

#: Default request timeout in seconds.
DEFAULT_TIMEOUT = 20
