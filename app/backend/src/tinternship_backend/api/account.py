"""Who is signed in, and how far their account setup got.

The app has no login of its own. A forward-auth proxy (Authelia, here) sits in
front of it and passes the identity down as `Remote-User` / `Remote-Name` /
`Remote-Email` / `Remote-Groups` request headers — the `authResponseHeaders`
list on the proxy's forwardAuth middleware. Nothing here authenticates
anyone; it reports what the proxy already decided, so the Account page can name
whose profile is on screen.

Run locally there is no proxy and the headers are absent, which answers
`authenticated: false` — the honest reading, not an error.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.onboarding import setup_state

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("")
async def account(request: Request):
    username = request.headers.get("Remote-User", "").strip()
    groups = request.headers.get("Remote-Groups", "")
    return {
        "authenticated": bool(username),
        "username": username,
        "display_name": request.headers.get("Remote-Name", "").strip(),
        "email": request.headers.get("Remote-Email", "").strip(),
        "groups": [group.strip() for group in groups.split(",") if group.strip()],
        "setup": await setup_state(),
    }
