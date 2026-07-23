"""
Contentful GraphQL queries for the Basic-Fit content library.

These hit the app's *public* Contentful delivery endpoint (read-only token in
:mod:`basicfit.constants`) and back the workout, recipe and club look-ups.
"""

from __future__ import annotations

from typing import Any

from .constants import CONTENTFUL_LOCALES, DEFAULT_LOCALE

WORKOUT_QUERY = """query($q:String,$l:Int,$loc:String!){
  workoutCollection(limit:$l, locale:$loc, where:{name_contains:$q, visible:true}, order:sys_firstPublishedAt_DESC){
    total
    items{ sys{id} name description duration mets gxr audioWorkout
      format{ name }
      focusBodyPartCollection(limit:6){ items{ name } }
      equipmentCollection(limit:10){ items{ name } } }
  }
}"""

RECIPE_QUERY = """query($q:String,$l:Int,$loc:String!){
  recipeCollection(limit:$l, locale:$loc, where:{name_contains:$q}, order:sys_firstPublishedAt_DESC){
    total
    items{ sys{id} name description kcal protein carbs fat serves prepTime cookingTime totalTime difficulty
      mealTypeCollection(limit:3){ items{ name } }
      dietCollection(limit:6){ items{ name } } }
  }
}"""

_CLUB_FIELDS = """
    sys{id}
    clubId
    name
    displayName
    city
    address
    postalCode
    country
    closed
    KpNumber
    servicesIndex
    openingHours
    latitude
    longitude
    busynessData
"""

SEARCH_CLUB_QUERY = (
    "query($loc:String!,$where:ClubFilter!,$limit:Int,$skip:Int){"
    "  clubCollection(locale:$loc, where:$where, limit:$limit, skip:$skip){"
    f"    total items{{ {_CLUB_FIELDS} }}"
    "  }"
    "}"
)

CLUB_LOCATIONS_QUERY = (
    "query($limit:Int,$skip:Int){"
    "  clubCollection(limit:$limit, skip:$skip){"
    "    total items{ sys{id} clubId name displayName city address postalCode"
    " country closed KpNumber latitude longitude }"
    "  }"
    "}"
)


def normalize_locale(locale: Any, default: str = DEFAULT_LOCALE) -> str:
    """Return a Contentful-valid locale, falling back to ``default``."""
    value = str(locale) if locale is not None else default
    return value if value in CONTENTFUL_LOCALES else default


def club_where(
    query: str | None = None,
    city: str | None = None,
    service: str | None = None,
    closed: bool | None = None,
) -> dict[str, Any]:
    """Build a Contentful ``ClubFilter`` from optional search terms."""
    where: dict[str, Any] = {}
    ors: list[dict[str, Any]] = []
    if query:
        ors += [
            {"name_contains": query},
            {"displayName_contains": query},
            {"city_contains": query},
            {"address_contains": query},
            {"postalCode_contains": query},
        ]
    if city:
        ors.append({"city_contains": city})
    if ors:
        where["OR"] = ors
    if service:
        where["servicesIndex_contains_all"] = [service]
    if closed is not None:
        where["closed"] = bool(closed)
    return where
