#!/usr/bin/env python3
# cabalspy_mcp.py
# ═══════════════════════════════════════════════════════════════════════════════
# CabalSpy MCP server — mcp.cabalspy.xyz
#
# Wraps the CabalSpy /v1 API as MCP tools so AI assistants (Claude, Cursor, and
# anything else that speaks MCP) can query live wallet data in plain language.
#
# This server only calls the existing REST API. It contains no business logic of
# its own; it is a thin, careful client in front of it.
#
# AUTH (per user): every user supplies their own CabalSpy key, sent by the MCP
# client as an HTTP header:
#       X-CabalSpy-Key: <key>
#   (Fallback: CABALSPY_API_KEY in the environment, for single-user or demo use.)
# Users without a key get the dashboard and pricing links from `get_started`.
#
# Transport: Streamable HTTP, behind nginx for TLS.
#
#   pip install "mcp[cli]" httpx
#   MCP_PORT=8081 python3 cabalspy_mcp.py
#   → http://0.0.0.0:8081/mcp
#
# ── WHY THE RESPONSES ARE TRIMMED ─────────────────────────────────────────────
# A 30-day wallet report from this API can carry more than 70,000 values. Handing
# that to a model costs a fortune, overruns the context window, and does not help
# it answer anything. Every response therefore goes through `_compact`, which cuts
# long lists and states in the payload that it did so — otherwise a model assumes
# it saw everything and reasons from a partial picture without knowing it.
# ═══════════════════════════════════════════════════════════════════════════════

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP

try:
    from mcp.types import ToolAnnotations
except ImportError:  # older mcp releases
    ToolAnnotations = None

API_BASE = os.environ.get("CABALSPY_API_BASE", "https://api.cabalspy.xyz")
ENV_KEY = os.environ.get("CABALSPY_API_KEY", "")  # fallback for demo/single user
TIMEOUT = 30.0

PRICING_URL = "https://cabalspy.xyz/pricing"
DASHBOARD_URL = "https://apidashboard.cabalspy.xyz/"
DOCS_URL = "https://docs.cabalspy.xyz"

CHAINS = ["solana", "bnb", "base", "eth", "rh"]
WALLET_TYPES_BY_CHAIN = {
    "solana": ["kol", "smart", "whale"],
    "bnb": ["kol", "smart"],
    "base": ["kol", "smart"],
    "eth": ["kol"],
    "rh": ["kol", "smart"],
}

#: Every tool here only reads; the API has no write endpoints. Falls back to a
#: plain dict, and finally to None, so an older mcp release cannot break startup.
if ToolAnnotations is not None:
    READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
else:
    READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}

def tool(**kwargs):
    """Registers a tool, degrading gracefully if the installed mcp release does
    not support annotations. Keeps an older deployment from failing at import."""
    try:
        return mcp.tool(**kwargs)
    except TypeError:
        kwargs.pop("annotations", None)
        return mcp.tool(**kwargs)


mcp = FastMCP(
    "CabalSpy",
    stateless_http=True,
    json_response=True,
    instructions=(
        "CabalSpy tracks labeled crypto wallets — key opinion leaders (KOLs), smart money "
        "and whales — across Solana, BNB Chain, Base, Ethereum and Robinhood Chain (rh). "
        "The tools cover wallets, tokens, the live trade feed, cluster signals, aggregate "
        "analytics and Jito bundle detection.\n\n"
        "Each user supplies their own CabalSpy API key through the 'X-CabalSpy-Key' header. "
        "If a tool returns an auth error, call 'get_started' for a free test key.\n\n"
        "Three things worth knowing before interpreting results:\n"
        "1. Market cap, price and unrealized PnL are returned for Solana only. On bnb, base, "
        "eth and rh those fields are null by design; realized PnL, invested amounts and "
        "holdings work everywhere.\n"
        "2. 'realized_pnl' is sales minus purchases. A wallet still holding everything it "
        "bought reports its whole investment as a loss at -100 percent. Check 'still_holding' "
        "before calling that a loss.\n"
        "3. Responses are trimmed to fit a context window. When a payload says entries were "
        "omitted, they were — narrow the query rather than assuming you saw everything."
    ),
)


