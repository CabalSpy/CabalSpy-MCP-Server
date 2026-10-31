#!/usr/bin/env python3
# cabalspy_mcp.py
# ═══════════════════════════════════════════════════════════════════════════════
# CabalSpy MCP server — mcp.cabalspy.xyz
#
# Wraps the CabalSpy /v1 API and the CabalSpy ID (CSID) APIs as MCP tools so AI
# assistants (Claude, Cursor, and anything else that speaks MCP) can query live
# wallet data, verified trader identities and token theses in plain language.
#
# This server only calls the existing REST API. It contains no business logic of
# its own; it is a thin, careful client in front of it.
#
# AUTH (per user): every user supplies their own CabalSpy key, sent by the MCP
# client as an HTTP header:
#       X-CabalSpy-Key: <key>
#   (Fallback: CABALSPY_API_KEY in the environment, for single-user use.)
# Users without a key run on the public demo key (20 requests per IP per day,
# data 15 minutes delayed); `get_started` has the links to a free test key.
#
# Transport: Streamable HTTP, behind nginx for TLS.
#
#   pip install "mcp[cli]" httpx
#   MCP_PORT=8081 python3 cabalspy_mcp.py
#   → http://0.0.0.0:8081/mcp
#
# ── SHAPING RESPONSES FOR A MODEL ─────────────────────────────────────────────
# CabalSpy returns depth: a 30-day wallet report covers every token touched, every
# trade and the full PnL curve. A language model works inside a context window, so
# `_compact` delivers that depth in a readable shape — summary blocks complete,
# long detail lists shortened, and the payload stating how many entries it left
# out so a model never mistakes an excerpt for the whole picture. Callers who want
# every row use the SDKs or the REST API.
# ═══════════════════════════════════════════════════════════════════════════════

import json
import os
from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

try:
    from mcp.types import ToolAnnotations
except ImportError:  # older mcp releases
    ToolAnnotations = None

API_BASE = os.environ.get("CABALSPY_API_BASE", "https://api.cabalspy.xyz")
ENV_KEY = os.environ.get("CABALSPY_API_KEY", "")  # fallback for demo/single user
#: Used when a caller brings no key at all, so an agent can try every tool before
#: anyone signs up. The API applies the demo rules: 20 requests per IP per day,
#: events delayed 15 minutes, at most 5 rows per list.
DEMO_KEY = os.environ.get("CABALSPY_DEMO_KEY", "demo")
#: The CabalSpy ID Data API (theses, CSID leaderboards). Same API key as the
#: CabalSpy API; the key's account needs a CabalSpy ID instance.
CSID_API_BASE = os.environ.get("CSID_API_BASE", "https://api-id.cabalspy.xyz")
TIMEOUT = 30.0
VERSION = "2.6.0"

PRICING_URL = "https://www.cabalspy.xyz/pricing/"
DASHBOARD_URL = "https://apidashboard.cabalspy.xyz/"
DOCS_URL = "https://docs.cabalspy.xyz"
WEBSITE_URL = "https://www.cabalspy.xyz/mcp/"
TERMINAL_URL = "https://app.cabalspy.xyz/"
CSID_URL = "https://id.cabalspy.xyz/"
CSID_SETUP_URL = "https://apidashboard.cabalspy.xyz/csid"
CSID_DOCS_URL = "https://docs.cabalspy.xyz/cabalspy-id"

#: Set by the tests to an httpx.MockTransport; None in production.
_TRANSPORT = None

CHAINS = ["solana", "bnb", "base", "eth", "rh"]
WALLET_TYPES_BY_CHAIN = {
    "solana": ["kol", "smart", "whale"],
    "bnb": ["kol", "smart"],
    "base": ["kol", "smart"],
    "eth": ["kol", "smart"],
    "rh": ["kol", "smart"],
}

#: Every tool here only reads (posting theses needs Login with CabalSpy ID and is
#: not offered here). Falls back to a
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
        "analytics and Jito bundle detection. get_calls and get_call_stats cover the curated "
        "CabalSpy calls (the ones posted in Discord) and how well they performed.\n\n"
        "Each user supplies their own CabalSpy API key, either through the 'X-CabalSpy-Key' "
        "header or as an 'api_key' query parameter on the connection URL. Without a key the "
        "tools still work on the public demo: 20 requests per IP per day, data delayed 15 "
        "minutes, at most 5 rows per list. Demo results carry a 'demo' block; say so when "
        "you present them, because they are not live. If a tool returns an auth error or "
        "'demo_limit_reached', call 'get_started' for a free test key.\n\n"
        "Three things worth knowing before interpreting results:\n"
        "1. Market cap, price and unrealized PnL are returned for Solana only. On bnb, base, "
        "eth and rh those fields are null by design; realized PnL, invested amounts and "
        "holdings work everywhere.\n"
        "2. 'realized_pnl' is sales minus purchases. A wallet still holding everything it "
        "bought reports its whole investment as a loss at -100 percent. Check 'still_holding' "
        "before calling that a loss.\n"
        "3. Responses are trimmed to fit a context window. When a payload says entries were "
        "omitted, they were — narrow the query rather than assuming you saw everything.\n"
        "4. Results for a single Solana token carry a 'trade_url': the token page in the "
        "CabalSpy Terminal, where the token can be traded with the same wallet data. Offer it "
        "when the user wants to act on a token.\n\n"
        "CabalSpy ID (CSID), the SocialFi layer: the 'csid_' tools cover verified trader "
        "identities (X account, KOL badge, wallets proven by an on-chain payment), wallet "
        "owners, and token theses — short bull or bear posts by people who hold the token in "
        "a verified wallet, with their live position and PnL. Use csid_profile or "
        "csid_wallet_owner for 'who is this', csid_token_theses for 'what do holders think "
        "about this token'. csid_profile, csid_wallet_owner and csid_kols work on the demo "
        "with sandbox identities only (marked 'sandbox': true; never present them as real "
        "people). The theses and leaderboard tools need the user's own CabalSpy API key with a "
        "CabalSpy ID instance; if they return 'csid_setup_required' or 'no_instance', pass on "
        "the setup link. Platforms that keep their own login (white-label) address their "
        "imported users by their own user id: csid_platform_user, csid_platform_leaderboard "
        "and csid_competitions (trading and callout competitions).\n\n"
        "Callouts (an extra of CabalSpy ID, switched on per instance on request): a user calls "
        "a token, its price and market cap are stamped and tracked (every minute for the first "
        "24 h, then every 5 minutes while active; tracking stops after 24 h in a row below a "
        "$10k market cap). score_x is the peak multiple since the call. csid_callouts lists "
        "callouts (latest, one token, one user), csid_callout_leaderboard ranks the callers "
        "and csid_callout_stats gives one user's track record. If they return "
        "'feature_not_enabled', callouts are not switched on for that instance: pass on the "
        "hint to ask contact@cabalspy.xyz."
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

    Measuring first matters: trimming eagerly would flatten small responses for no
    reason, and a 30 entry PnL chart loses its shape if cut to 15 when it was never
    too large. Only a genuine overrun triggers the cut.
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
    """Resolves the caller's key, in order of preference.

    1. The 'X-CabalSpy-Key' header. Preferred: headers do not end up in logs,
       browser history or referrers. Works in Cursor, VS Code, Claude Desktop
       and anything else with a config file.
    2. An 'api_key' or 'key' query parameter on the connection URL. Needed
       because some clients, claude.ai's web connector among them, offer no way
       to set a custom header and expect OAuth instead. A query parameter is the
       only channel left there.
    3. The environment, for single-user deployments.
    4. The public demo key, so a caller without a key can still try every tool.

    The query parameter is a deliberate compromise, not an oversight: the key
    will appear in the reverse proxy's access log. Keep those logs short, and
    prefer the header wherever the client allows it.
    """
    try:
        req = ctx.request_context.request if ctx else None
        if req is not None:
            hdr = req.headers.get("x-cabalspy-key")
            if hdr:
                return hdr.strip()
            for name in ("api_key", "key", "cabalspy_key"):
                value = req.query_params.get(name)
                if value:
                    return value.strip()
    except Exception:
        pass
    return ENV_KEY or DEMO_KEY


def _caller_ip(ctx: Context | None) -> str | None:
    """The end user's IP, as nginx in front of this server saw it.

    Every call to the API comes from this server, so without it all demo users
    would share one daily budget. The API only believes this header from a
    local connection, which is why CABALSPY_API_BASE points at 127.0.0.1 in
    production.
    """
    try:
        req = ctx.request_context.request if ctx else None
        if req is not None:
            ip = req.headers.get("x-real-ip") or req.headers.get("x-forwarded-for", "").split(",")[0]
            if ip and ip.strip():
                return ip.strip()
            if req.client:
                return req.client.host
    except Exception:
        pass
    return None


