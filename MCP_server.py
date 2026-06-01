#!/usr/bin/env python3
# cabalspy_mcp.py
# ═══════════════════════════════════════════════════════════════════════════════
# CabalSpy MCP-Server  —  mcp.cabalspy.xyz
#
# Verpackt ALLE öffentlichen CabalSpy /v1/-Wallet-Endpoints als MCP-Tools, damit
# KI-Assistenten (Claude, ChatGPT, Cursor, …) live CabalSpy-Daten abfragen können.
#
# Dieser Server ruft NUR die bestehende REST-API auf (https://api.cabalspy.xyz).
# Er fasst die API-Logik nicht an — er ist ein dünner Client davor.
#
# AUTH (pro Nutzer): Jeder Nutzer hinterlegt seinen EIGENEN CabalSpy-Key. Der Key
# wird vom MCP-Client als HTTP-Header übergeben:
#       X-CabalSpy-Key: <key>
#   (Fallback: Umgebungsvariable CABALSPY_API_KEY, nur für Single-User/Demo.)
# Wer keinen Key hat, bekommt über das Tool `get_started` die Links zu Pricing
# und zum Dashboard, wo es einen kostenlosen Test-Key mit 1000 Free-Abfragen gibt.
#
# Transport: Streamable HTTP (empfohlen für Remote-/Produktion).
#
# Start:
#   pip install "mcp[cli]" httpx
#   MCP_PORT=8081 python3 cabalspy_mcp.py
#   → Server läuft auf http://0.0.0.0:8081/mcp  (nginx terminiert TLS davor)
# ═══════════════════════════════════════════════════════════════════════════════

import os
import httpx
from mcp.server.fastmcp import FastMCP, Context

API_BASE = os.environ.get("CABALSPY_API_BASE", "https://api.cabalspy.xyz")
ENV_KEY  = os.environ.get("CABALSPY_API_KEY", "")    # Fallback (Demo/Single-User)
TIMEOUT  = 15.0

PRICING_URL   = "https://cabalspy.xyz/pricing"
DASHBOARD_URL = "https://apidashboard.cabalspy.xyz/"
DOCS_URL      = "https://docs.cabalspy.xyz"

mcp = FastMCP(
    "CabalSpy",
    stateless_http=True,
    json_response=True,
    instructions=(
        "CabalSpy tracks labeled crypto wallets (KOLs, smart money, whales) across "
        "Solana, BNB, Base and Ethereum. Use these tools to fetch leaderboards, "
        "per-wallet trading stats, lifetime history, current holdings, PnL "
        "calendars and wallet connections. Each user must supply their own "
        "CabalSpy API key via the 'X-CabalSpy-Key' header. If a tool returns an "
        "auth error, call the 'get_started' tool — it returns the link to a free "
        "test key (1000 requests) and the pricing page."
    ),
)


def _resolve_key(ctx: Context | None) -> str:
    """Key aus dem HTTP-Header 'X-CabalSpy-Key'; Fallback ENV (Demo)."""
    try:
        req = ctx.request_context.request if ctx else None
        if req is not None:
            hdr = req.headers.get("x-cabalspy-key")
            if hdr:
                return hdr.strip()
    except Exception:
        pass
    return ENV_KEY


async def _get(path: str, params: dict, ctx: Context | None) -> dict:
    """Ruft einen CabalSpy-v1-Endpoint mit dem Key des Nutzers auf."""
    key = _resolve_key(ctx)
    if not key:
        return {
            "error": "missing_api_key",
            "message": (
                "No CabalSpy API key provided. Set the 'X-CabalSpy-Key' header in "
                "your MCP client config. Get a free test key (1000 requests) — call "
                "the 'get_started' tool for the links."
            ),
            "get_test_key": DASHBOARD_URL,
            "pricing": PRICING_URL,
        }
    params = {k: v for k, v in params.items() if v not in (None, "")}
    params["api_key"] = key
    url = f"{API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, params=params)
    except Exception as e:
        return {"error": "request_failed", "detail": str(e)[:200]}
    if r.status_code in (401, 403):
        return {
            "error": "auth_failed",
            "message": (
                "Your CabalSpy API key is invalid or out of credits. Get a free "
                "test key (1000 requests) or view plans — call 'get_started'."
            ),
            "get_test_key": DASHBOARD_URL,
            "pricing": PRICING_URL,
        }
    if r.status_code != 200:
        return {"error": f"http_{r.status_code}", "detail": r.text[:300]}
    return r.json()


# ── Onboarding / Discovery ──────────────────────────────────────────────────────
@mcp.tool()
async def get_started() -> dict:
    """
    How to use CabalSpy: where to get a free API key (1000 requests, no cost),
    pricing and documentation. Call this first if you don't have an API key yet
    or if another tool returned an auth error.
    """
    return {
        "what_is_cabalspy": (
            "CabalSpy tracks labeled crypto wallets — KOLs, smart money and whales — "
            "across Solana, BNB, Base and Ethereum, with realized PnL, win rates, "
            "lifetime history, live holdings and wallet-connection analysis."
        ),
        "free_test_key": {
            "url": DASHBOARD_URL,
            "details": "Create a free test key with 1000 requests at no cost.",
        },
        "pricing": PRICING_URL,
        "docs": DOCS_URL,
        "how_to_set_key": (
            "Add 'X-CabalSpy-Key: <your-key>' to your MCP client's server config "
            "headers, then call any data tool."
        ),
        "chains": ["solana", "bnb", "base", "eth"],
        "wallet_types": ["kol", "smart", "whale"],
        "periods": ["6h", "1d", "7d", "30d"],
    }


