"""
Async client for the Basic-Fit API.

:class:`BasicFitClient` wraps :class:`~basicfit.auth.AuthManager` and exposes the
member data endpoints plus the public content library. It manages its own
``aiohttp`` session unless one is supplied.

Example::

    async with BasicFitClient.from_refresh_token("<refresh-token>") as client:
        member = await client.get_member()
        print(member.name, member.home_club)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

import aiohttp

from .auth import AuthManager, TokenUpdatedCallback
from .constants import (
    API_BASE,
    APP_HEADERS,
    CLIENT_ID,
    CLUB_IMAGE_TEMPLATE,
    CONTENTFUL_TOKEN,
    CONTENTFUL_URL,
    DEFAULT_LCID,
    DEFAULT_LOCALE,
    DEFAULT_TIMEOUT,
    MAX_ACTIVITY_RANGE_DAYS,
    REDIRECT_URI,
)
from .content import (
    CLUB_LOCATIONS_QUERY,
    RECIPE_QUERY,
    SEARCH_CLUB_QUERY,
    WORKOUT_QUERY,
    club_where,
    normalize_locale,
)
from .exceptions import (
    BasicFitAPIError,
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
    Streak,
    TokenSet,
    Workout,
)


def _ymd(value: date) -> str:
    return value.strftime("%Y-%m-%d")


class BasicFitClient:
    """High-level async client for a single Basic-Fit account."""

    def __init__(
        self,
        auth: AuthManager,
        session: aiohttp.ClientSession,
        *,
        owns_session: bool = False,
        locale: str = DEFAULT_LOCALE,
    ) -> None:
        self._auth = auth
        self._session = session
        self._owns_session = owns_session
        self.locale = locale

    # -- construction ----------------------------------------------------------

    @classmethod
    def create(
        cls,
        tokens: TokenSet,
        *,
        session: Optional[aiohttp.ClientSession] = None,
        token_updated: Optional[TokenUpdatedCallback] = None,
        client_id: str = CLIENT_ID,
        redirect_uri: str = REDIRECT_URI,
        locale: str = DEFAULT_LOCALE,
    ) -> "BasicFitClient":
        """Create a client from an existing :class:`TokenSet`."""
        owns = session is None
        session = session or aiohttp.ClientSession()
        auth = AuthManager(
            session,
            tokens,
            token_updated=token_updated,
            client_id=client_id,
            redirect_uri=redirect_uri,
        )
        return cls(auth, session, owns_session=owns, locale=locale)

    @classmethod
    def from_refresh_token(
        cls,
        refresh_token: str,
        *,
        session: Optional[aiohttp.ClientSession] = None,
        token_updated: Optional[TokenUpdatedCallback] = None,
        locale: str = DEFAULT_LOCALE,
    ) -> "BasicFitClient":
        """Convenience constructor from a bare refresh token."""
        return cls.create(
            TokenSet(refresh_token=refresh_token),
            session=session,
            token_updated=token_updated,
            locale=locale,
        )

    @property
    def auth(self) -> AuthManager:
        """The underlying auth manager (exposes the current token set)."""
        return self._auth

    @property
    def tokens(self) -> TokenSet:
        """The current token set (persist this after rotation)."""
        return self._auth.tokens

    async def close(self) -> None:
        """Close the session if this client created it."""
        if self._owns_session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> "BasicFitClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # -- low level -------------------------------------------------------------

    async def _api_get(self, path: str) -> Any:
        """GET ``path`` from the data API with a single 401-refresh retry."""
        try:
            token = await self._auth.async_get_access_token()
            resp_status, text = await self._raw_get(path, token)
            if resp_status == 401:
                token = await self._auth.async_get_access_token(force_refresh=True)
                resp_status, text = await self._raw_get(path, token)
        except aiohttp.ClientError as err:
            raise BasicFitNetworkError(f"request to {path} failed: {err}") from err

        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise BasicFitAPIError(
                f"{path} returned non-JSON ({resp_status})", resp_status
            ) from err
        if resp_status >= 400:
            message = ""
            if isinstance(data, dict):
                message = data.get("message") or ""
            raise BasicFitAPIError(f"{path} error: {message}".strip(), resp_status)
        return data

    async def _raw_get(self, path: str, token: str) -> tuple[int, str]:
        headers = {**APP_HEADERS, "Authorization": f"Bearer {token}"}
        async with self._session.get(
            f"{API_BASE}{path}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
        ) as resp:
            return resp.status, await resp.text()

    async def _cf_query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Run a Contentful GraphQL query and return its ``data`` object."""
        try:
            async with self._session.post(
                CONTENTFUL_URL,
                headers={
                    "Authorization": f"Bearer {CONTENTFUL_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables},
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as resp:
                payload = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise BasicFitNetworkError(f"Contentful request failed: {err}") from err
        if payload.get("errors"):
            msg = payload["errors"][0].get("message", "unknown")
            raise BasicFitAPIError(f"Contentful error: {msg}")
        data = payload.get("data")
        if data is None:
            raise BasicFitAPIError("Contentful returned no data")
        return data

    # -- member data -----------------------------------------------------------

    async def get_member(self) -> Member:
        """Return the membership summary."""
        return Member.from_api(await self._api_get("/member/info"))

    async def get_activities(
        self,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> list[Activity]:
        """Return activities in the range (default: last 30 days, max 365)."""
        today = date.today()
        end = _coerce_date(to_date) if to_date else today
        start = _coerce_date(from_date) if from_date else end - timedelta(days=30)
        if (end - start).days > MAX_ACTIVITY_RANGE_DAYS:
            start = end - timedelta(days=MAX_ACTIVITY_RANGE_DAYS)
        data = await self._api_get(f"/activities?from={_ymd(start)}&to={_ymd(end)}")
        by_date = data.get("activities") or {}
        activities: list[Activity] = []
        for day, entries in by_date.items():
            for entry in entries or []:
                activities.append(Activity.from_api(day, entry))
        activities.sort(key=lambda a: str(a.start_time or ""), reverse=True)
        return activities

    async def get_visits(
        self,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> list[Activity]:
        """Return only gym check-ins (``GYM_VISIT``) in the range."""
        return [a for a in await self.get_activities(from_date, to_date) if a.is_gym_visit]

    async def get_all_visits(self, *, max_windows: int = 20) -> list[Activity]:
        """Return every recorded gym check-in, paging back through history.

        The ``/activities`` endpoint caps each request at
        :data:`MAX_ACTIVITY_RANGE_DAYS`, so this walks backwards in
        year-sized windows until it hits an empty window (or ``max_windows``),
        de-duplicates, and returns the visits most-recent first.

        Note: this reflects the visits Basic-Fit's activity feed has records
        for. It can be lower than the lifetime "visits" counter shown in the
        Basic-Fit app, which may include check-ins from before the activity
        feed began tracking them.
        """
        step = timedelta(days=MAX_ACTIVITY_RANGE_DAYS - 1)
        end = date.today()
        seen: set[str] = set()
        visits: list[Activity] = []
        for _ in range(max_windows):
            start = end - step
            window = await self.get_visits(from_date=start, to_date=end)
            if not window:
                break
            for visit in window:
                key = str(visit.start_time or "") + "|" + str(visit.date or "")
                if key in seen:
                    continue
                seen.add(key)
                visits.append(visit)
            end = start - timedelta(days=1)
        visits.sort(key=lambda a: str(a.start_time or a.date or ""), reverse=True)
        return visits

    async def get_body_measurements(
        self, limit: Optional[int] = None
    ) -> list[BodyMeasurement]:
        """Return body-composition measurements, most recent first."""
        data = await self._api_get("/member/health/measurements")
        items = [BodyMeasurement.from_api(x) for x in data] if isinstance(data, list) else []
        items.sort(key=lambda m: str(m.date or ""), reverse=True)
        if limit is not None:
            items = items[: max(1, min(int(limit), 100))]
        return items

    async def get_badges(self, lcid: str = DEFAULT_LCID) -> list[Badge]:
        """Return earned achievement badges, most recent first."""
        data = await self._api_get(f"/badges?lcid={lcid}")
        items = [Badge.from_api(b) for b in data] if isinstance(data, list) else []
        items.sort(key=lambda b: str(b.earned_at or ""), reverse=True)
        return items

    async def get_streak(self) -> Streak:
        """Return the current visit streak (consecutive weeks with a check-in)."""
        data = await self._api_get("/badges/progress")
        return Streak.from_api(data if isinstance(data, dict) else {})

    # -- content library -------------------------------------------------------

    async def search_workouts(
        self, query: str, limit: int = 8, locale: Optional[str] = None
    ) -> list[Workout]:
        """Search the workout catalog by name."""
        if not query or not query.strip():
            raise BasicFitValidationError("query is required")
        variables = {
            "q": query.strip(),
            "l": max(1, min(int(limit), 30)),
            "loc": normalize_locale(locale or self.locale),
        }
        data = await self._cf_query(WORKOUT_QUERY, variables)
        items = (data.get("workoutCollection") or {}).get("items") or []
        return [Workout.from_api(w) for w in items]

    async def search_recipes(
        self, query: str, limit: int = 8, locale: Optional[str] = None
    ) -> list[Recipe]:
        """Search the recipe catalog (with macros) by name."""
        if not query or not query.strip():
            raise BasicFitValidationError("query is required")
        variables = {
            "q": query.strip(),
            "l": max(1, min(int(limit), 30)),
            "loc": normalize_locale(locale or self.locale),
        }
        data = await self._cf_query(RECIPE_QUERY, variables)
        items = (data.get("recipeCollection") or {}).get("items") or []
        return [Recipe.from_api(r) for r in items]

    async def search_clubs(
        self,
        query: Optional[str] = None,
        *,
        city: Optional[str] = None,
        service: Optional[str] = None,
        closed: Optional[bool] = None,
        limit: int = 10,
        skip: int = 0,
        locale: Optional[str] = None,
    ) -> list[Club]:
        """Search clubs by name/city/postcode and optional service."""
        if not any([query, city, service]):
            raise BasicFitValidationError("provide query, city or service")
        variables = {
            "loc": normalize_locale(locale or "nl"),
            "where": club_where(query, city, service, closed),
            "limit": max(1, min(int(limit), 50)),
            "skip": max(0, int(skip)),
        }
        data = await self._cf_query(SEARCH_CLUB_QUERY, variables)
        items = (data.get("clubCollection") or {}).get("items") or []
        return [Club.from_api(c) for c in items]

    async def get_club(
        self,
        club_id: Optional[str] = None,
        kp_number: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> Optional[Club]:
        """Fetch a single club by ``club_id`` or ``kp_number``."""
        if not club_id and not kp_number:
            raise BasicFitValidationError("provide club_id or kp_number")
        where = {"clubId": club_id} if club_id else {"KpNumber": kp_number}
        variables = {
            "loc": normalize_locale(locale or "nl"),
            "where": where,
            "limit": 1,
            "skip": 0,
        }
        data = await self._cf_query(SEARCH_CLUB_QUERY, variables)
        items = (data.get("clubCollection") or {}).get("items") or []
        return Club.from_api(items[0]) if items else None

    async def list_clubs(self, limit: int = 50, skip: int = 0) -> list[Club]:
        """Return a page of clubs from the raw locations collection."""
        variables = {"limit": max(1, min(int(limit), 100)), "skip": max(0, int(skip))}
        data = await self._cf_query(CLUB_LOCATIONS_QUERY, variables)
        items = (data.get("clubCollection") or {}).get("items") or []
        return [Club.from_api(c) for c in items]

    @staticmethod
    def club_image_url(kp_number: str, width: int = 800, height: int = 450) -> Optional[str]:
        """Build the public "front/outside" image URL for a club KP number."""
        kp = str(kp_number or "").strip()
        if not kp:
            return None
        width = max(100, min(int(width), 2000))
        height = max(100, min(int(height), 2000))
        return CLUB_IMAGE_TEMPLATE.format(kp=kp, width=width, height=height)


def _coerce_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as err:
        raise BasicFitValidationError("dates must be YYYY-MM-DD") from err
