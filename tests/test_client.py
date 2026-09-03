"""Tests for the data and content endpoints.

Two behaviours carry the risk. A 401 mid-session must cause exactly one forced
refresh and one retry, not a loop. And the activities endpoint caps a request
at 365 days, so a wider range has to be clamped rather than rejected by the
server.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from aiohttp import web

from basicfit import (
    BasicFitAPIError,
    BasicFitClient,
    BasicFitValidationError,
)
from basicfit.client import _coerce_date
from basicfit.constants import MAX_ACTIVITY_RANGE_DAYS
from basicfit.content import club_where, normalize_locale

from .conftest import FakeBasicFit, make_jwt

MEMBER = "/api/member/info"
ACTIVITIES = "/api/activities"
MEASUREMENTS = "/api/member/health/measurements"
BADGES = "/api/badges"
PROGRESS = "/api/badges/progress"
GRAPHQL = "/graphql"
TOKEN = "/token"


class TestMemberEndpoints:
    """The straightforward reads."""

    async def test_get_member_reads_the_summary(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(MEMBER, {"member": {"name": "Colin", "homeClub": "Utrecht"}})
        member = await client.get_member()
        assert member.name == "Colin"

    async def test_the_access_token_is_sent_as_a_bearer(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(MEMBER, {"member": {}})
        await client.get_member()
        assert api.requests[-1].headers["Authorization"].startswith("Bearer ")

    async def test_the_app_headers_are_sent(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        # The API rejects a default or absent User-Agent.
        api.json(MEMBER, {"member": {}})
        await client.get_member()
        headers = api.requests[-1].headers
        assert "Basic Fit App/" in headers["User-Agent"]
        assert headers["app-os"] == "android"

    async def test_measurements_come_back_newest_first(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(
            MEASUREMENTS,
            [{"date": "2026-01-01", "weight": 80}, {"date": "2026-06-01", "weight": 78}],
        )
        items = await client.get_body_measurements()
        assert [m.date for m in items] == ["2026-06-01", "2026-01-01"]

    async def test_a_measurement_limit_is_applied(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(MEASUREMENTS, [{"date": f"2026-01-{n:02d}"} for n in range(1, 11)])
        assert len(await client.get_body_measurements(limit=3)) == 3

    async def test_a_zero_limit_still_returns_one(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(MEASUREMENTS, [{"date": "2026-01-01"}, {"date": "2026-01-02"}])
        assert len(await client.get_body_measurements(limit=0)) == 1

    async def test_an_object_where_a_list_belongs_yields_nothing(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(MEASUREMENTS, {"error": "nope"})
        assert await client.get_body_measurements() == []

    async def test_badges_come_back_newest_first(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(
            BADGES,
            [
                {"badge": {"contentfulName": "old"}, "createdAt": "2025-01-01"},
                {"badge": {"contentfulName": "new"}, "createdAt": "2026-01-01"},
            ],
        )
        assert [b.name for b in await client.get_badges()] == ["new", "old"]

    async def test_the_streak_is_read(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(PROGRESS, {"progress": 9})
        assert (await client.get_streak()).weeks == 9

    async def test_a_list_where_the_streak_belongs_yields_an_empty_streak(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(PROGRESS, [])
        assert (await client.get_streak()).weeks is None


class TestTokenRetry:
    """A 401 mid-session means the token died early, not that the call failed."""

    async def test_a_401_is_retried_once_after_a_forced_refresh(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.sequence(MEMBER, (401, {"message": "expired"}), (200, {"member": {"name": "Colin"}}))
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "r2"})
        member = await client.get_member()
        assert member.name == "Colin"
        paths = [r.path for r in api.requests]
        assert paths == [MEMBER, TOKEN, MEMBER]

    async def test_a_second_401_is_not_retried_again(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        # One retry, not a loop. A token that is refused twice is dead.
        api.json(MEMBER, {"message": "expired"}, status=401)
        api.json(TOKEN, {"access_token": make_jwt(), "refresh_token": "r2"})
        with pytest.raises(BasicFitAPIError) as caught:
            await client.get_member()
        assert caught.value.status_code == 401
        assert [r.path for r in api.requests].count(MEMBER) == 2


class TestApiErrors:
    """Failures carry the status code, because the caller branches on it."""

    async def test_a_server_error_carries_its_status(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(MEMBER, {"message": "boom"}, status=500)
        with pytest.raises(BasicFitAPIError) as caught:
            await client.get_member()
        assert caught.value.status_code == 500
        assert "boom" in str(caught.value)

    async def test_a_non_json_body_is_an_api_error_with_the_status(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.text(MEMBER, "<html>gateway</html>", status=502)
        with pytest.raises(BasicFitAPIError, match="non-JSON") as caught:
            await client.get_member()
        assert caught.value.status_code == 502

    def test_the_status_code_is_rendered_in_the_message(self) -> None:
        assert "HTTP 404" in str(BasicFitAPIError("missing", 404))

    def test_a_status_free_error_renders_the_message_alone(self) -> None:
        assert str(BasicFitAPIError("plain")) == "plain"


class TestActivityRange:
    """The activities endpoint caps a request at a year."""

    async def test_the_default_range_is_the_last_thirty_days(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(ACTIVITIES, {"activities": {}})
        await client.get_activities()
        query = api.requests[-1].query
        span = date.fromisoformat(query["to"]) - date.fromisoformat(query["from"])
        assert span.days == 30

    async def test_a_range_wider_than_a_year_is_clamped(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        # The server rejects a wider span, so clamping keeps the call working
        # rather than turning it into an error the caller cannot act on.
        api.json(ACTIVITIES, {"activities": {}})
        await client.get_activities(from_date="2020-01-01", to_date="2026-01-01")
        query = api.requests[-1].query
        span = date.fromisoformat(query["to"]) - date.fromisoformat(query["from"])
        assert span.days == MAX_ACTIVITY_RANGE_DAYS

    async def test_an_explicit_narrow_range_is_left_alone(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(ACTIVITIES, {"activities": {}})
        await client.get_activities(from_date="2026-01-01", to_date="2026-01-31")
        query = api.requests[-1].query
        assert query["from"] == "2026-01-01"
        assert query["to"] == "2026-01-31"

    async def test_entries_are_flattened_out_of_the_date_map(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(
            ACTIVITIES,
            {
                "activities": {
                    "2026-01-01": [{"type": "GYM_VISIT", "startTime": "08:00"}],
                    "2026-01-02": [{"type": "GYM_VISIT", "startTime": "09:00"}],
                }
            },
        )
        entries = await client.get_activities()
        assert [e.date for e in entries] == ["2026-01-02", "2026-01-01"]

    async def test_get_visits_keeps_only_gym_check_ins(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(
            ACTIVITIES,
            {
                "activities": {
                    "2026-01-01": [
                        {"type": "GYM_VISIT", "startTime": "08:00"},
                        {"type": "CLASS_BOOKING", "startTime": "09:00"},
                    ]
                }
            },
        )
        assert len(await client.get_visits()) == 1

    async def test_an_empty_day_map_is_not_an_error(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(ACTIVITIES, {"activities": {}})
        assert await client.get_activities() == []


class TestPagingBackThroughHistory:
    """get_all_visits walks year-sized windows until one comes back empty."""

    async def test_it_stops_at_the_first_empty_window(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.sequence(
            ACTIVITIES,
            {"activities": {"2026-01-01": [{"type": "GYM_VISIT", "startTime": "08:00"}]}},
            {"activities": {}},
        )
        visits = await client.get_all_visits()
        assert len(visits) == 1
        assert len(api.requests) == 2

    async def test_it_stops_at_the_window_limit(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        # Without a cap this walks backwards forever against a server that
        # keeps answering.
        api.json(
            ACTIVITIES,
            {"activities": {"2026-01-01": [{"type": "GYM_VISIT", "startTime": "08:00"}]}},
        )
        await client.get_all_visits(max_windows=3)
        assert len(api.requests) == 3

    async def test_a_visit_seen_in_two_windows_is_returned_once(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(
            ACTIVITIES,
            {"activities": {"2026-01-01": [{"type": "GYM_VISIT", "startTime": "08:00"}]}},
        )
        visits = await client.get_all_visits(max_windows=3)
        assert len(visits) == 1


class TestDateCoercion:
    """Dates arrive as strings, dates and datetimes."""

    def test_a_date_passes_through(self) -> None:
        assert _coerce_date(date(2026, 1, 2)) == date(2026, 1, 2)

    def test_an_iso_string_is_parsed(self) -> None:
        assert _coerce_date("2026-01-02") == date(2026, 1, 2)

    def test_a_datetime_is_narrowed_to_its_date(self) -> None:
        from datetime import datetime

        assert _coerce_date(datetime(2026, 1, 2, 15, 30)) == date(2026, 1, 2)

    def test_another_format_is_refused_with_the_expected_one(self) -> None:
        with pytest.raises(BasicFitValidationError, match="YYYY-MM-DD"):
            _coerce_date("02/01/2026")


class TestContentLibrary:
    """The Contentful GraphQL side."""

    async def test_a_workout_search_returns_models(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(
            GRAPHQL,
            {"data": {"workoutCollection": {"items": [{"sys": {"id": "w1"}, "name": "Legs"}]}}},
        )
        workouts = await client.search_workouts("legs")
        assert [w.name for w in workouts] == ["Legs"]

    async def test_an_empty_query_is_refused_before_any_request(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        with pytest.raises(BasicFitValidationError, match="query is required"):
            await client.search_workouts("   ")
        assert api.requests == []

    async def test_the_result_limit_is_capped(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(GRAPHQL, {"data": {"recipeCollection": {"items": []}}})
        await client.search_recipes("rice", limit=500)
        assert api.bodies[-1]["variables"]["l"] == 30

    async def test_a_graphql_error_becomes_an_api_error(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(GRAPHQL, {"errors": [{"message": "Unknown locale"}]})
        with pytest.raises(BasicFitAPIError, match="Unknown locale"):
            await client.search_workouts("legs")

    async def test_a_response_with_no_data_is_an_api_error(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(GRAPHQL, {})
        with pytest.raises(BasicFitAPIError, match="no data"):
            await client.search_workouts("legs")

    async def test_a_club_search_needs_at_least_one_term(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        with pytest.raises(BasicFitValidationError, match="query, city or service"):
            await client.search_clubs()

    async def test_get_club_needs_an_identifier(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        with pytest.raises(BasicFitValidationError, match="club_id or kp_number"):
            await client.get_club()

    async def test_get_club_returns_none_when_nothing_matches(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(GRAPHQL, {"data": {"clubCollection": {"items": []}}})
        assert await client.get_club(club_id="1234") is None

    async def test_get_club_returns_the_single_match(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(GRAPHQL, {"data": {"clubCollection": {"items": [{"name": "Utrecht"}]}}})
        club = await client.get_club(kp_number="99")
        assert club is not None
        assert club.name == "Utrecht"

    async def test_list_clubs_pages(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(GRAPHQL, {"data": {"clubCollection": {"items": [{"name": "A"}]}}})
        await client.list_clubs(limit=500, skip=-5)
        variables = api.bodies[-1]["variables"]
        assert variables["limit"] == 100
        assert variables["skip"] == 0


class TestLocaleAndFilters:
    """Pure helpers behind the content queries."""

    @pytest.mark.parametrize("locale", ["en-US", "nl", "fr", "es", "de"])
    def test_a_published_locale_is_kept(self, locale: str) -> None:
        assert normalize_locale(locale) == locale

    def test_nl_nl_is_not_a_contentful_locale_and_falls_back(self) -> None:
        # nl-NL is the API locale, not the Contentful one. Passing it through
        # makes Contentful answer with an error rather than content.
        assert normalize_locale("nl-NL") == "en-US"

    def test_none_falls_back_to_the_default(self) -> None:
        assert normalize_locale(None) == "en-US"

    def test_a_text_query_searches_five_fields(self) -> None:
        where = club_where(query="Utrecht")
        assert len(where["OR"]) == 5

    def test_a_city_adds_one_more_alternative(self) -> None:
        assert club_where(city="Utrecht")["OR"] == [{"city_contains": "Utrecht"}]

    def test_a_service_becomes_a_contains_all_filter(self) -> None:
        assert club_where(service="sauna")["servicesIndex_contains_all"] == ["sauna"]

    def test_closed_false_is_kept_rather_than_dropped(self) -> None:
        # A falsy value that means something has to survive the filter build.
        assert club_where(closed=False)["closed"] is False

    def test_no_terms_produce_an_empty_filter(self) -> None:
        assert club_where() == {}


class TestClubImageUrl:
    """A pure URL builder with clamped dimensions."""

    def test_builds_a_url_for_a_kp_number(self) -> None:
        url = BasicFitClient.club_image_url("1234")
        assert url is not None
        assert "1234" in url

    def test_an_empty_kp_number_yields_nothing(self) -> None:
        assert BasicFitClient.club_image_url("") is None
        assert BasicFitClient.club_image_url("   ") is None

    def test_the_dimensions_are_clamped(self) -> None:
        url = BasicFitClient.club_image_url("1234", width=99999, height=1)
        assert url is not None
        assert "width:2000" in url
        assert "height:100" in url


class TestNetworkFailures:
    """A dead host is a network error, not an API error."""

    async def test_an_unreachable_data_api_is_a_network_error(
        self, client: BasicFitClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from basicfit import BasicFitNetworkError

        monkeypatch.setattr("basicfit.client.API_BASE", "http://127.0.0.1:1/api")
        with pytest.raises(BasicFitNetworkError):
            await client.get_member()

    async def test_an_unreachable_contentful_is_a_network_error(
        self, client: BasicFitClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from basicfit import BasicFitNetworkError

        monkeypatch.setattr("basicfit.client.CONTENTFUL_URL", "http://127.0.0.1:1/graphql")
        with pytest.raises(BasicFitNetworkError):
            await client.search_workouts("legs")


class TestRemainingSurface:
    """The paths the cases above did not reach."""

    async def test_the_auth_manager_is_reachable_from_the_client(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        assert client.auth.tokens is client.tokens

    async def test_an_empty_recipe_query_is_refused(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        with pytest.raises(BasicFitValidationError, match="query is required"):
            await client.search_recipes("")

    async def test_a_club_search_returns_models(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(
            GRAPHQL,
            {"data": {"clubCollection": {"items": [{"name": "Utrecht"}, {"name": "Amersfoort"}]}}},
        )
        clubs = await client.search_clubs("Utr")
        assert [c.name for c in clubs] == ["Utrecht", "Amersfoort"]

    async def test_a_club_search_clamps_its_paging(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(GRAPHQL, {"data": {"clubCollection": {"items": []}}})
        await client.search_clubs(city="Utrecht", limit=500, skip=-1)
        variables = api.bodies[-1]["variables"]
        assert variables["limit"] == 50
        assert variables["skip"] == 0

    async def test_a_club_search_sends_the_built_filter(
        self, client: BasicFitClient, api: FakeBasicFit
    ) -> None:
        api.json(GRAPHQL, {"data": {"clubCollection": {"items": []}}})
        await client.search_clubs(service="sauna")
        where = api.bodies[-1]["variables"]["where"]
        assert where["servicesIndex_contains_all"] == ["sauna"]

    async def test_an_unreachable_token_endpoint_is_a_network_error(
        self, session, tokens, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from basicfit import AuthManager, BasicFitNetworkError

        monkeypatch.setattr("basicfit.auth.AUTH_URL", "http://127.0.0.1:1")
        with pytest.raises(BasicFitNetworkError, match="token request failed"):
            await AuthManager(session, tokens).async_refresh()