@mcp.tool()
async def get_leaderboard(blockchain: str, wallet_type: str = "kol",
                          period: str = "1d", limit: int = 20,
                          ctx: Context = None) -> dict:
    """
    Top tracked wallets ranked by trading volume for a chain, wallet type and
    period. Use for "best Solana KOLs today", "top whales this week", etc.

    blockchain: solana, bnb, base or eth
    wallet_type: kol, smart or whale (default kol)
    period: 6h, 1d, 7d or 30d (default 1d)
    limit: max wallets to return (default 20)
    """
    return await _get("/v1/wallet/leaderboard", {
        "blockchain": blockchain, "type": wallet_type,
        "period": period, "limit": limit,
    }, ctx)


@mcp.tool()
async def get_wallet_tracker(blockchain: str, address: str,
                             period: str = "1d", ctx: Context = None) -> dict:
    """
    Detailed period stats for ONE wallet: realized PnL, win rate, volume, trade
    counts, active tokens, win-rate distribution and recent trades.

    blockchain: solana, bnb, base or eth
    address: the wallet address
    period: 6h, 1d, 7d or 30d (default 1d)
    """
    return await _get("/v1/wallet/tracking", {
        "blockchain": blockchain, "address": address, "period": period,
    }, ctx)


@mcp.tool()
async def list_wallets(blockchain: str, wallet_type: str,
                       limit: int = 50, cursor: str = "",
                       ctx: Context = None) -> dict:
    """
    List all tracked wallets for a chain and wallet type (paginated).

    blockchain: solana, bnb, base or eth
    wallet_type: kol, smart or whale
    limit: max wallets per page (default 50)
    cursor: pagination cursor from the previous response (omit for first page)
    """
    return await _get("/v1/wallets", {
        "blockchain": blockchain, "type": wallet_type,
        "limit": limit, "cursor": cursor,
    }, ctx)


@mcp.tool()
async def lookup_wallet(address: str, ctx: Context = None) -> dict:
    """
    Check whether a wallet address is tracked by CabalSpy across all chains and
    types. Returns the wallet's profile (name, chain, type) if found.

    address: the wallet address to look up
    """
    return await _get("/v1/wallets/lookup", {"address": address}, ctx)


@mcp.tool()
async def get_wallet_history(blockchain: str, address: str,
                             cursor: str = "", limit: int = 100,
                             ctx: Context = None) -> dict:
    """
    Complete LIFETIME trading history for a wallet: aggregated stats, per-token
    overview, win-rate distribution and a paginated list of every transaction.
    For a full export, call repeatedly with pagination.next_cursor until null.

    blockchain: solana, bnb, base or eth
    address: the wallet address
    cursor: pagination cursor from the previous response (omit for first page)
    limit: trades per page, 1-1000 (default 100)
    """
    return await _get("/v1/wallets/history", {
        "blockchain": blockchain, "address": address,
        "cursor": cursor, "limit": limit,
    }, ctx)


@mcp.tool()
async def get_wallet_holdings(blockchain: str, address: str,
                              ctx: Context = None) -> dict:
    """
    Current on-chain token holdings of a wallet (amounts, not USD). If 'loading'
    is true, the data is still warming up — call again shortly.

    blockchain: solana, bnb, base or eth
    address: the wallet address
    """
    return await _get("/v1/wallet/holdings", {
        "blockchain": blockchain, "address": address,
    }, ctx)


@mcp.tool()
async def get_pnl_calendar(blockchain: str, address: str,
                           ctx: Context = None) -> dict:
    """
    Daily and monthly realized-PnL calendar for a wallet, covering its full
    tracked history (all months, plus the current month live).

    blockchain: solana, bnb, base or eth
    address: the wallet address
    """
    return await _get("/v1/wallet/pnl_calendar", {
        "blockchain": blockchain, "address": address,
    }, ctx)


@mcp.tool()
async def get_wallet_connections(blockchain: str, address: str,
                                 limit: int = 50, ctx: Context = None) -> dict:
    """
    Find other tracked wallets that share traded tokens with the given wallet
    over the last 30 days, ranked by number of shared tokens.

    blockchain: solana, bnb, base or eth
    address: the source wallet address
    limit: max connections to return (default 50)
    """
    return await _get("/v1/wallets/connections", {
        "blockchain": blockchain, "address": address, "limit": limit,
    }, ctx)


if __name__ == "__main__":

    mcp.settings.host = os.environ.get("MCP_HOST", "0.0.0.0")

    mcp.settings.port = int(os.environ.get("MCP_PORT", "8081"))

    # DNS-Rebinding-Schutz: öffentlichen Host explizit erlauben

    mcp.settings.transport_security.allowed_hosts = ["mcp.cabalspy.xyz", "localhost", "127.0.0.1"]

    mcp.settings.transport_security.allowed_origins = ["https://mcp.cabalspy.xyz"]

    mcp.run(transport="streamable-http")
