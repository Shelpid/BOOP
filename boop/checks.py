from __future__ import annotations

from dataclasses import dataclass

from .config import LAMPORTS, SOL_MINT, Config
from .jupiter import Jupiter
from .rpc import Rpc
from .sniff import Candidate


@dataclass
class MintInfo:
    mint_authority: bytes | None
    supply: int
    decimals: int
    freeze_authority: bytes | None


def parse_mint(data: bytes) -> MintInfo:
    """SPL Token / Token-2022 mint layout (first 82 bytes are identical)."""
    if len(data) < 82:
        raise ValueError("not a mint account")
    ma_opt = int.from_bytes(data[0:4], "little")
    supply = int.from_bytes(data[36:44], "little")
    decimals = data[44]
    fa_opt = int.from_bytes(data[46:50], "little")
    return MintInfo(
        mint_authority=data[4:36] if ma_opt else None,
        supply=supply,
        decimals=decimals,
        freeze_authority=data[50:82] if fa_opt else None,
    )


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Verdict:
    candidate: Candidate
    checks: list[Check]
    buy_quote: dict | None = None

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def failed(self) -> str:
        return ", ".join(c.name for c in self.checks if not c.ok)


async def run_checks(c: Candidate, cfg: Config, rpc: Rpc, jup: Jupiter) -> Verdict:
    checks: list[Check] = []
    v = Verdict(c, checks)

    # 1. market sanity (cheap, no RPC)
    checks.append(Check("liquidity", c.liquidity_usd >= cfg.min_liquidity_usd, f"${c.liquidity_usd:,.0f}"))
    checks.append(Check("fdv", cfg.min_fdv_usd <= c.fdv_usd <= cfg.max_fdv_usd, f"${c.fdv_usd:,.0f}"))
    checks.append(Check("age", c.age_min <= cfg.max_pair_age_min, f"{c.age_min:.0f}m"))
    if not all(x.ok for x in checks):
        return v

    # 2. mint / freeze authority
    data = await rpc.account_data(c.mint)
    if data is None:
        checks.append(Check("mint", False, "account not found"))
        return v
    mi = parse_mint(data)
    if cfg.require_mint_revoked:
        checks.append(Check("mint auth", mi.mint_authority is None, "revoked" if mi.mint_authority is None else "ACTIVE"))
    if cfg.require_freeze_revoked:
        checks.append(Check("freeze auth", mi.freeze_authority is None, "revoked" if mi.freeze_authority is None else "ACTIVE"))
    if not all(x.ok for x in checks):
        return v

    # 3. route + price impact + round-trip (honeypot / hidden tax detector)
    lamports = int(cfg.buy_sol * LAMPORTS)
    q_buy = await jup.quote(SOL_MINT, c.mint, lamports, cfg.slippage_bps)
    if not q_buy:
        checks.append(Check("buy route", False, "no route"))
        return v
    impact = float(q_buy.get("priceImpactPct") or 0) * 100
    checks.append(Check("impact", impact <= cfg.max_price_impact_pct, f"{impact:.2f}%"))
    q_sell = await jup.quote(c.mint, SOL_MINT, int(q_buy["outAmount"]), cfg.slippage_bps)
    if not q_sell:
        checks.append(Check("sell route", False, "cannot sell"))
        return v
    back = int(q_sell["outAmount"]) / lamports
    loss = (1 - back) * 100
    checks.append(Check("round-trip", loss <= cfg.max_roundtrip_loss_pct, f"-{loss:.1f}%"))
    v.buy_quote = q_buy
    return v
