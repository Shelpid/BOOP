from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

SOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS = 1_000_000_000


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    v = os.getenv(name)
    return default if not v else float(v)


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    return default if not v else int(v)


@dataclass
class Config:
    # connections
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    private_key: str | None = None
    jup_base: str = "https://api.jup.ag/swap/v1"
    jup_api_key: str | None = None
    dexscreener_base: str = "https://api.dexscreener.com"

    # mode
    paper: bool = True
    paper_balance_sol: float = 5.0

    # sizing & limits
    buy_sol: float = 0.1
    max_open: int = 3
    max_boops: int = 12
    max_session_loss_sol: float = 0.5
    slippage_bps: int = 300
    priority_max_lamports: int = 1_000_000

    # exits
    take_profit_pct: float = 60.0
    stop_loss_pct: float = 25.0
    trailing_pct: float = 20.0
    max_hold_sec: int = 900

    # checks
    min_liquidity_usd: float = 15_000
    min_fdv_usd: float = 30_000
    max_fdv_usd: float = 3_000_000
    max_pair_age_min: float = 180
    max_price_impact_pct: float = 5.0
    max_roundtrip_loss_pct: float = 10.0
    require_mint_revoked: bool = True
    require_freeze_revoked: bool = True

    # loop
    sniff_every_sec: float = 20
    monitor_every_sec: float = 3
    watchlist: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "Config":
        if env_file:
            load_dotenv(env_file)
        c = cls()
        c.rpc_url = os.getenv("RPC_URL", c.rpc_url)
        c.private_key = os.getenv("PRIVATE_KEY") or None
        c.jup_base = os.getenv("JUP_BASE", c.jup_base).rstrip("/")
        c.jup_api_key = os.getenv("JUP_API_KEY") or None
        c.dexscreener_base = os.getenv("DEXSCREENER_BASE", c.dexscreener_base).rstrip("/")
        c.paper = _bool("PAPER", c.paper)
        c.paper_balance_sol = _float("PAPER_BALANCE_SOL", c.paper_balance_sol)
        c.buy_sol = _float("BUY_SOL", c.buy_sol)
        c.max_open = _int("MAX_OPEN", c.max_open)
        c.max_boops = _int("MAX_BOOPS", c.max_boops)
        c.max_session_loss_sol = _float("MAX_SESSION_LOSS_SOL", c.max_session_loss_sol)
        c.slippage_bps = _int("SLIPPAGE_BPS", c.slippage_bps)
        c.priority_max_lamports = _int("PRIORITY_MAX_LAMPORTS", c.priority_max_lamports)
        c.take_profit_pct = _float("TAKE_PROFIT_PCT", c.take_profit_pct)
        c.stop_loss_pct = _float("STOP_LOSS_PCT", c.stop_loss_pct)
        c.trailing_pct = _float("TRAILING_PCT", c.trailing_pct)
        c.max_hold_sec = _int("MAX_HOLD_SEC", c.max_hold_sec)
        c.min_liquidity_usd = _float("MIN_LIQUIDITY_USD", c.min_liquidity_usd)
        c.min_fdv_usd = _float("MIN_FDV_USD", c.min_fdv_usd)
        c.max_fdv_usd = _float("MAX_FDV_USD", c.max_fdv_usd)
        c.max_pair_age_min = _float("MAX_PAIR_AGE_MIN", c.max_pair_age_min)
        c.max_price_impact_pct = _float("MAX_PRICE_IMPACT_PCT", c.max_price_impact_pct)
        c.max_roundtrip_loss_pct = _float("MAX_ROUNDTRIP_LOSS_PCT", c.max_roundtrip_loss_pct)
        c.require_mint_revoked = _bool("REQUIRE_MINT_REVOKED", c.require_mint_revoked)
        c.require_freeze_revoked = _bool("REQUIRE_FREEZE_REVOKED", c.require_freeze_revoked)
        c.sniff_every_sec = _float("SNIFF_EVERY_SEC", c.sniff_every_sec)
        c.monitor_every_sec = _float("MONITOR_EVERY_SEC", c.monitor_every_sec)
        wl = os.getenv("WATCHLIST", "")
        c.watchlist = [m.strip() for m in wl.split(",") if m.strip()]
        return c

    def validate(self) -> None:
        if not self.paper and not self.private_key:
            raise SystemExit("PRIVATE_KEY is required when PAPER=false")
        if self.buy_sol <= 0:
            raise SystemExit("BUY_SOL must be > 0")