_DEMO_LIMIT = {
    "error": "demo_limit_reached",
    "message": (
        "The public demo allows 20 requests per IP per day. Get a free test key with 1000 "
        "real-time requests at no cost, then set it as 'X-CabalSpy-Key' — call "
        "'get_started' for the details."
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


#: CabalSpy ID errors that mean "set up CabalSpy ID first", not "bad key".
_CSID_SETUP_CODES = {"product_not_enabled", "no_instance", "instance_required",
                     "instance_not_found", "instance_forbidden"}
#: 403s that are about what the key may see, not about the key itself. Every
#: other 401/403 (invalid key, no credits) keeps the usual auth answer.
_CSID_PASS_403 = _CSID_SETUP_CODES | {"scope_not_allowed", "plan_user_limit", "feature_not_enabled"}
#: Callouts are an extra that CabalSpy switches on per instance on request.
CALLOUTS_CONTACT = "contact@cabalspy.xyz"


def _csid_error(code: str, message: str, status: int) -> dict:
    """Shapes a CabalSpy ID error so the model can act on it."""
    out = {"error": code or f"http_{status}", "message": message}
    if code in _CSID_SETUP_CODES:
        out["setup_url"] = CSID_SETUP_URL
        out["hint"] = (
            "In the CabalSpy API dashboard, open CabalSpy ID, create an instance (free plan "
            "available) and enable the key for CabalSpy ID. With several instances, pass "
            "'instance' (the instance's client_id)."
        )
    elif code == "feature_not_enabled":
        out["contact"] = CALLOUTS_CONTACT
        out["hint"] = (
            "Callouts (and callout competitions) are an extra of CabalSpy ID that is switched "
            f"on per instance on request. Ask CabalSpy at {CALLOUTS_CONTACT} to enable it for "
            "this instance. Nothing is wrong with the key."
        )
    return out


async def _call(
    method: str,
    path: str,
    ctx: Context | None,
    params: dict | None = None,
    body: dict | None = None,
    base: str | None = None,
    csid: bool = False,
) -> tuple[dict | None, dict | None]:
    """Calls an endpoint with the user's key. Returns (payload, None) on success
    and (None, error) otherwise. csid=True passes CabalSpy ID errors through
    instead of the CabalSpy API's generic wording."""
    key = _resolve_key(ctx)

    clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    # The key goes in the Authorization header, not the query string: query
    # parameters end up in nginx access logs, proxy logs and browser history.
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": f"cabalspy-mcp/{VERSION}",
    }
    base = base or API_BASE
    caller_ip = _caller_ip(ctx)
    if caller_ip and base == API_BASE:
        headers["X-Real-IP"] = caller_ip

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=_TRANSPORT) as client:
            if method == "POST":
                r = await client.post(f"{base}{path}", json=body, headers=headers)
            else:
                r = await client.get(f"{base}{path}", params=clean, headers=headers)
    except httpx.TimeoutException:
        return None, {"error": "timeout", "message": f"CabalSpy did not respond within {TIMEOUT:.0f}s."}
    except Exception as exc:
        return None, {"error": "request_failed", "detail": str(exc)[:200]}

    try:
        err = r.json().get("error", {}) if r.status_code >= 400 else {}
        if not isinstance(err, dict):
            err = {}
    except Exception:
        err = {}
    code = err.get("code", "")

    if code == "demo_limit_reached":
        return None, _DEMO_LIMIT
    if csid and code and (r.status_code in (400, 404) or
                          (r.status_code == 403 and code in _CSID_PASS_403)):
        return None, _csid_error(code, err.get("message", ""), r.status_code)

    if r.status_code in (401, 403):
        if code == "insufficient_credits":
            return None, {**_AUTH_FAILED, "error": "insufficient_credits",
                          "message": "This CabalSpy API key has no credits left. Top up or upgrade."}
        return None, _AUTH_FAILED

    if r.status_code == 404:
        return None, {
            "error": "not_found",
            "message": (
                "Not tracked by CabalSpy. This is not the same as the wallet or token not "
                "existing onchain — CabalSpy only covers labeled wallets."
            ),
        }
    if r.status_code == 429:
        return None, {"error": "rate_limited",
                      "message": "Rate limit reached. Wait a moment before retrying.",
                      "retry_after_seconds": r.headers.get("Retry-After")}
    if r.status_code >= 400:
        return None, {
            "error": code or f"http_{r.status_code}",
            "message": err.get("message", r.text[:300]),
            "parameter": err.get("parameter"),
            "allowed": err.get("allowed"),
        }

    try:
        payload = r.json()
    except Exception:
        return None, {"error": "bad_response", "detail": r.text[:300]}
    if not isinstance(payload, dict):
        payload = {"data": payload}
    return payload, None


