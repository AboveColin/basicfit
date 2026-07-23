"""
Typed data models for the Basic-Fit API.

Each model exposes a ``from_api`` classmethod that maps the raw JSON returned by
the app API/Contentful into a stable, documented shape. The original payload is
kept on ``raw`` so callers can reach fields that aren't modelled yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


def _num(value: Any) -> Optional[float]:
    """Best-effort float conversion; ``None``/`""` -> ``None``."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class TokenSet:
    """OAuth2 token material. ``refresh_token`` rotates on every refresh."""

    refresh_token: str
    access_token: Optional[str] = None
    access_expires_at: Optional[int] = None  # epoch seconds (JWT ``exp``)
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None
    obtained_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise for persistent storage."""
        return {
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
            "access_expires_at": self.access_expires_at,
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "obtained_at": self.obtained_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenSet":
        """Rebuild from a previously stored dict."""
        return cls(
            refresh_token=data["refresh_token"],
            access_token=data.get("access_token"),
            access_expires_at=data.get("access_expires_at"),
            client_id=data.get("client_id"),
            redirect_uri=data.get("redirect_uri"),
            obtained_at=data.get("obtained_at"),
        )


@dataclass
class Member:
    """A Basic-Fit membership summary."""

    name: Optional[str]
    membership_type: Optional[str]
    membership_number: Optional[str]
    card_number: Optional[str]
    home_club: Optional[str]
    country: Optional[str]
    add_ons: list[Any] = field(default_factory=list)
    has_debt: Optional[bool] = None
    member_since: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Member":
        """Build a :class:`Member` from the ``/member/info`` payload."""
        member = (payload or {}).get("member") or {}
        return cls(
            name=member.get("name"),
            membership_type=member.get("membershipType"),
            membership_number=member.get("membershipnumber"),
            card_number=member.get("cardnumber"),
            home_club=member.get("homeClub"),
            country=member.get("country"),
            add_ons=member.get("addOns") or [],
            has_debt=member.get("hasDebt"),
            member_since=member.get("latestMembershipStartDate"),
            raw=member,
        )


@dataclass
class Activity:
    """A single activity from the visit history."""

    date: str
    type: Optional[str]
    status: Optional[str]
    start_time: Optional[str]
    club: Optional[str]
    club_id: Optional[Any] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_gym_visit(self) -> bool:
        """True if this activity is a physical gym check-in."""
        return self.type == "GYM_VISIT"

    @classmethod
    def from_api(cls, date: str, payload: dict[str, Any]) -> "Activity":
        """Build an :class:`Activity` from one activities-feed entry."""
        return cls(
            date=date,
            type=payload.get("type"),
            status=payload.get("status"),
            start_time=payload.get("startTime"),
            club=payload.get("clubName"),
            club_id=payload.get("clubId"),
            raw=payload,
        )


@dataclass
class BodyMeasurement:
    """A body-composition measurement from an in-club scale / InBody."""

    date: Optional[str]
    weight: Optional[float]
    fat: Optional[float]
    muscle: Optional[float]
    bone: Optional[float]
    water: Optional[float]
    height: Optional[float]
    id: Optional[Any] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "BodyMeasurement":
        """Build a :class:`BodyMeasurement` from one measurement record."""
        return cls(
            date=payload.get("date"),
            weight=_num(payload.get("weight")),
            fat=_num(payload.get("fat")),
            muscle=_num(payload.get("muscle")),
            bone=_num(payload.get("bone")),
            water=_num(payload.get("water")),
            height=_num(payload.get("height")),
            id=payload.get("id"),
            raw=payload,
        )


@dataclass
class Badge:
    """An earned achievement badge."""

    name: Optional[str]
    type: Optional[str]
    threshold: Optional[Any]
    earned_at: Optional[str]
    read_at: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Badge":
        """Build a :class:`Badge` from one badges-endpoint entry."""
        badge = (payload or {}).get("badge") or {}
        return cls(
            name=badge.get("contentfulName"),
            type=(badge.get("badgeType") or {}).get("contentfulName"),
            threshold=badge.get("threshold"),
            earned_at=payload.get("createdAt"),
            read_at=payload.get("readAt"),
            raw=payload,
        )


@dataclass
class Workout:
    """A workout from the Basic-Fit content library."""

    id: Optional[str]
    name: Optional[str]
    description: Optional[str]
    duration_min: Optional[int]
    mets: Optional[float]
    format: Optional[str]
    body_parts: list[str] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Workout":
        """Build a :class:`Workout` from a Contentful workout item."""
        duration = payload.get("duration")
        return cls(
            id=(payload.get("sys") or {}).get("id"),
            name=payload.get("name"),
            description=payload.get("description"),
            duration_min=round(duration / 60) if duration else None,
            mets=_num(payload.get("mets")),
            format=(payload.get("format") or {}).get("name"),
            body_parts=_names(payload.get("focusBodyPartCollection")),
            equipment=_names(payload.get("equipmentCollection")),
            raw=payload,
        )


@dataclass
class Recipe:
    """A recipe (with macros) from the Basic-Fit content library."""

    id: Optional[str]
    name: Optional[str]
    description: Optional[str]
    kcal: Optional[float]
    protein_g: Optional[float]
    carbs_g: Optional[float]
    fat_g: Optional[float]
    serves: Optional[float]
    prep_min: Optional[int]
    total_min: Optional[int]
    difficulty: Optional[str]
    meal_types: list[str] = field(default_factory=list)
    diets: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Recipe":
        """Build a :class:`Recipe` from a Contentful recipe item."""
        prep = payload.get("prepTime")
        total = payload.get("totalTime")
        return cls(
            id=(payload.get("sys") or {}).get("id"),
            name=payload.get("name"),
            description=payload.get("description"),
            kcal=_num(payload.get("kcal")),
            protein_g=_num(payload.get("protein")),
            carbs_g=_num(payload.get("carbs")),
            fat_g=_num(payload.get("fat")),
            serves=_num(payload.get("serves")),
            prep_min=round(prep / 60) if prep else None,
            total_min=round(total / 60) if total else None,
            difficulty=payload.get("difficulty"),
            meal_types=_names(payload.get("mealTypeCollection")),
            diets=_names(payload.get("dietCollection")),
            raw=payload,
        )


@dataclass
class Club:
    """A Basic-Fit club/location."""

    id: Optional[str]
    club_id: Optional[str]
    name: Optional[str]
    display_name: Optional[str]
    city: Optional[str]
    address: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    closed: Optional[bool]
    kp_number: Optional[str] = None
    services: list[str] = field(default_factory=list)
    busyness: Optional[dict[str, Any]] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Club":
        """Build a :class:`Club` from a Contentful club item."""
        return cls(
            id=(payload.get("sys") or {}).get("id"),
            club_id=payload.get("clubId"),
            name=payload.get("name"),
            display_name=payload.get("displayName"),
            city=payload.get("city"),
            address=payload.get("address"),
            postal_code=payload.get("postalCode"),
            country=payload.get("country"),
            closed=payload.get("closed"),
            kp_number=payload.get("KpNumber") or payload.get("kpNumber"),
            services=payload.get("servicesIndex") or [],
            busyness=payload.get("busynessData"),
            raw=payload,
        )


def _names(collection: Any) -> list[str]:
    """Extract ``.name`` from a Contentful ``*Collection`` object."""
    items = (collection or {}).get("items") or []
    return [i.get("name") for i in items if i and i.get("name")]
