"""
Basic-Fit quickstart.

First run does the one-time browser login and stores a refresh token in
``tokens.json``. Subsequent runs reuse (and silently rotate) that token.

    python examples/quickstart.py

Because the login page is behind an Imperva browser challenge, the sign-in
itself has to happen in a real browser — the script prints a URL, you log in,
then paste the ``com.basicfit.trainingapp:/oauthredirect?code=...`` address bar
value back into the terminal.
"""

import asyncio
import json
import os

import aiohttp

from basicfit import (
    AuthManager,
    BasicFitClient,
    TokenSet,
    parse_redirect,
    start_login,
)

TOKENS_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")


def save_tokens(tokens: TokenSet) -> None:
    with open(TOKENS_FILE, "w", encoding="utf-8") as fh:
        json.dump(tokens.to_dict(), fh, indent=2)


def load_tokens() -> TokenSet | None:
    if not os.path.exists(TOKENS_FILE):
        return None
    with open(TOKENS_FILE, encoding="utf-8") as fh:
        return TokenSet.from_dict(json.load(fh))


async def interactive_login(session: aiohttp.ClientSession) -> TokenSet:
    challenge = start_login()
    print("\n1. Open this URL in your browser and sign in:\n")
    print("   " + challenge.authorize_url + "\n")
    print("2. After login your browser will try to open a")
    print("   'com.basicfit.trainingapp:/oauthredirect?code=...' URL.")
    print("   Copy that whole URL from the address bar.\n")
    redirect = input("Paste the redirect URL (or just the code): ").strip()
    code = parse_redirect(redirect, expected_state=challenge.state)
    tokens = await AuthManager.async_exchange_code(session, code, challenge.verifier)
    save_tokens(tokens)
    print("\nLogged in — refresh token saved to tokens.json\n")
    return tokens


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        tokens = load_tokens()
        if tokens is None:
            tokens = await interactive_login(session)

        client = BasicFitClient.create(
            tokens, session=session, token_updated=save_tokens
        )

        member = await client.get_member()
        print(f"Member:      {member.name}")
        print(f"Membership:  {member.membership_type}")
        print(f"Home club:   {member.home_club}")

        visits = await client.get_visits()
        print(f"\nGym visits (last 30 days): {len(visits)}")
        for visit in visits[:5]:
            print(f"  {visit.date}  {visit.club or ''}")

        measurements = await client.get_body_measurements(limit=1)
        if measurements:
            latest = measurements[0]
            print(f"\nLatest weight: {latest.weight} kg  (fat {latest.fat}%)")

        badges = await client.get_badges()
        print(f"\nBadges earned: {len(badges)}")


if __name__ == "__main__":
    asyncio.run(main())