async def _request(
    method: str,
    path: str,
    ctx: Context | None,
    params: dict | None = None,
    body: dict | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict:
    """Calls a v1 endpoint with the user's key and trims the result."""
    payload, error = await _call(method, path, ctx, params, body)
    if error:
        return error

    data = payload.get("data", payload)
    result = _compact(data, max_items)
    if isinstance(result, dict) and isinstance(payload.get("pagination"), dict):
        result["pagination"] = payload["pagination"]
    # Demo data is 15 minutes old and capped at 5 rows. The model has to know,
    # or it presents a delayed excerpt as the live picture.
    if isinstance(payload.get("demo"), dict):
        if isinstance(result, dict):
            result["demo"] = payload["demo"]
        else:
            result = {"data": result, "demo": payload["demo"]}
    return result


def _with_trade_url(result: Any, blockchain: str, mint: str) -> Any:
    """Adds the token page in the CabalSpy Terminal to a successful result. Solana only."""
    if isinstance(result, dict) and "error" not in result and blockchain == "solana" and mint:
        result["trade_url"] = f"{TERMINAL_URL}token/{mint}"
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


# ── Parameter types ───────────────────────────────────────────────────────────
# Descriptions attached here end up in each tool's JSON Schema, which is what a
# model reads when deciding how to fill an argument. A description buried in the
# docstring does not: it becomes prose about the tool, not about the parameter.

ChainArg = Annotated[str, Field(description=(
    "Blockchain. One of: solana, bnb, base, eth, rh. solana has kol, smart and whale "
    "wallets; bnb, base, eth and rh have kol and smart. rh is Robinhood "
    "Chain, an Ethereum L2."
))]
WalletTypeArg = Annotated[str, Field(description=(
    "Wallet type. kol is a Key Opinion Leader, an influencer whose calls move markets. "
    "smart is a wallet selected for its track record. whale is a large holder, Solana only."
))]
OptionalWalletTypeArg = Annotated[str, Field(description=(
    "Restrict to one wallet type: kol, smart or whale. Leave empty to merge all types "
    "the chain has."
))]
AddressArg = Annotated[str, Field(description=(
    "Wallet address. Base58 on Solana, 0x-prefixed hex on the EVM chains."
))]
MintArg = Annotated[str, Field(description=(
    "Token address: the mint on Solana, the contract address on the EVM chains."
))]
OptionalMintArg = Annotated[str, Field(description=(
    "Restrict the result to a single token. Leave empty for all tokens."
))]
PeriodArg = Annotated[str, Field(description=(
    "Statistics window: 6h, 1d, 7d or 30d. Longer windows return far more data and get "
    "trimmed harder, so prefer the shortest window that answers the question."
))]
CursorArg = Annotated[str, Field(description=(
    "Pagination cursor taken from the previous response. Leave empty for the first page."
))]
LimitArg = Annotated[int, Field(ge=1, le=200, description=(
    "How many entries to return. Keep it small: large results are trimmed to fit the "
    "context window anyway."
))]
HoursArg = Annotated[int, Field(ge=1, le=24, description=(
    "Observation window in hours. The server caps this at 24."
))]


# ═══════════════════════════════════════════════════════════════════════════
#  ONBOARDING
# ═══════════════════════════════════════════════════════════════════════════


@tool(annotations=READ_ONLY, structured_output=True)
async def get_started() -> dict[str, Any]:
    """
    How to use CabalSpy: the keyless demo, where to get a free API key (1000
    requests, no cost), pricing, documentation, and what the data covers. Call
    this first if you do not have a key yet, or if another tool returned an auth
    error or 'demo_limit_reached'.
    """
    return {
        "what_is_cabalspy": (
            "CabalSpy tracks labeled crypto wallets — KOLs, smart money and whales — across "
            "Solana, BNB Chain, Base, Ethereum and Robinhood Chain, with realized PnL, win "
            "rates, lifetime history, live holdings, cluster signals and Jito bundle detection."
        ),
        "demo": {
            "details": (
                "Every tool works without a key on the public demo: 20 requests per IP per "
                "day, data delayed 15 minutes, at most 5 rows per list. Results then carry a "
                "'demo' block. For live data and more requests, use a free test key."
            ),
            "rest": "https://demo-api.cabalspy.xyz/v1/wallets?blockchain=solana&type=kol",
            "websocket": "wss://demo-api.cabalspy.xyz/ws",
        },
        "free_test_key": {"url": DASHBOARD_URL,
                          "details": "Create a free test key with 1000 requests at no cost."},
        "pricing": PRICING_URL,
        "docs": DOCS_URL,
        "website": WEBSITE_URL,
        "trading_terminal": TERMINAL_URL,
        "how_to_set_key": {
            "clients_with_a_config_file": (
                "Cursor, VS Code, Claude Desktop: add 'X-CabalSpy-Key: <your-key>' to the "
                "headers of the server entry. Preferred, because the key stays out of logs."
            ),
            "clients_without_custom_headers": (
                "claude.ai and anything else that only offers OAuth: append the key to the "
                "connection URL instead, as https://mcp.cabalspy.xyz/mcp?api_key=<your-key>"
            ),
        },
        "chains": CHAINS,
        "wallet_types_by_chain": WALLET_TYPES_BY_CHAIN,
        "periods": ["6h", "1d", "7d", "30d"],
        "good_first_questions": [
            "Who are the best performing Solana KOLs this week?",
            "What are KOLs buying right now?",
            "Was this token launch bundled?",
            "Who is still holding this token and who already sold?",
            "What do verified holders think about $BONK?",
            "Who owns this wallet?",
        ],
        "cabalspy_id": {
            "what": (
                "CabalSpy ID (CSID) is the SocialFi layer for trading platforms: traders sign in "
                "with X, Telegram or Google, verify their wallets with an on-chain payment, and "
                "every trade feeds leaderboards, profiles, KOL badges and token theses (bull or "
                "bear posts that only holders can write, with their live PnL)."
            ),
            "tools": {
                "csid_profile": "who is this trader (handle, id or wallet)",
                "csid_wallet_owner": "who verified this wallet (1-100 addresses)",
                "csid_kols": "verified KOLs, per chain",
                "csid_token_theses": "holder sentiment and theses for one token",
                "csid_latest_theses": "newest theses across tokens",
                "csid_user_theses": "theses of one person",
                "csid_thesis": "one thesis with replies",
                "csid_leaderboard": "your instance's verified traders ranked",
                "csid_platform_user": "white-label: one of your platform's users by your own user id",
                "csid_platform_leaderboard": "white-label: your platform's users ranked",
                "csid_competitions": "white-label: your trading and callout competitions and standings",
                "csid_callouts": "callouts on your instance: latest, for one token or one user",
                "csid_callout_leaderboard": "your best callers per period, scored by peak multiple",
                "csid_callout_stats": "one user's callout track record per period",
            },
            "callouts": (
                "An extra of CabalSpy ID, switched on per instance on request "
                f"({CALLOUTS_CONTACT}). A user calls a token; its price and market cap are "
                "stamped and tracked every minute for the first 24 hours (then scored on "
                "candles), after that every 5 minutes while the token is active. Tracking stops "
                "after 24 hours in a row below a $10k market cap. score_x is the peak multiple. "
                "Without the extra the callout tools return 'feature_not_enabled'."
            ),
            "white_label": (
                "Platforms with their own login import their users and wallets into a CabalSpy "
                "ID instance and get trades, PnL, leaderboards and competitions through "
                "the Data API, without CabalSpy branding. Creating and importing users happens in "
                "the Data API; these tools only read."
            ),
            "demo": (
                "csid_profile, csid_wallet_owner and csid_kols work without a key on sandbox "
                "identities (e.g. username 'csid_sandbox_kol'). Theses and the leaderboard "
                "need your own key with a CabalSpy ID instance."
            ),
            "setup": CSID_SETUP_URL,
            "docs": CSID_DOCS_URL,
            "white_label_docs": f"{CSID_DOCS_URL}/white-label",
            "website": CSID_URL,
        },
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_api_status(ctx: Context = None) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def lookup_wallet(address: AddressArg, ctx: Context = None) -> dict[str, Any]:
    """
    Identify a wallet address: is it tracked, and by what name. Returns the label
    CabalSpy attached to it — name, Twitter, Telegram, wallet type and chain.
    Start here when a user pastes an address and asks who it is.

    On EVM chains the same address can be tracked on several of them and only the
    first match is returned, so the reported chain may not be the intended one.

    address: the wallet address to look up
    """
    return await _request("GET", "/v1/wallets/lookup", ctx, {"address": address})


@tool(annotations=READ_ONLY, structured_output=True)
async def get_wallet_tracker(blockchain: ChainArg, address: AddressArg,
                             period: PeriodArg = "1d",
                             ctx: Context = None) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_leaderboard(blockchain: ChainArg, wallet_type: WalletTypeArg = "kol",
                          period: PeriodArg = "1d", limit: LimitArg = 20,
                          ctx: Context = None) -> dict[str, Any]:
    """
    Top tracked wallets ranked by performance for a chain, wallet type and period.
    Use for "best Solana KOLs today", "top whales this week", and similar.

    blockchain: solana, bnb, base, eth or rh
    wallet_type: kol, smart or whale. whale is Solana only.
    period: 6h, 1d, 7d or 30d (default 1d)
    limit: how many wallets (default 20)
    """
    if bad := _check_type(blockchain, wallet_type):
        return bad
    return await _request("GET", "/v1/wallet/leaderboard", ctx,
                          {"blockchain": blockchain, "type": wallet_type,
                           "period": period, "limit": limit})


@tool(annotations=READ_ONLY, structured_output=True)
async def list_wallets(blockchain: ChainArg, wallet_type: WalletTypeArg,
                       limit: LimitArg = 50, cursor: CursorArg = "",
                       ctx: Context = None) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_wallet_history(blockchain: ChainArg, address: AddressArg,
                             cursor: CursorArg = "", limit: LimitArg = 50,
                             ctx: Context = None) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_wallet_holdings(blockchain: ChainArg, address: AddressArg,
                              ctx: Context = None) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_pnl_calendar(blockchain: ChainArg, address: AddressArg,
                           ctx: Context = None) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_wallet_connections(blockchain: ChainArg, address: AddressArg,
                                 limit: LimitArg = 25,
                                 ctx: Context = None) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def compare_wallets(
    blockchain: ChainArg,
    addresses: Annotated[list[str], Field(max_length=100, description=(
        "Up to 100 wallet addresses. Far cheaper than calling get_wallet_tracker once "
        "per wallet."))],
    wallet_type: WalletTypeArg = "kol",
    period: PeriodArg = "7d",
    ctx: Context = None,
) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_token_stats(blockchain: ChainArg, mint: MintArg,
                          wallet_type: OptionalWalletTypeArg = "",
                          ctx: Context = None) -> dict[str, Any]:
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
    return _with_trade_url(
        await _request("GET", "/v1/tokens/stats", ctx,
                       {"blockchain": blockchain, "mint": mint, "type": wallet_type}),
        blockchain, mint)


@tool(annotations=READ_ONLY, structured_output=True)
async def get_token_holders(blockchain: ChainArg, mint: MintArg,
                            wallet_type: OptionalWalletTypeArg = "",
                            limit: LimitArg = 25,
                            ctx: Context = None) -> dict[str, Any]:
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
    return _with_trade_url(
        await _request("GET", "/v1/tokens/holders", ctx,
                       {"blockchain": blockchain, "mint": mint,
                        "type": wallet_type, "limit": limit}),
        blockchain, mint)


@tool(annotations=READ_ONLY, structured_output=True)
async def get_token_transactions(blockchain: ChainArg, mint: MintArg,
                                 wallet_type: OptionalWalletTypeArg = "",
                                 limit: LimitArg = 25,
                                 ctx: Context = None) -> dict[str, Any]:
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
    return _with_trade_url(
        await _request("GET", "/v1/tokens/transactions", ctx,
                       {"blockchain": blockchain, "mint": mint,
                        "type": wallet_type, "limit": limit}),
        blockchain, mint)


@tool(annotations=READ_ONLY, structured_output=True)
async def compare_tokens(
    blockchain: ChainArg,
    mints: Annotated[list[str], Field(max_length=100, description=(
        "Up to 100 token addresses. Use for shortlists, or to follow up on the "
        "most_traded analytics view."))],
    wallet_type: WalletTypeArg = "kol",
    ctx: Context = None,
) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def detect_bundles(
    mint: Annotated[str, Field(description=(
        "The Solana token mint address to inspect for bundled buys."))],
    ctx: Context = None,
) -> dict[str, Any]:
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
    return _with_trade_url(
        await _request("GET", "/v1/bundle", ctx,
                       {"blockchain": "solana", "mint": mint}, max_items=10),
        "solana", mint)


# ═══════════════════════════════════════════════════════════════════════════
#  LIVE FEED, SIGNALS, ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════


@tool(annotations=READ_ONLY, structured_output=True)
async def get_recent_trades(
    blockchain: ChainArg,
    wallet_type: WalletTypeArg = "kol",
    minutes: Annotated[int, Field(ge=0, le=60, description=(
        "Only trades from the last N minutes, at most 60. Leave at 0 for the most "
        "recent trades regardless of age."))] = 0,
    mint: OptionalMintArg = "",
    limit: LimitArg = 25,
    ctx: Context = None,
) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_activity_metrics(blockchain: ChainArg, wallet_type: WalletTypeArg = "kol",
                               hours: HoursArg = 1, mint: OptionalMintArg = "",
                               ctx: Context = None) -> dict[str, Any]:
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


@tool(annotations=READ_ONLY, structured_output=True)
async def get_signals(
    blockchain: ChainArg,
    wallet_type: WalletTypeArg = "kol",
    mode: Annotated[str, Field(description=(
        "cluster means several wallets bought the same token, the strongest signal. "
        "entry marks fresh positions. exit marks wallets selling out."))] = "cluster",
    hours: Annotated[int, Field(ge=1, le=168, description=(
        "Observation window in hours."))] = 6,
    min_wallets: Annotated[int, Field(ge=0, le=50, description=(
        "Minimum wallets in a cluster. Higher means fewer but stronger signals. "
        "0 uses the server default of 3."))] = 0,
    min_win_rate: Annotated[float, Field(ge=0, le=100, description=(
        "Only count wallets above this historical win rate, 0 to 100. 0 disables it."))] = 0,
    limit: LimitArg = 15,
    ctx: Context = None,
) -> dict[str, Any]:
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
    params = {"blockchain": blockchain, "type": wallet_type, "mode": mode,
              "hours": hours, "limit": limit}
    if min_wallets:
        params["min_wallets"] = min_wallets
    if min_win_rate:
        params["min_win_rate"] = min_win_rate
    # Signals nest deeply: fewer entries, more room per entry.
    return await _request("GET", "/v1/signals", ctx, params, max_items=6)


@tool(annotations=READ_ONLY, structured_output=True)
async def get_signal_history(
    blockchain: ChainArg,
    wallet_type: WalletTypeArg = "kol",
    days: Annotated[str, Field(description=(
        "How far back to look: 7, 30, 90 or all."))] = "30",
    mode: Annotated[str, Field(description=(
        "Restrict to cluster, entry or exit. Leave empty for every mode."))] = "",
    limit: LimitArg = 25,
    ctx: Context = None,
) -> dict[str, Any]:
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


CALL_CHAINS = ["solana", "bnb", "eth", "rh"]
CALL_TIERS = ["gamble", "moderate", "good", "big", "whale"]


def _check_csv(value: str, allowed: list, parameter: str) -> dict | None:
    """Comma separated choices, each from allowed. Empty means all."""
    bad = [v for v in (x.strip().lower() for x in value.split(",")) if v and v not in allowed]
    if bad:
        return {"error": {"code": "invalid_parameter", "parameter": parameter,
                          "message": f"Unknown {parameter} '{bad[0]}'. Allowed: {', '.join(allowed)}."}}
    return None


@tool(annotations=READ_ONLY, structured_output=True)
async def get_calls(
    blockchain: Annotated[str, Field(description=(
        "Comma separated chains: solana, bnb, eth, rh. Empty for all chains."))] = "",
    tier: Annotated[str, Field(description=(
        "Comma separated tiers: gamble, moderate, good, big, whale. Empty for all tiers."))] = "",
    since: Annotated[str, Field(description=(
        "Only calls at or after this time, ISO 8601 or Unix seconds. Empty for no limit."))] = "",
    until: Annotated[str, Field(description=(
        "Only calls at or before this time, ISO 8601 or Unix seconds. Empty for no limit."))] = "",
    limit: LimitArg = 15,
    cursor: CursorArg = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """
    The curated CabalSpy calls, the same ones posted in the CabalSpy Discord, newest
    first. Each call has the token, the market cap at the call, the KOL and Smart
    Money wallets behind it, trading links, and its performance over the 24 hours
    after the call (peak multiple, minutes to peak, multiple after 24 h).

    Use this for "what did CabalSpy call" or "how did the call on this token do".
    These are fixed picks per tier; for wallet clusters with your own thresholds use
    get_signals instead. performance.status 'pending' means the call is younger than
    about two days and not measured yet, which is not a bad result.

    blockchain: solana, bnb, eth, rh, comma separated (default all)
    tier: gamble, moderate, good, big, whale, comma separated (default all)
    since / until: time window, ISO 8601 or Unix seconds
    limit: how many calls (default 15)
    cursor: next_cursor from the previous page
    """
    if bad := _check_csv(blockchain, CALL_CHAINS, "blockchain"):
        return bad
    if bad := _check_csv(tier, CALL_TIERS, "tier"):
        return bad
    return await _request("GET", "/v1/calls", ctx,
                          {"blockchain": blockchain, "tier": tier, "since": since,
                           "until": until, "limit": limit, "cursor": cursor}, max_items=10)


@tool(annotations=READ_ONLY, structured_output=True)
async def get_call_stats(
    period: Annotated[str, Field(description="1d, 7d, 30d or 90d.")] = "7d",
    blockchain: Annotated[str, Field(description=(
        "Comma separated chains: solana, bnb, eth, rh. Empty for all chains."))] = "",
    tier: Annotated[str, Field(description=(
        "Comma separated tiers: gamble, moderate, good, big, whale. Empty for all tiers."))] = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """
    How well the curated CabalSpy calls performed: per chain and tier the number of
    calls, the share that reached 2x, 5x and 10x within 24 hours, the median peak
    multiple and minutes to peak, plus the best calls of the period.

    Use this for "how good are CabalSpy calls" or "which tier works best". Only the
    first call per token, tier and day counts; calls without price data are left out
    of the hit rate. Calls from the last one to two days count as pending.

    period: 1d, 7d, 30d or 90d (default 7d)
    blockchain: solana, bnb, eth, rh, comma separated (default all)
    tier: gamble, moderate, good, big, whale, comma separated (default all)
    """
    if period not in ("1d", "7d", "30d", "90d"):
        return {"error": {"code": "invalid_parameter", "parameter": "period",
                          "message": "period must be one of 1d, 7d, 30d, 90d."}}
    if bad := _check_csv(blockchain, CALL_CHAINS, "blockchain"):
        return bad
    if bad := _check_csv(tier, CALL_TIERS, "tier"):
        return bad
    return await _request("GET", "/v1/calls/stats", ctx,
                          {"period": period, "blockchain": blockchain, "tier": tier})


@tool(annotations=READ_ONLY, structured_output=True)
async def get_analytics(
    blockchain: ChainArg,
    mode: Annotated[str, Field(description=(
        "volume_trend shows activity over time. most_traded lists the tokens getting the "
        "most attention. win_rate gives the distribution of outcomes. top_performers ranks "
        "wallets by profit."))],
    wallet_type: WalletTypeArg = "kol",
    period: PeriodArg = "7d",
    limit: LimitArg = 20,
    ctx: Context = None,
) -> dict[str, Any]:
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
#  CABALSPY ID (CSID) — the SocialFi layer
# ═══════════════════════════════════════════════════════════════════════════
#
# CabalSpy ID links a trader's X account (and Telegram) to the wallets they
# proved with an on-chain payment, gives KOLs a reviewed badge, and lets
# token holders post theses that carry their live position.
#
# Two APIs, one key:
#   * CabalSpy API /v1/csid/*  — profiles, wallet owners, verified KOLs. Works
#     on the keyless demo, answered from sandbox identities only.
#   * CSID Data API (api-id)   — theses and CSID leaderboards. Needs the user's
#     own key, enabled for CabalSpy ID, and a CabalSpy ID instance. No demo.
# The APIs decide what a key may see; these tools never widen it.

CSID_SORTS = ["volume", "pnl", "pnl_usd", "win_rate", "trades"]

_CSID_NEEDS_KEY = {
    "error": "csid_setup_required",
    "message": (
        "Theses and CabalSpy ID leaderboards come from the CabalSpy ID Data API, which has no "
        "keyless demo. It needs your own CabalSpy API key (free) with CabalSpy ID enabled and a "
        "CabalSpy ID instance (free plan available). Set the key as 'X-CabalSpy-Key'. "
        "csid_profile, csid_wallet_owner and csid_kols work without a key on sandbox data."
    ),
    "setup_url": CSID_SETUP_URL,
    "free_test_key": DASHBOARD_URL,
    "docs": CSID_DOCS_URL,
}


def _has_own_key(ctx: Context | None) -> bool:
    return _resolve_key(ctx) != DEMO_KEY


def _resolve_instance(ctx: Context | None, explicit: str | None) -> str | None:
    """The CabalSpy ID instance (client_id) to act as: the tool argument, else
    an 'X-CSID-Instance' header or 'csid_instance' query parameter on the
    connection URL. Only needed when the key's account has several instances."""
    if explicit and explicit.strip():
        return explicit.strip()[:64]
    try:
        req = ctx.request_context.request if ctx else None
        if req is not None:
            value = req.headers.get("x-csid-instance") or req.query_params.get("csid_instance")
            if value and value.strip():
                return value.strip()[:64]
    except Exception:
        pass
    return None


def _drop_empty(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _chain_ids(chains: Any) -> list:
    out = []
    for c in chains or []:
        out.append(c.get("id") if isinstance(c, dict) else c)
    return out


def _slim_wallet(w: dict) -> dict:
    return _drop_empty({"address": w.get("address"), "chains": _chain_ids(w.get("chains")),
                        "verified_at": w.get("verified_at")})


def _slim_profile(p: Any, full: bool = True) -> Any:
    """A CabalSpy ID profile without avatars and duplicate links."""
    if not isinstance(p, dict):
        return p
    x = p.get("x") or {}
    kol = p.get("kol") or {}
    username = p.get("username")
    out = {
        "csid_id": p.get("csid_id"),
        "username": username,
        "name": p.get("name"),
        "kol_badge": bool(kol.get("badge")),
        "kol_since": kol.get("since"),
        "x": _drop_empty({
            "username": x.get("username") or username, "url": x.get("url") or p.get("twitter"),
            "followers": x.get("followers"), "following": x.get("following"),
            "verified": x.get("verified") or None, "account_created": x.get("created_at"),
        }) if x else None,
        "telegram": p.get("telegram"),
        "website": p.get("website"),
        "wallets": [_slim_wallet(w) for w in (p.get("wallets") or [])[:10]],
        "trading_7d": p.get("onchain"),
        "joined_at": p.get("joined_at"),
        "profile_url": p.get("profile_url") or (
            f"{CSID_URL}u/{username}" if username and not p.get("sandbox") else None),
    }
    if full:
        out["bio"] = p.get("bio")
        out["location"] = p.get("location")
    if p.get("sandbox"):
        out["sandbox"] = True
    return _drop_empty(out) | {"kol_badge": out["kol_badge"]}


def _with_demo(result: dict, payload: dict | None) -> dict:
    if payload and isinstance(payload.get("demo"), dict):
        result["demo"] = payload["demo"]
        result["sandbox_note"] = (
            "Demo mode: these are CabalSpy ID sandbox identities, not real people. "
            "Use your own API key for real profiles."
        )
    return result


def _slim_position(pos: Any) -> Any:
    if not isinstance(pos, dict):
        return None
    if pos.get("private"):
        return {"private": True, "note": "Holds the token; keeps trading details private."}
    now = pos.get("now") or {}
    at = pos.get("at_post") or {}
    return _drop_empty({
        "status": now.get("status"),
        "tokens_held": now.get("tokens_held"),
        "tokens_held_at_post": at.get("tokens_held"),
        "invested_usd": now.get("invested_usd"),
        "realized_usd": now.get("realized_usd"),
        "holding_value_usd": now.get("holding_value_usd"),
        "pnl_usd": now.get("pnl_usd"),
        "pnl_percent": now.get("pnl_percent"),
    }) or None


def _slim_author(a: Any) -> dict:
    a = a if isinstance(a, dict) else {}
    return _drop_empty({"username": a.get("username"), "name": a.get("name"),
                        "kol_badge": a.get("kol_badge") or None, "csid_id": a.get("csid_id")})


def _slim_reply(r: dict, body_chars: int = 1000) -> dict:
    body = r.get("body") or ""
    return _drop_empty({
        "id": r.get("id"), "author": _slim_author(r.get("author")),
        "body": body if len(body) <= body_chars else body[:body_chars] + "…",
        "likes": r.get("likes") or None, "created_at": r.get("created_at"),
    })


def _slim_thesis(t: Any, with_token: bool = False) -> Any:
    if not isinstance(t, dict):
        return t
    out = {
        "id": t.get("id"),
        "stance": t.get("stance") or "neutral",
        "body": t.get("body"),
        "author": _slim_author(t.get("author")),
        "position": _slim_position(t.get("position")),
        "likes": t.get("likes"),
        "replies": t.get("replies"),
        "reactions": t.get("reactions") or None,
        "via": t.get("via"),
        "created_at": t.get("created_at"),
    }
    if with_token:
        out["chain"] = t.get("chain")
        out["mint"] = t.get("mint")
    latest = t.get("latest_replies") or []
    if latest:
        out["latest_replies"] = [_slim_reply(r, 280) for r in latest[:3]]
    return _drop_empty(out) | {"likes": out["likes"] or 0, "replies": out["replies"] or 0}


def _next_cursor(payload: dict | None) -> str | None:
    pag = (payload or {}).get("pagination") or {}
    return pag.get("next_cursor") if isinstance(pag, dict) else None


def _check_chain(chain: str, parameter: str = "blockchain") -> dict | None:
    if chain not in CHAINS:
        return {"error": "invalid_parameter", "parameter": parameter,
                "message": f"Unknown blockchain '{chain}'.", "allowed": CHAINS}
    return None


def _check_choice(value: str, allowed: list, parameter: str) -> dict | None:
    if value not in allowed:
        return {"error": "invalid_parameter", "parameter": parameter,
                "message": f"Invalid value '{value}' for {parameter}.", "allowed": allowed}
    return None


# ── Parameter types (CSID) ────────────────────────────────────────────────────

CsidUsernameArg = Annotated[str, Field(description=(
    "X (Twitter) handle of the person, with or without @, e.g. 'CabalSpySol'. "
    "Pass exactly one of username, csid_id, x_id or address."
))]
CsidIdArg = Annotated[str, Field(description=(
    "CabalSpy ID user id (a UUID, the 'sub' of a Login with CabalSpy ID token), e.g. "
    "'123e4567-e89b-12d3-a456-426614174000'."
))]
XIdArg = Annotated[str, Field(description=(
    "Numeric X user id, e.g. '1234567890123456789'. Survives handle changes."
))]
CsidAddressArg = Annotated[str, Field(description=(
    "A wallet address (Solana base58 or 0x EVM). Returns the person who verified it."
))]
OptionalChainArg = Annotated[str, Field(description=(
    "Restrict to one blockchain: solana, bnb, base, eth or rh. Leave empty for all."
))]
ThesisLimitArg = Annotated[int, Field(ge=1, le=25, description=(
    "How many theses to return (1-25, default 10)."
))]
StanceArg = Annotated[str, Field(description=(
    "Only bullish ('bull') or bearish ('bear') theses. Leave empty for all, including "
    "neutral ones."
))]
ThesisSortArg = Annotated[str, Field(description=(
    "'new' (newest first, default) or 'top' (most liked first)."
))]
ThesisScopeArg = Annotated[str, Field(description=(
    "'global' (default): theses posted on every platform that uses CabalSpy ID. "
    "'instance': only theses written on your own CabalSpy ID instance."
))]
InstanceArg = Annotated[str, Field(description=(
    "Your CabalSpy ID instance (its client_id, e.g. 'csid_1a2b…'). Only needed when your "
    "account has several instances. Leave empty otherwise."
))]


# ── Identity ──────────────────────────────────────────────────────────────────


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_profile(username: CsidUsernameArg = "", csid_id: CsidIdArg = "",
                       x_id: XIdArg = "", address: CsidAddressArg = "",
                       ctx: Context = None) -> dict[str, Any]:
    """
    CabalSpy ID profile of a crypto trader: X account (followers, age), Telegram,
    KOL badge, the wallets they verified by an on-chain payment (per chain), and
    7-day trading activity. Use it to check who someone is and whether a trader
    really owns the wallets they claim, e.g. "Is @CabalSpySol verified?",
    "Which wallets does this KOL trade with?".

    Pass exactly one of: username (X handle), csid_id, x_id, or address (looks up
    the owner of a wallet). Works on the keyless demo with sandbox identities only
    (try username 'csid_sandbox_kol').
    """
    given = {k: v.strip() for k, v in
             {"username": username, "csid_id": csid_id, "x_id": x_id, "address": address}.items()
             if v and v.strip()}
    if len(given) != 1:
        return {"error": "invalid_parameter", "parameter": "username|csid_id|x_id|address",
                "message": "Pass exactly one of: username, csid_id, x_id, address."}
    if "address" in given:
        return await _wallet_owner(given["address"], ctx)
    params = {k: (v.lstrip("@") if k == "username" else v) for k, v in given.items()}
    payload, error = await _call("GET", "/v1/csid/profile", ctx, params, csid=True)
    if error:
        if error.get("error") == "profile_not_found":
            error["hint"] = ("This person has no CabalSpy ID (or not under this handle). "
                             "For any labeled wallet, lookup_wallet may still know them.")
        return error
    return _with_demo(_slim_profile(payload.get("data")), payload)


async def _wallet_owner(address: str, ctx: Context | None) -> dict:
    payload, error = await _call("GET", "/v1/csid/wallet", ctx, {"address": address}, csid=True)
    if error:
        if error.get("error") == "wallet_not_found":
            return {"address": address, "verified": False,
                    "message": "No CabalSpy ID user has verified this wallet. It may still be a "
                               "labeled wallet: try lookup_wallet."}
        return error
    d = payload.get("data") or {}
    return _with_demo(_drop_empty({
        "address": d.get("address", address), "verified": True,
        "chains": _chain_ids(d.get("chains")), "verified_at": d.get("verified_at"),
        "owner": _slim_profile(d.get("owner"), full=False),
    }), payload)


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_wallet_owner(
    addresses: Annotated[str, Field(description=(
        "One wallet address, or up to 100 separated by commas (Solana and EVM mixed), "
        "e.g. 'HHTNJXn5zDoVtbnRpYVwr7tKmnMs94cMPsu8gK2aLG9X'."))],
    ctx: Context = None,
) -> dict[str, Any]:
    """
    Who owns a wallet? Returns the CabalSpy ID user who proved ownership with an
    on-chain payment (X handle, KOL badge, verified chains), or verified=false.
    Use it when a user pastes an address and asks who is behind it — e.g. "Who
    owns wallet X?" — and to find verified traders among a token's holders.
    Complements lookup_wallet (CabalSpy's own wallet labels). Several addresses at
    once count as one batch request.
    """
    items = [a.strip() for a in addresses.replace("\n", ",").replace(" ", ",").split(",") if a.strip()]
    if not items:
        return {"error": "missing_parameter", "parameter": "addresses",
                "message": "Pass at least one wallet address."}
    if len(items) > 100:
        return {"error": "invalid_parameter", "parameter": "addresses",
                "message": f"At most 100 addresses per call, got {len(items)}."}
    if len(items) == 1:
        return await _wallet_owner(items[0], ctx)
    payload, error = await _call("POST", "/v1/csid/wallets/lookup", ctx,
                                 body={"addresses": items}, csid=True)
    if error:
        return error
    d = payload.get("data") or {}
    results = []
    for r in d.get("results") or []:
        w = r.get("wallet") or {}
        results.append(_drop_empty({
            "address": r.get("address"), "verified": bool(r.get("verified")),
            "error": r.get("error"), "chains": _chain_ids(w.get("chains")),
            "owner": _slim_profile(w.get("owner"), full=False) if w.get("owner") else None,
        }) | {"verified": bool(r.get("verified"))})
    # Verified first: they are what the caller is looking for.
    results.sort(key=lambda r: not r["verified"])
    return _with_demo(_compact({"checked": d.get("count", len(items)),
                                "verified": d.get("verified"), "results": results}, 25), payload)


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_kols(chain: OptionalChainArg = "",
                    limit: Annotated[int, Field(ge=1, le=50, description=(
                        "How many KOLs to return (1-50, default 20)."))] = 20,
                    cursor: CursorArg = "", ctx: Context = None) -> dict[str, Any]:
    """
    KOLs with a verified CabalSpy ID badge (reviewed: real X account with reach,
    wallets proven on-chain), newest badge first. Each entry has the X handle,
    followers, verified wallets and 7-day activity. Use for "Which KOLs are
    verified on Base?" or to get wallets of verified influencers. For performance
    rankings of tracked KOL wallets use get_leaderboard instead.

    chain: solana, bnb, base, eth or rh — only KOLs with a wallet verified there.
    """
    if chain and (bad := _check_chain(chain, "chain")):
        return bad
    payload, error = await _call("GET", "/v1/csid/kols", ctx,
                                 {"chain": chain, "limit": limit, "cursor": cursor}, csid=True)
    if error:
        return error
    d = payload.get("data") or {}
    kols = [_slim_profile(k, full=False) for k in d.get("kols") or []]
    return _with_demo(_compact(_drop_empty({"count": len(kols), "kols": kols,
                                            "next_cursor": d.get("next_cursor")}) | {"count": len(kols)}),
                      payload)


# ── Theses ────────────────────────────────────────────────────────────────────


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_token_theses(blockchain: ChainArg, mint: MintArg,
                            sort: ThesisSortArg = "new", stance: StanceArg = "",
                            limit: ThesisLimitArg = 10, cursor: CursorArg = "",
                            scope: ThesisScopeArg = "global", instance: InstanceArg = "",
                            ctx: Context = None) -> dict[str, Any]:
    """
    What do verified holders think about a token? Returns the bull/bear summary
    and the latest (or top) theses: short posts that only people holding the token
    in a CabalSpy ID verified wallet can write, each with the author's live
    position (holding or sold, invested, PnL). Use for "What do holders say about
    $BONK?" or "Is sentiment on this token bullish?".

    Needs your own CabalSpy API key with a CabalSpy ID instance (no demo).
    Example: blockchain='solana', mint='DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263'.
    Page with the returned next_cursor.
    """
    if bad := _check_chain(blockchain):
        return bad
    if (bad := _check_choice(sort, ["new", "top"], "sort")) or \
            (stance and (bad := _check_choice(stance, ["bull", "bear"], "stance"))) or \
            (bad := _check_choice(scope, ["global", "instance"], "scope")):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    inst = _resolve_instance(ctx, instance)
    base_params = {"blockchain": blockchain, "mint": mint, "scope": scope, "instance": inst}
    result: dict[str, Any] = {}
    if not cursor:
        summary, error = await _call("GET", "/v1/theses/summary", ctx, base_params,
                                     base=CSID_API_BASE, csid=True)
        if error:
            return error
        s = summary.get("data") or {}
        tok = s.get("token") or {}
        bull, bear = s.get("bull") or 0, s.get("bear") or 0
        result["token"] = _drop_empty({"symbol": tok.get("symbol"), "name": tok.get("name"),
                                       "price_usd": tok.get("price_usd")})
        result["summary"] = {
            "theses": s.get("theses", 0), "authors": s.get("authors", 0),
            "bull": bull, "bear": bear,
            "bull_percent": round(100 * bull / (bull + bear), 1) if bull + bear else None,
        }
    payload, error = await _call("GET", "/v1/theses", ctx,
                                 base_params | {"sort": sort, "stance": stance, "limit": limit,
                                                "cursor": cursor},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    items = payload.get("data") or []
    result["theses"] = [_slim_thesis(t) for t in items]
    if not items and not cursor:
        result["note"] = ("No theses for this token yet. Holders can post one on any platform "
                          f"with the CabalSpy ID thesis widget, or at {CSID_URL}try/thesis.")
    if nxt := _next_cursor(payload):
        result["next_cursor"] = nxt
    return _with_trade_url(_compact(result), blockchain, mint)


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_latest_theses(blockchain: OptionalChainArg = "", limit: ThesisLimitArg = 10,
                             cursor: CursorArg = "",
                             users: Annotated[str, Field(description=(
                                 "'all' (default): every author. 'instance': only users of your "
                                 "CabalSpy ID instance."))] = "all",
                             scope: ThesisScopeArg = "global", instance: InstanceArg = "",
                             ctx: Context = None) -> dict[str, Any]:
    """
    The newest theses across all tokens: a live feed of what verified holders are
    posting, each with token, stance, author and position. Use for "What are
    verified traders talking about right now?" or to discover tokens with fresh
    conviction. For one token use csid_token_theses.

    Needs your own CabalSpy API key with a CabalSpy ID instance (no demo).
    """
    if blockchain and (bad := _check_chain(blockchain)):
        return bad
    if (bad := _check_choice(users, ["all", "instance"], "users")) or \
            (bad := _check_choice(scope, ["global", "instance"], "scope")):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    payload, error = await _call("GET", "/v1/theses/latest", ctx,
                                 {"blockchain": blockchain, "limit": limit, "cursor": cursor,
                                  "users": users, "scope": scope,
                                  "instance": _resolve_instance(ctx, instance)},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    result = {"theses": [_slim_thesis(t, with_token=True) for t in payload.get("data") or []]}
    if nxt := _next_cursor(payload):
        result["next_cursor"] = nxt
    return _compact(result)


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_user_theses(username: Annotated[str, Field(description=(
                               "X handle of the author, with or without @, e.g. 'CabalSpySol'. "
                               "Pass username or csid_id."))] = "",
                           csid_id: CsidIdArg = "", limit: ThesisLimitArg = 10,
                           cursor: CursorArg = "", instance: InstanceArg = "",
                           ctx: Context = None) -> dict[str, Any]:
    """
    All theses one CabalSpy ID user has posted, newest first, with token and the
    position they hold. Use to judge a caller's track record: "What has
    @CabalSpySol been bullish on, and did it work out?".

    Needs your own CabalSpy API key with a CabalSpy ID instance (no demo).
    """
    if bool(username.strip()) == bool(csid_id.strip()):
        return {"error": "invalid_parameter", "parameter": "username|csid_id",
                "message": "Pass exactly one of: username, csid_id."}
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    payload, error = await _call("GET", "/v1/theses/user", ctx,
                                 {"username": username.strip().lstrip("@"), "csid_id": csid_id.strip(),
                                  "limit": limit, "cursor": cursor,
                                  "instance": _resolve_instance(ctx, instance)},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    result = {"theses": [_slim_thesis(t, with_token=True) for t in payload.get("data") or []]}
    if nxt := _next_cursor(payload):
        result["next_cursor"] = nxt
    return _compact(result)


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_thesis(thesis_id: Annotated[str, Field(description=(
                          "Thesis id (UUID) from another csid_ tool, e.g. "
                          "'7d4436ac-c0ef-4655-995f-10b06af94f21'."))],
                      replies_limit: Annotated[int, Field(ge=0, le=50, description=(
                          "How many replies to include (0-50, default 20)."))] = 20,
                      cursor: CursorArg = "", instance: InstanceArg = "",
                      ctx: Context = None) -> dict[str, Any]:
    """
    One thesis in full with its discussion: body, stance, author, the author's
    position, reactions and the replies (oldest first). Use after another csid_
    tool when the user wants to read a thread. cursor pages through the replies.

    Needs your own CabalSpy API key with a CabalSpy ID instance (no demo).
    """
    if not thesis_id.strip():
        return {"error": "missing_parameter", "parameter": "thesis_id", "message": "Pass a thesis id."}
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    inst = _resolve_instance(ctx, instance)
    result: dict[str, Any] = {}
    if not cursor:
        item, error = await _call("GET", "/v1/theses/item", ctx, {"id": thesis_id.strip(), "instance": inst},
                                  base=CSID_API_BASE, csid=True)
        if error:
            return error
        t = item.get("data") or {}
        result["thesis"] = {k: v for k, v in _slim_thesis(t, with_token=True).items()
                            if k != "latest_replies"}
        if t.get("chain") == "solana" and t.get("mint"):
            result["trade_url"] = f"{TERMINAL_URL}token/{t['mint']}"
        if not t.get("replies") or not replies_limit:
            result["replies"] = []
            return _compact(result)
    if not replies_limit:
        return {"replies": []}
    payload, error = await _call("GET", "/v1/theses/replies", ctx,
                                 {"id": thesis_id.strip(), "limit": replies_limit, "cursor": cursor,
                                  "instance": inst},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    result["replies"] = [_slim_reply(r) for r in payload.get("data") or []]
    if nxt := _next_cursor(payload):
        result["next_cursor"] = nxt
    return _compact(result)


# ── Leaderboard ───────────────────────────────────────────────────────────────


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_leaderboard(blockchain: ChainArg, period: PeriodArg = "7d",
                           sort: Annotated[str, Field(description=(
                               "volume (default), pnl (native currency), pnl_usd, win_rate or "
                               "trades."))] = "volume",
                           limit: Annotated[int, Field(ge=1, le=50, description=(
                               "How many traders (1-50, default 10)."))] = 10,
                           cursor: CursorArg = "",
                           scope: Annotated[str, Field(description=(
                               "'instance' (default): the users of your CabalSpy ID instance. "
                               "'global': every CabalSpy ID user, Enterprise plan only."))] = "instance",
                           instance: InstanceArg = "", ctx: Context = None) -> dict[str, Any]:
    """
    Ranking of CabalSpy ID verified traders by their tracked trades: volume,
    realized PnL, win rate and trade count for a period. Covers the users of YOUR
    CabalSpy ID instance (the people who signed in on your platform);
    scope='global' ranks every CabalSpy ID user and needs the Enterprise plan.
    Use for "Who are the best traders on my platform this week?". For KOLs and
    smart money tracked by CabalSpy use get_leaderboard.

    Needs your own CabalSpy API key with a CabalSpy ID instance (no demo).
    """
    if bad := _check_chain(blockchain):
        return bad
    if (bad := _check_choice(period, ["6h", "1d", "7d", "30d"], "period")) or \
            (bad := _check_choice(sort, CSID_SORTS, "sort")) or \
            (bad := _check_choice(scope, ["instance", "global"], "scope")):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    payload, error = await _call("GET", "/v1/wallets/leaderboard", ctx,
                                 {"blockchain": blockchain, "period": period, "sort": sort,
                                  "limit": limit, "cursor": cursor, "scope": scope,
                                  "instance": _resolve_instance(ctx, instance)},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    d = payload.get("data") or {}
    rows = []
    for e in d.get("leaderboard") or []:
        prof = e.get("profile") or {}
        st = e.get("period_stats") or {}
        wr = e.get("period_win_rate_distribution") or {}
        rows.append(_drop_empty({
            "rank": e.get("rank"), "wallet": e.get("wallet"),
            "username": prof.get("username"), "name": prof.get("name"),
            "kol": prof.get("kol") or None, "csid_id": prof.get("csid_id"),
            "volume": st.get("total_volume"), "volume_usd": st.get("total_volume_usd"),
            "realized_pnl": st.get("realized_pnl"), "realized_pnl_usd": st.get("realized_pnl_usd"),
            "realized_pnl_percent": st.get("realized_pnl_percentage"),
            "win_rate_percent": wr.get("win_rate_percentage"), "closed_positions": wr.get("closed_count"),
            "trades": st.get("total_txn"),
            "tokens": (e.get("period_history_tokens") or {}).get("total_tokens"),
        }))
    pag = d.get("pagination") or {}
    result = {"blockchain": d.get("blockchain", blockchain), "period": d.get("period", period),
              "scope": d.get("scope", scope), "sort": d.get("sort", sort),
              "currency": d.get("currency"), "total": pag.get("total"), "leaderboard": rows}
    if pag.get("next_cursor"):
        result["next_cursor"] = pag["next_cursor"]
    if not rows:
        result["note"] = ("No verified traders with trades in this period"
                          + (" on your instance yet." if result["scope"] == "instance" else "."))
    return _compact(result)


# ── White-label: a platform's own users and competitions ─────────────────────
#
# Platforms that keep their own login import their users into a CabalSpy ID
# instance and address them by their own user id (external_id). These tools
# only read; creating, importing and deleting users stays in the Data API.

CSID_WHITE_LABEL_DOCS_URL = f"{CSID_DOCS_URL}/white-label"
COMPETITION_STATUSES = ["scheduled", "waiting", "running", "ended", "cancelled"]

ExternalIdArg = Annotated[str, Field(description=(
    "The user's id on YOUR platform (external_id), as you passed it when the user was "
    "created or imported, e.g. 'did:privy:abc123' or '42'."
))]


def _slim_stats(s: dict) -> dict:
    return _drop_empty({
        "volume": s.get("total_volume"), "volume_usd": s.get("total_volume_usd"),
        "realized_pnl": s.get("realized_pnl"), "realized_pnl_usd": s.get("realized_pnl_usd"),
        "win_rate_percent": s.get("win_rate_percentage"), "closed_positions": s.get("closed_count"),
        "trades": s.get("total_txn"), "tokens": s.get("tokens"),
    })


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_platform_user(external_id: ExternalIdArg, period: PeriodArg = "7d",
                             instance: InstanceArg = "", ctx: Context = None) -> dict[str, Any]:
    """
    One user of YOUR platform (white-label), looked up by your own user id: display
    name, wallets with their trust status, X/Telegram/KOL badge, trading stats per
    chain for the period (volume, realized PnL, win rate), the latest trades and
    theses. Use for "How is user 42 on my platform doing this week?".

    Only for platforms that import their users into a CabalSpy ID instance
    (white-label). For CabalSpy ID users who signed in themselves use csid_profile.
    Needs your own CabalSpy API key with a CabalSpy ID instance (no demo).
    """
    if not external_id.strip():
        return {"error": "invalid_parameter", "parameter": "external_id",
                "message": "Pass the user's id on your platform."}
    if bad := _check_choice(period, ["6h", "1d", "7d", "30d"], "period"):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    payload, error = await _call("GET", "/v1/platform-users/profile", ctx,
                                 {"external_id": external_id.strip(), "period": period,
                                  "instance": _resolve_instance(ctx, instance)},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    p = payload.get("data") or {}
    x = p.get("x") or {}
    trading = [_drop_empty({"blockchain": t.get("blockchain"), "currency": t.get("currency"),
                            **_slim_stats(t),
                            "wallets": [_drop_empty({"address": w.get("address"), "verified": w.get("verified"),
                                                     "volume_usd": w.get("total_volume_usd"),
                                                     "realized_pnl_usd": w.get("realized_pnl_usd")})
                                        for w in t.get("wallets") or []]})
               for t in p.get("trading") or []]
    return _compact(_drop_empty({
        "external_id": p.get("external_id"), "csid_id": p.get("csid_id"),
        "display_name": p.get("display_name"), "claimed": p.get("claimed") or None,
        "x": x.get("username"), "telegram": (p.get("telegram") or {}).get("username"),
        "kol": (p.get("kol") or {}).get("badge") or None,
        "wallets": [_drop_empty({"address": w.get("address"), "family": w.get("family"),
                                 "status": w.get("status"), "source": w.get("source")})
                    for w in p.get("wallets") or []],
        "period": p.get("period", period), "trading": trading,
        "recent_trades": p.get("recent_trades"),
        "theses": (p.get("theses") or {}).get("total"),
        "created_at": p.get("created_at"),
    }))


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_platform_leaderboard(blockchain: ChainArg, period: PeriodArg = "7d",
                                    sort: Annotated[str, Field(description=(
                                        "pnl_usd (default), pnl (native currency), volume, "
                                        "win_rate or trades."))] = "pnl_usd",
                                    limit: Annotated[int, Field(ge=1, le=50, description=(
                                        "How many traders (1-50, default 10)."))] = 10,
                                    cursor: CursorArg = "",
                                    verified_only: Annotated[bool, Field(description=(
                                        "True ranks only payment-verified wallets. The instance "
                                        "setting leaderboard_trust can already enforce this."))] = False,
                                    instance: InstanceArg = "", ctx: Context = None) -> dict[str, Any]:
    """
    Ranking of the users of YOUR platform (white-label) by their trades on one
    chain: realized PnL, volume, win rate and trade count for a period, each entry
    with your own user id (external_id). Use for "Who are the top traders on my
    platform this week?" when your users are imported into a CabalSpy ID instance.
    For users who sign in with CabalSpy ID themselves use csid_leaderboard.

    Needs your own CabalSpy API key with a CabalSpy ID instance (no demo).
    """
    if bad := _check_chain(blockchain):
        return bad
    if (bad := _check_choice(period, ["6h", "1d", "7d", "30d"], "period")) or \
            (bad := _check_choice(sort, CSID_SORTS, "sort")):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    payload, error = await _call("GET", "/v1/platform-users/leaderboard", ctx,
                                 {"blockchain": blockchain, "period": period, "sort": sort,
                                  "limit": limit, "cursor": cursor,
                                  "trust": "verified" if verified_only else "",
                                  "instance": _resolve_instance(ctx, instance)},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    d = payload.get("data") or {}
    rows = []
    for e in d.get("leaderboard") or []:
        st = e.get("period_stats") or {}
        wr = e.get("period_win_rate_distribution") or {}
        rows.append(_drop_empty({
            "rank": e.get("rank"), "external_id": e.get("external_id"), "wallet": e.get("wallet"),
            "verified": e.get("verified"),
            "volume": st.get("total_volume"), "volume_usd": st.get("total_volume_usd"),
            "realized_pnl": st.get("realized_pnl"), "realized_pnl_usd": st.get("realized_pnl_usd"),
            "win_rate_percent": wr.get("win_rate_percentage"), "closed_positions": wr.get("closed_count"),
            "trades": st.get("total_txn"),
        }))
    result = {"blockchain": d.get("blockchain", blockchain), "period": d.get("period", period),
              "sort": d.get("sort", sort), "trust": d.get("trust"), "currency": d.get("currency"),
              "total": (payload.get("pagination") or {}).get("total"), "leaderboard": rows}
    if nxt := _next_cursor(payload):
        result["next_cursor"] = nxt
    if not rows:
        result["note"] = "None of your platform's users traded on this chain in this period."
    return _compact(result)


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_competitions(competition_id: Annotated[str, Field(description=(
                                "A competition id from a previous call. Empty lists your "
                                "competitions; set it for the rules and the standings."))] = "",
                            status: Annotated[str, Field(description=(
                                "When listing: scheduled, waiting, running, ended or cancelled. "
                                "Empty lists all."))] = "",
                            limit: Annotated[int, Field(ge=1, le=50, description=(
                                "How many competitions or standings rows (1-50, default 10)."))] = 10,
                            instance: InstanceArg = "", ctx: Context = None) -> dict[str, Any]:
    """
    Competitions of YOUR platform (white-label): without competition_id the list
    (name, kind, chain, metric, status, start and end, participants); with it the
    rules, every rule change and the current standings with your own user ids
    (standings are recomputed every 5 minutes, final once ended). Use for "Who is
    leading the competition?" or "Which competitions are running?".

    'kind' is 'trading' (ranked on trades: pnl_usd, pnl, volume, trades, win_rate;
    min_trades / min_volume_usd) or 'callouts' (ranked on the callouts made during
    the competition, each scored by its peak multiple: avg_peak_x, best_peak_x,
    sum_peak_x, hit_rate, callouts; min_callouts to qualify, hit_x = the multiple
    that counts as a hit).

    Needs your own CabalSpy API key with a CabalSpy ID instance (no demo).
    """
    if status and (bad := _check_choice(status, COMPETITION_STATUSES, "status")):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    inst = _resolve_instance(ctx, instance)
    keep = ("id", "name", "kind", "chain", "metric", "status", "starts_at", "ends_at", "ended_at",
            "participants", "min_participants", "max_participants", "min_trades",
            "min_volume_usd", "min_callouts", "hit_x", "wallet_trust", "enrollment", "late_join",
            "prizes", "rules_version")
    if not competition_id.strip():
        payload, error = await _call("GET", "/v1/competitions", ctx,
                                     {"status": status, "limit": limit, "instance": inst},
                                     base=CSID_API_BASE, csid=True)
        if error:
            return error
        items = [_drop_empty({k: c.get(k) for k in keep}) for c in payload.get("data") or []]
        result: dict[str, Any] = {"total": (payload.get("pagination") or {}).get("total"),
                                  "competitions": items}
        if not items:
            result["note"] = ("No competitions yet. They are created through the Data API: "
                              f"{CSID_WHITE_LABEL_DOCS_URL}")
        return _compact(result)
    cid = competition_id.strip()
    payload, error = await _call("GET", "/v1/competitions/detail", ctx, {"id": cid, "instance": inst},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    c = payload.get("data") or {}
    result = _drop_empty({k: c.get(k) for k in keep + ("description", "changed_while_running")})
    if c.get("changes"):
        result["changes"] = c["changes"]
    payload, error = await _call("GET", "/v1/competitions/standings", ctx,
                                 {"id": cid, "limit": limit, "instance": inst},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    s = payload.get("data") or {}
    result["standings_updated_at"] = s.get("updated_at")
    result["final"] = s.get("final")
    result["standings"] = s.get("standings") or []
    return _compact(result)


# ── Callouts: users call a token, CabalSpy tracks how it did ──────────────────
#
# An extra of CabalSpy ID, switched on per instance on request. When a user
# calls a token, the price and market cap are stamped; for the first 24 hours
# the price is tracked every minute (then scored on candles), after that every
# 5 minutes while the token is active, until it spends 24 h in a row below a
# $10k market cap. score_x is the peak multiple. These tools only read; making
# and removing callouts stays in the Data API.

CALLOUT_PERIODS = ["6h", "1d", "7d", "30d"]
CALLOUT_SORTS = ["avg_peak_x", "best_peak_x", "sum_peak_x", "hit_rate", "callouts", "median_peak_x"]
CALLOUTS_DOCS_URL = CSID_DOCS_URL

CalloutExternalIdArg = Annotated[str, Field(description=(
    "Only this user: their id on YOUR platform (external_id), as passed when the user was "
    "created or imported. Pass external_id or csid_id, not both."
))]
CalloutCsidIdArg = Annotated[str, Field(description=(
    "Only this user: their CabalSpy ID user id (UUID), for users who signed in with "
    "CabalSpy ID themselves. Pass external_id or csid_id, not both."
))]
HitXArg = Annotated[float, Field(gt=1, le=1000, description=(
    "The peak multiple that counts as a hit for hits and hit_rate_percent, e.g. 2 for a "
    "2x (default 2, above 1 and at most 1000)."
))]


def _slim_caller(a: Any) -> dict | None:
    """A callout author or leaderboard person: your user id first."""
    if not isinstance(a, dict):
        return None
    return _drop_empty({"external_id": a.get("external_id"), "username": a.get("username"),
                        "name": a.get("name"), "csid_id": a.get("csid_id"),
                        "kol": a.get("kol") or None})


def _slim_summary(s: dict) -> dict:
    """The server's summary of a list of peak multiples; hit_rate is a percentage."""
    out = {k: s.get(k) for k in ("callouts", "avg_peak_x", "median_peak_x", "best_peak_x",
                                 "sum_peak_x", "hits")}
    out["hit_rate_percent"] = s.get("hit_rate")
    for k in ("avg_now_x", "tracking"):
        if k in s:
            out[k] = s[k]
    return {k: v for k, v in out.items() if v is not None}


def _slim_callout(c: dict) -> dict:
    token = c.get("token") or {}
    at_call = c.get("at_call") or {}
    now = c.get("now") or {}
    peak = c.get("peak") or {}
    tr = c.get("tracking") or {}
    return _drop_empty({
        "id": c.get("id"), "chain": c.get("chain"), "mint": c.get("mint"),
        "token": token.get("symbol") or token.get("name"),
        "author": _slim_caller(c.get("author")),
        "called_at": c.get("called_at"),
        "market_cap_at_call_usd": at_call.get("market_cap_usd"),
        "price_at_call_usd": at_call.get("price_usd"),
        "now_x": now.get("x"), "now_market_cap_usd": now.get("market_cap_usd"),
        "peak_x": peak.get("x"), "peak_at": peak.get("at"),
        "score_x": c.get("score_x"),
        "phase": tr.get("phase"),
        "stop_reason": tr.get("stop_reason"),
        "note": c.get("note"),
    })


def _check_callout_user(external_id: str, csid_id: str) -> dict | None:
    if external_id.strip() and csid_id.strip():
        return {"error": "invalid_parameter", "parameter": "external_id",
                "message": "Pass external_id or csid_id, not both."}
    return None


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_callouts(chain: Annotated[str, Field(description=(
                            "Only callouts on this blockchain: solana, bnb, base, eth or rh. "
                            "Required together with mint. Leave empty for all chains."))] = "",
                        mint: Annotated[str, Field(description=(
                            "Only callouts of this token (mint on Solana, contract on EVM); "
                            "needs chain. Answers 'who called this token and how did it do'."))] = "",
                        external_id: CalloutExternalIdArg = "",
                        csid_id: CalloutCsidIdArg = "",
                        limit: Annotated[int, Field(ge=1, le=50, description=(
                            "How many callouts (1-50, default 10)."))] = 10,
                        cursor: CursorArg = "",
                        instance: InstanceArg = "", ctx: Context = None) -> dict[str, Any]:
    """
    Callouts on YOUR CabalSpy ID instance, newest first: users call a token and
    CabalSpy stamps the price and market cap and tracks it. Without filters the
    latest callouts of your platform; with chain + mint the callouts of one token
    ("Who called this token and how did it do?"); with external_id or csid_id the
    callouts of one user. Each entry: token, author (your user id), called_at,
    market cap at the call, now_x and peak_x (multiples since the call), score_x
    (the peak multiple the callout is scored by) and the tracking phase
    (first_day: every minute for 24 h, then scored on candles; extended: every
    5 minutes while active; stopped: after 24 h in a row below a $10k market cap).

    Callouts are an extra switched on per instance on request; otherwise this
    returns feature_not_enabled. Needs your own CabalSpy API key with a CabalSpy
    ID instance (no demo).
    """
    chain, mint = chain.strip().lower(), mint.strip()
    if chain and (bad := _check_chain(chain, "chain")):
        return bad
    if mint and not chain:
        return {"error": "invalid_parameter", "parameter": "chain",
                "message": "Pass chain together with mint.", "allowed": CHAINS}
    if bad := _check_callout_user(external_id, csid_id):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    payload, error = await _call("GET", "/v1/callouts", ctx,
                                 {"chain": chain, "mint": mint, "external_id": external_id.strip(),
                                  "csid_id": csid_id.strip(), "limit": limit, "cursor": cursor,
                                  "instance": _resolve_instance(ctx, instance)},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    items = [_slim_callout(c) for c in payload.get("data") or [] if isinstance(c, dict)]
    result: dict[str, Any] = {"callouts": items}
    if nxt := _next_cursor(payload):
        result["next_cursor"] = nxt
    if not items:
        result["note"] = ("No callouts match. Callouts are made through the Data API: "
                          f"{CALLOUTS_DOCS_URL}")
    result = _with_trade_url(result, chain, mint)
    return _compact(result)


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_callout_leaderboard(period: Annotated[str, Field(description=(
                                       "Callouts made in the last 6h, 1d, 7d (default) or 30d."))] = "7d",
                                   sort: Annotated[str, Field(description=(
                                       "avg_peak_x (default), best_peak_x, sum_peak_x, hit_rate, "
                                       "callouts or median_peak_x."))] = "avg_peak_x",
                                   chain: OptionalChainArg = "",
                                   min_callouts: Annotated[int, Field(ge=1, le=1000, description=(
                                       "Only callers with at least this many callouts in the period "
                                       "(1-1000, default 1). Raise it to keep one lucky call from "
                                       "topping the average."))] = 1,
                                   hit_x: HitXArg = 2.0,
                                   limit: Annotated[int, Field(ge=1, le=50, description=(
                                       "How many callers (1-50, default 10)."))] = 10,
                                   cursor: CursorArg = "",
                                   instance: InstanceArg = "", ctx: Context = None) -> dict[str, Any]:
    """
    The best callers of YOUR CabalSpy ID instance for a period (6h, 1d, 7d, 30d):
    each user's callouts in the period, scored by their peak multiples (score_x),
    with average, median, best and summed peak multiple, hits and hit rate (share
    of callouts that reached hit_x), and their best call. Entries carry your own
    user id (external_id). Use for "Who are the best callers this week?".

    Callouts are an extra switched on per instance on request; otherwise this
    returns feature_not_enabled. Needs your own CabalSpy API key with a CabalSpy
    ID instance (no demo).
    """
    chain = chain.strip().lower()
    if (bad := _check_choice(period, CALLOUT_PERIODS, "period")) or \
            (bad := _check_choice(sort, CALLOUT_SORTS, "sort")):
        return bad
    if chain and (bad := _check_chain(chain, "chain")):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    payload, error = await _call("GET", "/v1/callouts/leaderboard", ctx,
                                 {"period": period, "sort": sort, "chain": chain,
                                  "min_callouts": min_callouts, "hit_x": hit_x, "limit": limit,
                                  "cursor": cursor, "instance": _resolve_instance(ctx, instance)},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    d = payload.get("data") or {}
    rows = []
    for e in d.get("leaderboard") or []:
        best = e.get("best_call") or {}
        person = _slim_caller(e.get("author")) or {"csid_id": e.get("csid_id")}
        rows.append(_drop_empty({
            "rank": e.get("rank"), **person, **_slim_summary(e),
            "best_call": _drop_empty({"token": best.get("symbol"), "chain": best.get("chain"),
                                      "mint": best.get("mint"), "peak_x": best.get("peak_x")}),
        }))
    result: dict[str, Any] = {"period": d.get("period", period), "sort": d.get("sort", sort),
                              "chain": d.get("chain") or "all", "hit_x": d.get("hit_x", hit_x),
                              "min_callouts": min_callouts,
                              "total": (payload.get("pagination") or {}).get("total"),
                              "leaderboard": rows}
    if nxt := _next_cursor(payload):
        result["next_cursor"] = nxt
    if not rows:
        result["note"] = "Nobody on your instance made enough callouts in this period."
    return _compact(result)


@tool(annotations=READ_ONLY, structured_output=True)
async def csid_callout_stats(external_id: CalloutExternalIdArg = "",
                             csid_id: CalloutCsidIdArg = "",
                             hit_x: HitXArg = 2.0,
                             instance: InstanceArg = "", ctx: Context = None) -> dict[str, Any]:
    """
    The callout track record of ONE user of YOUR CabalSpy ID instance, per period
    (callouts made in the last 6h, 1d, 7d and 30d): number of callouts, average,
    median, best and summed peak multiple (score_x), hits and hit rate (share that
    reached hit_x), the average multiple right now and how many are still being
    tracked, plus the all-time count. Use for "How good are this user's calls?".
    Pass external_id (your user id) or csid_id.

    Callouts are an extra switched on per instance on request; otherwise this
    returns feature_not_enabled. Needs your own CabalSpy API key with a CabalSpy
    ID instance (no demo).
    """
    if not external_id.strip() and not csid_id.strip():
        return {"error": "invalid_parameter", "parameter": "external_id",
                "message": "Pass the user's id on your platform (external_id) or their csid_id."}
    if bad := _check_callout_user(external_id, csid_id):
        return bad
    if not _has_own_key(ctx):
        return _CSID_NEEDS_KEY
    payload, error = await _call("GET", "/v1/callouts/stats", ctx,
                                 {"external_id": external_id.strip(), "csid_id": csid_id.strip(),
                                  "hit_x": hit_x, "instance": _resolve_instance(ctx, instance)},
                                 base=CSID_API_BASE, csid=True)
    if error:
        return error
    d = payload.get("data") or {}
    periods = {name: _slim_summary(s) for name, s in (d.get("periods") or {}).items()
               if isinstance(s, dict)}
    return _compact(_drop_empty({
        "user": _slim_caller(d.get("user")), "hit_x": d.get("hit_x", hit_x),
        "periods": periods, "callouts_all_time": d.get("callouts_all_time"),
    }))


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
