![PyPI - Downloads](https://img.shields.io/pypi/dm/basicfit)
![PyPI - Downloads](https://img.shields.io/pypi/dd/basicfit)

# Unofficial Basic-Fit API Client

_Disclaimer: This is an unofficial Python client for the Basic-Fit app API. It is not affiliated with, endorsed by, or in any way connected to Basic-Fit N.V. Use it with your own account, at your own risk._

## Introduction
The Unofficial Basic-Fit API Client is an asynchronous Python library for the backend that powers the Basic-Fit mobile app. It lets you read your membership details, gym visit history, in-club body-composition measurements and achievement badges, and it exposes the public workout, recipe and club-finder content library. The client handles the OAuth2 token lifecycle — including Basic-Fit's rotating refresh tokens — so you can focus on the data.

## Features
- **Authentication Management:** Keeps a valid access token, refreshes automatically when it expires, and correctly persists the **rotating** refresh token Basic-Fit hands back on every refresh.
- **One-time browser login (PKCE):** A helper that builds the authorize URL and exchanges the returned code for tokens. The sign-in itself happens in a real browser because the login page is protected by a bot-challenge WAF.
- **Membership info:** Name, membership type, home club, card/membership number, add-ons and outstanding-debt flag.
- **Visit history:** Full activity feed with a convenience filter for physical gym check-ins.
- **Body measurements:** Weight, fat %, muscle, water and more from the in-club scales.
- **Badges:** Earned achievement badges.
- **Content library:** Search the workout catalog, the recipe catalog (with macros) and the club finder — all via the app's public Contentful endpoint.
- **Typed models:** Every response is parsed into a documented dataclass, with the raw payload kept on `.raw` for anything not yet modelled.

## Features to be Added
- **Workout progress / logging endpoints**
- **Club busyness time-series helpers**

(feel free to PR if you manage to implement any of these features)

## Installation
Ensure you have Python 3.11 or higher installed. You can install the package using pip:

```bash
pip install basicfit
```

Or, from a checkout:

```bash
pip install -r requirements.txt
```

## Authentication

Basic-Fit uses OAuth2 Authorization Code + PKCE. The **login page** (`login.basic-fit.com`) sits behind an Imperva browser challenge, so it can't be automated headlessly — you sign in once in a normal browser. The **token endpoint** (`auth.basic-fit.com`) is not challenged, so all refreshes after that first login happen automatically in the background.

> **Refresh tokens rotate.** Every refresh returns a *new* refresh token and invalidates the old one. Always persist the token set after each call — use the `token_updated` callback below and you never have to think about it.

### One-time browser login

```python
import asyncio
import aiohttp
from basicfit import AuthManager, TokenSet, start_login, parse_redirect

async def login():
    challenge = start_login()
    print("Open this URL and sign in:\n", challenge.authorize_url)
    # Your browser will try to open a
    # com.basicfit.trainingapp:/oauthredirect?code=... URL — copy it from the
    # address bar and paste it here:
    redirect = input("Paste the redirect URL: ").strip()
    code = parse_redirect(redirect, expected_state=challenge.state)

    async with aiohttp.ClientSession() as session:
        tokens = await AuthManager.async_exchange_code(
            session, code, challenge.verifier
        )
    # Persist this — it's all you need next time.
    print(tokens.to_dict())

asyncio.run(login())
```

### Reusing a stored token

```python
import json
from basicfit import BasicFitClient, TokenSet

def save(tokens):  # called automatically after every rotation
    with open("tokens.json", "w") as fh:
        json.dump(tokens.to_dict(), fh)

with open("tokens.json") as fh:
    tokens = TokenSet.from_dict(json.load(fh))

client = BasicFitClient.create(tokens, token_updated=save)
```

Or, if you only have the raw refresh token string:

```python
client = BasicFitClient.from_refresh_token("<refresh-token>", token_updated=save)
```

## Usage

The client manages its own `aiohttp` session (pass your own via `session=` if you prefer) and works as an async context manager.

```python
import asyncio
from basicfit import BasicFitClient, TokenSet

async def main():
    async with BasicFitClient.from_refresh_token("<refresh-token>") as client:
        # Membership
        member = await client.get_member()
        print(member.name, member.membership_type, member.home_club)

        # Gym visits (last 30 days by default; accepts date ranges, max 365 days)
        visits = await client.get_visits()
        print(f"{len(visits)} visits")
        for v in visits[:5]:
            print(v.date, v.club)

        # Body composition (most recent first)
        for m in await client.get_body_measurements(limit=3):
            print(m.date, m.weight, "kg", m.fat, "% fat")

        # Achievement badges
        for b in await client.get_badges():
            print(b.name, b.earned_at)

asyncio.run(main())
```

### Content library

The workout, recipe and club look-ups hit Basic-Fit's public content endpoint and don't require authentication (they work even before login):

```python
async with BasicFitClient.from_refresh_token("<refresh-token>") as client:
    workouts = await client.search_workouts("full body", limit=5)
    for w in workouts:
        print(w.name, w.duration_min, "min", w.body_parts)

    recipes = await client.search_recipes("protein", limit=5)
    for r in recipes:
        print(r.name, r.kcal, "kcal", r.protein_g, "g protein")

    clubs = await client.search_clubs(city="Groningen")
    for c in clubs:
        print(c.display_name, c.address, "closed" if c.closed else "open")
        print(client.club_image_url(c.kp_number))
```

## Quickstart script

`examples/quickstart.py` runs the whole flow end to end: it does the one-time browser login, stores the token in `tokens.json`, and prints your membership, recent visits, latest weight and badge count. On later runs it reuses (and silently rotates) the stored token.

```bash
python examples/quickstart.py
```

## Home Assistant

A companion Home Assistant integration built on this package lives at [HA-Basic-Fit](https://github.com/AboveColin/HA-Basic-Fit) — install it via HACS to get your visits, membership, weight and badges as sensors.

## Notes

- **Locales:** the content library uses Contentful locale codes (`en-US`, `nl`, `fr`, `es`, `de`) — note `nl`, not `nl-NL`. The client normalises unknown values to `en-US`.
- **Ranges:** the activities endpoint accepts spans up to 365 days; longer ranges are clamped.
- **Errors:** the package raises `BasicFitAuthError` (sign in again), `BasicFitAPIError` (bad response, carries `status_code`), `BasicFitNetworkError` (timeout/connection) and `BasicFitValidationError` (bad arguments) — all subclasses of `BasicFitError`.

## License
MIT — see [LICENSE](LICENSE).
