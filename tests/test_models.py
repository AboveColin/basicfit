"""Tests for the typed models.

The API mixes numbers with numeric strings and empty strings, and nests the
interesting fields one or two levels down. Each case here is a shape the API
actually returns.
"""

from __future__ import annotations

from basicfit import (
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


class TestTokenSet:
    """Token material has to survive a round trip through storage."""

    def test_a_round_trip_through_a_dict_preserves_everything(self) -> None:
        original = TokenSet(
            refresh_token="r",
            access_token="a",
            access_expires_at=1234,
            client_id="c",
            redirect_uri="app:/cb",
            obtained_at="2026-09-03T00:00:00Z",
        )
        assert TokenSet.from_dict(original.to_dict()) == original

    def test_only_the_refresh_token_is_required(self) -> None:
        rebuilt = TokenSet.from_dict({"refresh_token": "r"})
        assert rebuilt.refresh_token == "r"
        assert rebuilt.access_token is None


class TestMember:
    """The membership summary, which lives under a "member" key."""

    def test_reads_the_nested_member_object(self) -> None:
        member = Member.from_api(
            {"member": {"name": "Colin", "membershipType": "Premium", "homeClub": "Utrecht"}}
        )
        assert member.name == "Colin"
        assert member.membership_type == "Premium"
        assert member.home_club == "Utrecht"

    def test_an_empty_payload_does_not_raise(self) -> None:
        assert Member.from_api({}).name is None

    def test_the_raw_payload_is_kept_for_unmodelled_fields(self) -> None:
        member = Member.from_api({"member": {"name": "Colin", "somethingNew": 1}})
        assert member.raw["somethingNew"] == 1

    def test_add_ons_default_to_an_empty_list(self) -> None:
        assert Member.from_api({"member": {}}).add_ons == []


class TestActivity:
    """Visit history entries, only some of which are gym check-ins."""

    def test_a_gym_visit_is_recognised(self) -> None:
        entry = Activity.from_api("2026-09-01", {"type": "GYM_VISIT"})
        assert entry.is_gym_visit is True

    def test_anything_else_is_not_a_gym_visit(self) -> None:
        assert Activity.from_api("2026-09-01", {"type": "CLASS_BOOKING"}).is_gym_visit is False

    def test_a_missing_type_is_not_a_gym_visit(self) -> None:
        assert Activity.from_api("2026-09-01", {}).is_gym_visit is False

    def test_the_date_comes_from_the_feed_key_not_the_entry(self) -> None:
        # The activities feed is a map of date to entries, and the entry
        # itself carries only a time.
        entry = Activity.from_api("2026-09-01", {"startTime": "18:20"})
        assert entry.date == "2026-09-01"
        assert entry.start_time == "18:20"


class TestBodyMeasurement:
    """Scale readings, where numbers arrive as strings."""

    def test_a_numeric_string_becomes_a_float(self) -> None:
        assert BodyMeasurement.from_api({"weight": "72.5"}).weight == 72.5

    def test_an_empty_string_is_an_absence_not_a_zero(self) -> None:
        # A body-fat reading of 0.0 would be a plausible-looking wrong value.
        assert BodyMeasurement.from_api({"fat": ""}).fat is None

    def test_a_null_is_an_absence(self) -> None:
        assert BodyMeasurement.from_api({"muscle": None}).muscle is None

    def test_unparsable_text_is_an_absence(self) -> None:
        assert BodyMeasurement.from_api({"water": "n/a"}).water is None

    def test_a_real_number_passes_through(self) -> None:
        assert BodyMeasurement.from_api({"bone": 3.2}).bone == 3.2


class TestBadge:
    """Badges nest their name two levels down."""

    def test_reads_the_nested_name_and_type(self) -> None:
        badge = Badge.from_api(
            {
                "badge": {
                    "contentfulName": "50 visits",
                    "badgeType": {"contentfulName": "Milestone"},
                    "threshold": 50,
                },
                "createdAt": "2026-08-01T10:00:00Z",
            }
        )
        assert badge.name == "50 visits"
        assert badge.type == "Milestone"
        assert badge.threshold == 50
        assert badge.earned_at == "2026-08-01T10:00:00Z"

    def test_a_missing_badge_object_does_not_raise(self) -> None:
        assert Badge.from_api({}).name is None

    def test_a_missing_badge_type_does_not_raise(self) -> None:
        assert Badge.from_api({"badge": {"contentfulName": "x"}}).type is None


class TestStreak:
    """Streak progress, which must not turn junk into a number."""

    def test_reads_the_progress_and_next_threshold(self) -> None:
        streak = Streak.from_api(
            {"progress": 12, "possibleNextBadge": {"threshold": 25}, "lastIncrementDate": "2026-09-01"}
        )
        assert streak.weeks == 12
        assert streak.next_badge_at == 25
        assert streak.last_increment == "2026-09-01"

    def test_a_non_numeric_progress_is_an_absence(self) -> None:
        assert Streak.from_api({"progress": "many"}).weeks is None

    def test_an_empty_payload_does_not_raise(self) -> None:
        assert Streak.from_api({}).weeks is None


class TestWorkout:
    """Durations arrive in seconds and are reported in minutes."""

    def test_seconds_become_rounded_minutes(self) -> None:
        assert Workout.from_api({"duration": 1800}).duration_min == 30

    def test_rounding_goes_to_the_nearest_minute(self) -> None:
        assert Workout.from_api({"duration": 100}).duration_min == 2

    def test_a_zero_duration_is_an_absence_not_zero_minutes(self) -> None:
        assert Workout.from_api({"duration": 0}).duration_min is None

    def test_the_id_comes_from_the_contentful_sys_object(self) -> None:
        assert Workout.from_api({"sys": {"id": "abc"}}).id == "abc"

    def test_a_collection_becomes_a_list_of_names(self) -> None:
        workout = Workout.from_api(
            {"equipmentCollection": {"items": [{"name": "Dumbbell"}, {"name": "Bench"}]}}
        )
        assert workout.equipment == ["Dumbbell", "Bench"]

    def test_a_missing_collection_becomes_an_empty_list(self) -> None:
        assert Workout.from_api({}).body_parts == []

    def test_an_item_without_a_name_is_skipped(self) -> None:
        workout = Workout.from_api(
            {"focusBodyPartCollection": {"items": [{"name": "Legs"}, {}, None]}}
        )
        assert workout.body_parts == ["Legs"]


class TestRecipe:
    """Macros, and two more second-based durations."""

    def test_reads_the_macros(self) -> None:
        recipe = Recipe.from_api({"kcal": 520, "protein": "31", "carbs": 40, "fat": 22.5})
        assert recipe.kcal == 520
        assert recipe.protein_g == 31
        assert recipe.fat_g == 22.5

    def test_prep_and_total_time_convert_to_minutes(self) -> None:
        recipe = Recipe.from_api({"prepTime": 600, "totalTime": 1500})
        assert recipe.prep_min == 10
        assert recipe.total_min == 25

    def test_a_zero_prep_time_is_an_absence(self) -> None:
        assert Recipe.from_api({"prepTime": 0}).prep_min is None


class TestClub:
    """Clubs, where one field is spelled two ways."""

    def test_the_kp_number_is_read_from_the_capitalised_key(self) -> None:
        assert Club.from_api({"KpNumber": "1234"}).kp_number == "1234"

    def test_the_kp_number_is_also_read_from_the_lowercase_key(self) -> None:
        assert Club.from_api({"kpNumber": "1234"}).kp_number == "1234"

    def test_reads_the_address_fields(self) -> None:
        club = Club.from_api(
            {"name": "Utrecht", "city": "Utrecht", "postalCode": "3511", "closed": False}
        )
        assert club.city == "Utrecht"
        assert club.postal_code == "3511"
        assert club.closed is False

    def test_services_default_to_an_empty_list(self) -> None:
        assert Club.from_api({}).services == []