# ═══════════════════════════════════════════════════════════════════════════
#  RESPONSE COMPACTION
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_MAX_ITEMS = 15
MAX_CHARS = 40_000

#: Fields that cost tokens and tell a model nothing.
NOISE_KEYS = {"copytrade_link", "image_url"}


def _trim(value: Any, max_items: int, depth: int = 0) -> Any:
    if depth > 12 or value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        kept = [_trim(v, max_items, depth + 1) for v in value[:max_items]]
        if len(value) > max_items:
            kept.append(
                f"… {len(value) - max_items} more of {len(value)} omitted to fit the context"
            )
        return kept
    if isinstance(value, dict):
        return {
            k: _trim(v, max_items, depth + 1)
            for k, v in value.items()
            if k not in NOISE_KEYS
        }
    return str(value)


def _compact(data: Any, max_items: int = DEFAULT_MAX_ITEMS) -> Any:
    """Returns the payload whole when it fits, and trims progressively when not.

    Trimming eagerly would damage small responses for no reason: a 30 entry PnL
    chart loses its shape if it is cut to 15 for a payload that was never too big
    in the first place. So the full payload is measured first, and only a genuine
    overrun triggers the cut.
    """
    for items in (None, max_items, 8, 4, 2, 1):
        trimmed = _trim(data, items if items is not None else 10**9)
        size = len(json.dumps(trimmed, default=str))
        if size <= MAX_CHARS:
            if items is not None and isinstance(trimmed, dict):
                trimmed["_note"] = (
                    f"Lists were shortened to {items} entries each so the response fits. "
                    "Ask for a narrower period or a smaller limit to see more per item."
                )
            return trimmed
    return {
        "_note": (
            "The response was too large to return even heavily trimmed. Narrow the request: "
            "a shorter period, a smaller limit, or a single wallet or token."
        ),
        "preview": json.dumps(_trim(data, 1), default=str)[:8000],
    }


# ═══════════════════════════════════════════════════════════════════════════
#  HTTP
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_key(ctx: Context | None) -> str:
    """Key from the 'X-CabalSpy-Key' header, falling back to the environment."""
    try:
        req = ctx.request_context.request if ctx else None
        if req is not None:
            hdr = req.headers.get("x-cabalspy-key")
            if hdr:
                return hdr.strip()
    except Exception:
        pass
    return ENV_KEY


_NO_KEY = {
    "error": "missing_api_key",
    "message": (
        "No CabalSpy API key provided. Set the 'X-CabalSpy-Key' header in your MCP client "
        "config. A free test key with 1000 requests is available — call 'get_started'."
    ),
    "get_test_key": DASHBOARD_URL,
    "pricing": PRICING_URL,
}

_AUTH_FAILED = {
    "error": "auth_failed",
    "message": (
        "The CabalSpy API key is invalid or out of credits. Get a free test key with 1000 "
        "requests, or view the plans — call 'get_started' for the links."
    ),
    "get_test_key": DASHBOARD_URL,
    "pricing": PRICING_URL,
}


async def _request(
    method: str,
    path: str,
    ctx: Context | None,
    params: dict | None = None,
    body: dict | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict:
    """Calls a v1 endpoint with the user's key and trims the result."""
    key = _resolve_key(ctx)
    if not key:
        return _NO_KEY

    clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    # The key goes in the Authorization header, not the query string: query
    # parameters end up in nginx access logs, proxy logs and browser history.
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "cabalspy-mcp/2.0",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if method == "POST":
                r = await client.post(f"{API_BASE}{path}", json=body, headers=headers)
            else:
                r = await client.get(f"{API_BASE}{path}", params=clean, headers=headers)
    except httpx.TimeoutException:
        return {"error": "timeout", "message": f"CabalSpy did not respond within {TIMEOUT:.0f}s."}
    except Exception as exc:
        return {"error": "request_failed", "detail": str(exc)[:200]}

    if r.status_code in (401, 403):
        try:
            code = r.json().get("error", {}).get("code", "")
        except Exception:
            code = ""
        if code == "insufficient_credits":
            return {**_AUTH_FAILED, "error": "insufficient_credits",
                    "message": "This CabalSpy API key has no credits left. Top up or upgrade."}
        return _AUTH_FAILED

    if r.status_code == 404:
        return {
            "error": "not_found",
            "message": (
                "Not tracked by CabalSpy. This is not the same as the wallet or token not "
                "existing onchain — CabalSpy only covers labeled wallets."
            ),
        }
    if r.status_code == 429:
        return {"error": "rate_limited",
                "message": "Rate limit reached. Wait a moment before retrying.",
                "retry_after_seconds": r.headers.get("Retry-After")}
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
        except Exception:
            err = {}
        return {
            "error": err.get("code", f"http_{r.status_code}"),
            "message": err.get("message", r.text[:300]),
            "parameter": err.get("parameter"),
            "allowed": err.get("allowed"),
        }

    try:
        payload = r.json()
    except Exception:
        return {"error": "bad_response", "detail": r.text[:300]}

    data = payload.get("data", payload)
    result = _compact(data, max_items)
    if isinstance(result, dict) and isinstance(payload.get("pagination"), dict):
        result["pagination"] = payload["pagination"]
    return result


def _check_type(chain: str, wallet_type: str | None) -> dict | None:
    """Rejects impossible chain and wallet type pairs before spending a request."""
    if chain not in CHAINS:
        return {"error": "invalid_parameter", "parameter": "blockchain",
                "message": f"Unknown blockchain '{chain}'.", "allowed": CHAINS}
    if wallet_type and wallet_type not in WALLET_TYPES_BY_CHAIN[chain]:
        return {"error": "invalid_parameter", "parameter": "type",
                "message": f"{chain} has no {wallet_type} wallets.",
                "allowed": WALLET_TYPES_BY_CHAIN[chain]}
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  ONBOARDING
# ═══════════════════════════════════════════════════════════════════════════


@tool(annotations=READ_ONLY)
async def get_started() -> dict:
    """
    How to use CabalSpy: where to get a free API key (1000 requests, no cost),
    pricing, documentation, and what the data covers. Call this first if you do
    not have a key yet, or if another tool returned an auth error.
    """
    return {
        "what_is_cabalspy": (
            "CabalSpy tracks labeled crypto wallets — KOLs, smart money and whales — across "
            "Solana, BNB Chain, Base, Ethereum and Robinhood Chain, with realized PnL, win "
            "rates, lifetime history, live holdings, cluster signals and Jito bundle detection."
        ),
        "free_test_key": {"url": DASHBOARD_URL,
                          "details": "Create a free test key with 1000 requests at no cost."},
        "pricing": PRICING_URL,
        "docs": DOCS_URL,
        "how_to_set_key": (
            "Add 'X-CabalSpy-Key: <your-key>' to the headers in your MCP client's server "
            "config, then call any data tool."
        ),
        "chains": CHAINS,
        "wallet_types_by_chain": WALLET_TYPES_BY_CHAIN,
        "periods": ["6h", "1d", "7d", "30d"],
        "good_first_questions": [
            "Who are the best performing Solana KOLs this week?",
            "What are KOLs buying right now?",
            "Was this token launch bundled?",
            "Who is still holding this token and who already sold?",
        ],
        "data_caveats": {
            "market_cap": "Returned for Solana only. Null on bnb, base, eth and rh.",
            "realized_pnl": (
                "Sales minus purchases. A wallet that has not sold yet shows its full "
                "investment as a loss. Check 'still_holding' first."
            ),
            "lookup_wallet": (
                "On EVM chains the same address can be tracked on several of them; only the "
                "first match is returned, so the reported chain may not be the intended one."
            ),
        },
    }


@tool(annotations=READ_ONLY)
async def get_api_status(ctx: Context = None) -> dict:
    """
    Service health and current coverage: chains, wallet types, periods, limits and
    how many wallets are tracked per chain. Useful when a query returns nothing and
    it is unclear whether the data exists at all.
    """
    health = await _request("GET", "/v1/health", ctx)
    meta = await _request("GET", "/v1/meta", ctx)
    return {"health": health, "coverage": meta,
            "chains_and_wallet_types": WALLET_TYPES_BY_CHAIN}


# ═══════════════════════════════════════════════════════════════════════════
#  WALLETS
# ═══════════════════════════════════════════════════════════════════════════


@tool(annotations=READ_ONLY)
async def lookup_wallet(address: str, ctx: Context = None) -> dict:
    """
    Identify a wallet address: is it tracked, and by what name. Returns the label
    CabalSpy attached to it — name, Twitter, Telegram, wallet type and chain.
    Start here when a user pastes an address and asks who it is.

    On EVM chains the same address can be tracked on several of them and only the
    first match is returned, so the reported chain may not be the intended one.

    address: the wallet address to look up
    """
    return await _request("GET", "/v1/wallets/lookup", ctx, {"address": address})


@tool(annotations=READ_ONLY)
async def get_wallet_tracker(blockchain: str, address: str, period: str = "1d",
                             ctx: Context = None) -> dict:
    """
    Period statistics for ONE wallet: realized PnL, win rate, volume, trade counts,
    active tokens and win-rate distribution. The main tool for "how is this trader
    doing".

    blockchain: solana, bnb, base, eth or rh
    address: the wallet address
    period: 6h, 1d, 7d or 30d (default 1d). Longer periods return far more data
            and are trimmed harder; prefer the shortest period that answers it.
    """
    if bad := _check_type(blockchain, None):
        return bad
    return await _request("GET", "/v1/wallet/tracking", ctx,
                          {"blockchain": blockchain, "address": address, "period": period})


@tool(annotations=READ_ONLY)
async def get_leaderboard(blockchain: str, wallet_type: str = "kol", period: str = "1d",
                          limit: int = 20, ctx: Context = None) -> dict:
    """
    Top tracked wallets ranked by performance for a chain, wallet type and period.
    Use for "best Solana KOLs today", "top whales this week", and similar.

    blockchain: solana, bnb, base, eth or rh
    wallet_type: kol, smart or whale. whale is Solana only, eth has kol only.
    period: 6h, 1d, 7d or 30d (default 1d)
    limit: how many wallets (default 20)
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    return await _request("GET", "/v1/wallet/leaderboard", ctx,
                          {"blockchain": blockchain, "type": wallet_type,
                           "period": period, "limit": limit})


@tool(annotations=READ_ONLY)
async def list_wallets(blockchain: str, wallet_type: str, limit: int = 50,
                       cursor: str = "", ctx: Context = None) -> dict:
    """
    Browse the wallets CabalSpy tracks for a chain and wallet type. Use this to
    answer which KOLs or smart money wallets are covered at all. Always pass a
    limit; the full list runs into the thousands.

    blockchain: solana, bnb, base, eth or rh
    wallet_type: kol, smart or whale
    limit: wallets per page (default 50)
    cursor: pagination cursor from the previous response
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    return await _request("GET", "/v1/wallets", ctx,
                          {"blockchain": blockchain, "type": wallet_type,
                           "limit": limit, "cursor": cursor})


@tool(annotations=READ_ONLY)
async def get_wallet_history(blockchain: str, address: str, cursor: str = "",
                             limit: int = 50, ctx: Context = None) -> dict:
    """
    Lifetime trading history of a wallet: aggregate stats, a per-token overview and
    the individual trades. Use for what a wallet traded historically, rather than
    how it is doing now.

    This endpoint returns its pagination inside the payload rather than alongside
    it; follow pagination.next_cursor until it is null for a full export.

    blockchain: solana, bnb, base, eth or rh
    address: the wallet address
    cursor: pagination cursor from the previous response
    limit: trades per page, 1-1000 (default 50; higher values get trimmed anyway)
    """
    if bad := _check_type(blockchain, None):
        return bad
    return await _request("GET", "/v1/wallets/history", ctx,
                          {"blockchain": blockchain, "address": address,
                           "cursor": cursor, "limit": min(limit, 200)})


@tool(annotations=READ_ONLY)
async def get_wallet_holdings(blockchain: str, address: str, ctx: Context = None) -> dict:
    """
    Current onchain token holdings of a wallet, read live rather than derived from
    tracked trades. Slower than the other wallet tools, often over a second. If
    'loading' is true the data is still warming up — call again shortly.

    blockchain: solana, bnb, base, eth or rh
    address: the wallet address
    """
    if bad := _check_type(blockchain, None):
        return bad
    return await _request("GET", "/v1/wallet/holdings", ctx,
                          {"blockchain": blockchain, "address": address})


@tool(annotations=READ_ONLY)
async def get_pnl_calendar(blockchain: str, address: str, ctx: Context = None) -> dict:
    """
    Daily and monthly realized profit and loss for a wallet across its tracked
    history. Use for when a wallet made or lost money, and for spotting streaks.

    blockchain: solana, bnb, base, eth or rh
    address: the wallet address
    """
    if bad := _check_type(blockchain, None):
        return bad
    return await _request("GET", "/v1/wallet/pnl_calendar", ctx,
                          {"blockchain": blockchain, "address": address})


@tool(annotations=READ_ONLY)
async def get_wallet_connections(blockchain: str, address: str, limit: int = 25,
                                 ctx: Context = None) -> dict:
    """
    Other tracked wallets that traded the same tokens as this one over the last 30
    days, ranked by overlap. Useful for finding groups that move together, which
    can indicate coordination.

    blockchain: solana, bnb, base, eth or rh
    address: the source wallet address
    limit: how many connections (default 25)
    """
    if bad := _check_type(blockchain, None):
        return bad
    return await _request("GET", "/v1/wallets/connections", ctx,
                          {"blockchain": blockchain, "address": address, "limit": limit})


@tool(annotations=READ_ONLY)
async def compare_wallets(blockchain: str, addresses: list[str], wallet_type: str = "kol",
                          period: str = "7d", ctx: Context = None) -> dict:
    """
    Statistics for up to 100 wallets in a single request. Much cheaper than calling
    get_wallet_tracker repeatedly. Use when the user names several wallets, or to
    follow up on a leaderboard.

    blockchain: solana, bnb, base, eth or rh
    addresses: up to 100 wallet addresses
    wallet_type: kol, smart or whale (default kol)
    period: 6h, 1d, 7d or 30d (default 7d)
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    if not addresses:
        return {"error": "invalid_parameter", "parameter": "addresses",
                "message": "Provide at least one address."}
    if len(addresses) > 100:
        return {"error": "invalid_parameter", "parameter": "addresses",
                "message": f"At most 100 addresses per request, received {len(addresses)}."}
    return await _request("POST", "/v1/wallets/batch", ctx, body={
        "blockchain": blockchain, "type": wallet_type, "addresses": addresses,
        "period": period, "fields": ["profile", "period_stats"]})


# ═══════════════════════════════════════════════════════════════════════════
#  TOKENS
# ═══════════════════════════════════════════════════════════════════════════


@tool(annotations=READ_ONLY)
async def get_token_stats(blockchain: str, mint: str, wallet_type: str = "",
                          ctx: Context = None) -> dict:
    """
    Who is trading a token: how many KOLs, smart money wallets and whales hold it,
    total bought and sold, buying pressure, first and latest entry, and the
    individual traders with their positions. The main tool for "is anyone notable
    in this token".

    Note that market cap in USD comes back empty on this endpoint even for Solana;
    get_token_holders reports it.

    blockchain: solana, bnb, base, eth or rh
    mint: token mint address on Solana, contract address on the EVM chains
    wallet_type: restrict to kol, smart or whale. Omit to merge all types.
    """
    if bad := _check_type(blockchain, wallet_type or None):
        return bad
    return await _request("GET", "/v1/tokens/stats", ctx,
                          {"blockchain": blockchain, "mint": mint, "type": wallet_type})


@tool(annotations=READ_ONLY)
async def get_token_holders(blockchain: str, mint: str, wallet_type: str = "",
                            limit: int = 25, ctx: Context = None) -> dict:
    """
    The tracked wallets holding a token, sorted by balance, with market cap and
    price in USD on Solana. Use when the user asks who is still holding, rather
    than who ever traded it.

    blockchain: solana, bnb, base, eth or rh
    mint: token address
    wallet_type: restrict to kol, smart or whale. Omit to merge all types.
    limit: how many holders (default 25)
    """
    if bad := _check_type(blockchain, wallet_type or None):
        return bad
    return await _request("GET", "/v1/tokens/holders", ctx,
                          {"blockchain": blockchain, "mint": mint,
                           "type": wallet_type, "limit": limit})


@tool(annotations=READ_ONLY)
async def get_token_transactions(blockchain: str, mint: str, wallet_type: str = "",
                                 limit: int = 25, ctx: Context = None) -> dict:
    """
    Individual buys and sells by tracked wallets in one token, most recent first.
    Use for the sequence of events, for example whether KOLs bought before or after
    a price move.

    blockchain: solana, bnb, base, eth or rh
    mint: token address
    wallet_type: restrict to kol, smart or whale. Omit to merge all types.
    limit: how many transactions (default 25)
    """
    if bad := _check_type(blockchain, wallet_type or None):
        return bad
    return await _request("GET", "/v1/tokens/transactions", ctx,
                          {"blockchain": blockchain, "mint": mint,
                           "type": wallet_type, "limit": limit})


@tool(annotations=READ_ONLY)
async def compare_tokens(blockchain: str, mints: list[str], wallet_type: str = "kol",
                         ctx: Context = None) -> dict:
    """
    Statistics for up to 100 tokens in a single request. Use for shortlists, or to
    follow up on the most-traded analytics view.

    blockchain: solana, bnb, base, eth or rh
    mints: up to 100 token addresses
    wallet_type: kol, smart or whale (default kol)
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    if not mints:
        return {"error": "invalid_parameter", "parameter": "mints",
                "message": "Provide at least one token address."}
    if len(mints) > 100:
        return {"error": "invalid_parameter", "parameter": "mints",
                "message": f"At most 100 tokens per request, received {len(mints)}."}
    return await _request("POST", "/v1/tokens/batch", ctx, body={
        "blockchain": blockchain, "type": wallet_type, "mints": mints,
        "fields": ["token", "total_holders", "total_statistics"]})


@tool(annotations=READ_ONLY)
async def detect_bundles(mint: str, ctx: Context = None) -> dict:
    """
    Check whether KOL wallets bought a Solana token through Jito bundles together
    with side wallets they control, which hides the real size of their position.

    Returns each detected bundle with a confidence score and the evidence behind
    it: matching transaction fees, block index, and adjacency to the KOL's own
    transaction. Use this when a user asks whether a launch was bundled,
    insider-heavy, sniped or manipulated.

    Solana only, because it depends on Jito bundles.

    mint: the Solana token mint address
    """
    return await _request("GET", "/v1/bundle", ctx,
                          {"blockchain": "solana", "mint": mint}, max_items=10)


# ═══════════════════════════════════════════════════════════════════════════
#  LIVE FEED, SIGNALS, ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════


@tool(annotations=READ_ONLY)
async def get_recent_trades(blockchain: str, wallet_type: str = "kol", minutes: int = 0,
                            mint: str = "", limit: int = 25, ctx: Context = None) -> dict:
    """
    The live feed: what tracked wallets are buying and selling right now, across
    every token or filtered to one. Use for "what are KOLs buying at the moment".

    blockchain: solana, bnb, base, eth or rh
    wallet_type: kol, smart or whale (default kol)
    minutes: only trades from the last N minutes, at most 60. Leave at 0 for the
             most recent trades regardless of age.
    mint: restrict to one token
    limit: how many trades (default 25)
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    params = {"blockchain": blockchain, "type": wallet_type, "mint": mint, "limit": limit}
    if minutes and minutes > 0:
        params["minutes"] = min(minutes, 60)
        return await _request("GET", "/v1/transactions/timerange", ctx, params)
    return await _request("GET", "/v1/transactions/latest", ctx, params)


@tool(annotations=READ_ONLY)
async def get_activity_metrics(blockchain: str, wallet_type: str = "kol", hours: int = 1,
                               mint: str = "", ctx: Context = None) -> dict:
    """
    How many trades happened and how much value moved over a window of up to 24
    hours, plus how many distinct wallets were involved. Use for how busy the
    market or a single token is, rather than for the individual trades.

    blockchain: solana, bnb, base, eth or rh
    wallet_type: kol, smart or whale (default kol)
    hours: window in hours, at most 24 (default 1)
    mint: restrict to one token
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    params = {"blockchain": blockchain, "type": wallet_type,
              "hours": min(hours, 24), "mint": mint}
    count = await _request("GET", "/v1/transactions/count", ctx, params)
    volume = await _request("GET", "/v1/transactions/volume", ctx, params)
    return {"count": count, "volume": volume}


@tool(annotations=READ_ONLY)
async def get_signals(blockchain: str, wallet_type: str = "kol", mode: str = "cluster",
                      hours: int = 6, min_wallets: int = 0, min_win_rate: float = 0,
                      limit: int = 15, ctx: Context = None) -> dict:
    """
    Tokens where several tracked wallets acted within the same window.

    'cluster' means multiple wallets bought the same token, which is the strongest
    signal. 'entry' marks fresh positions, 'exit' marks wallets selling out. Use
    this for "what should I be looking at right now".

    Only the first page is reachable: this endpoint reports that more results
    exist but does not return a usable cursor, so raise the limit rather than
    trying to paginate. Smart money signals are unavailable on eth.

    blockchain: solana, bnb, base, eth or rh
    wallet_type: kol, smart or whale (default kol)
    mode: cluster, entry or exit (default cluster)
    hours: observation window (default 6)
    min_wallets: minimum wallets in a cluster; higher means fewer, stronger signals
    min_win_rate: only count wallets above this historical win rate, 0-100
    limit: how many signals (default 15)
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    if wallet_type == "smart" and blockchain == "eth":
        return {"error": "invalid_parameter", "parameter": "wallet_type",
                "message": "Smart money signals are not available on eth; it tracks kol only.",
                "allowed": ["kol"]}
    params = {"blockchain": blockchain, "type": wallet_type, "mode": mode,
              "hours": hours, "limit": limit}
    if min_wallets:
        params["min_wallets"] = min_wallets
    if min_win_rate:
        params["min_win_rate"] = min_win_rate
    # Signals nest deeply: fewer entries, more room per entry.
    return await _request("GET", "/v1/signals", ctx, params, max_items=6)


@tool(annotations=READ_ONLY)
async def get_signal_history(blockchain: str, wallet_type: str = "kol", days: str = "30",
                             mode: str = "", limit: int = 25, ctx: Context = None) -> dict:
    """
    Past signals, for checking whether a kind of signal has worked historically
    before acting on a live one.

    blockchain: solana, bnb, base, eth or rh
    wallet_type: kol, smart or whale (default kol)
    days: 7, 30, 90 or "all" (default 30)
    mode: cluster, entry or exit. Omit for all modes.
    limit: how many signals (default 25)
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    return await _request("GET", "/v1/signals/history", ctx,
                          {"blockchain": blockchain, "type": wallet_type,
                           "days": days, "mode": mode, "limit": limit}, max_items=8)


@tool(annotations=READ_ONLY)
async def get_analytics(blockchain: str, mode: str, wallet_type: str = "kol",
                        period: str = "7d", limit: int = 20, ctx: Context = None) -> dict:
    """
    Four aggregate views over the tracked wallets.

    volume_trend shows activity over time. most_traded lists the tokens getting the
    most attention. win_rate gives the distribution of outcomes. top_performers
    ranks wallets by profit. Use for the overall picture rather than one wallet or
    token.

    blockchain: solana, bnb, base, eth or rh
    mode: volume_trend, most_traded, win_rate or top_performers
    wallet_type: kol, smart or whale (default kol)
    period: 6h, 1d, 7d or 30d (default 7d)
    limit: how many entries (default 20)
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    valid = ["volume_trend", "most_traded", "win_rate", "top_performers"]
    if mode not in valid:
        return {"error": "invalid_parameter", "parameter": "mode",
                "message": f"Unknown analytics mode '{mode}'.", "allowed": valid}
    return await _request("GET", "/v1/analytics", ctx,
                          {"blockchain": blockchain, "type": wallet_type,
                           "mode": mode, "period": period, "limit": limit})


# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.settings.host = os.environ.get("MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.environ.get("MCP_PORT", "8081"))
    # DNS rebinding protection: allow the public host explicitly.
    mcp.settings.transport_security.allowed_hosts = [
        "mcp.cabalspy.xyz", "localhost", "127.0.0.1",
    ]
    mcp.settings.transport_security.allowed_origins = ["https://mcp.cabalspy.xyz"]
    mcp.run(transport="streamable-http")
