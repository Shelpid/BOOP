import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from boop.checks import parse_mint, run_checks  # noqa: E402
from boop.config import Config  # noqa: E402
from boop.engine import Engine  # noqa: E402
from boop.sniff import Candidate  # noqa: E402


def mint_bytes(mint_auth=None, freeze=None, supply=10**15, decimals=6):
    b = bytearray(82)
    if mint_auth:
        b[0:4] = (1).to_bytes(4, "little"); b[4:36] = mint_auth
    b[36:44] = supply.to_bytes(8, "little"); b[44] = decimals; b[45] = 1
    if freeze:
        b[46:50] = (1).to_bytes(4, "little"); b[50:82] = freeze
    return bytes(b)


def test_parse_mint():
    m = parse_mint(mint_bytes())
    assert m.mint_authority is None and m.freeze_authority is None and m.decimals == 6
    m = parse_mint(mint_bytes(mint_auth=b"\x01" * 32, freeze=b"\x02" * 32))
    assert m.mint_authority == b"\x01" * 32 and m.freeze_authority == b"\x02" * 32


class FakeRpc:
    def __init__(self, data): self.data = data
    async def account_data(self, mint): return self.data.get(mint)


class FakeJup:
    """Price moves up 12% per mark for GOOD, down for BAD."""
    def __init__(self): self.mult = {"GOOD": 1.0, "BAD": 1.0}
    async def quote(self, inp, out, amount, bps):
        sol = "So11111111111111111111111111111111111111112"
        if inp == sol:
            return {"outAmount": str(amount * 1000), "priceImpactPct": "0.01"}
        m = self.mult.get(inp, 1.0)
        return {"outAmount": str(int(amount / 1000 * m * 0.99)), "priceImpactPct": "0.01"}


def cand(sym):
    return Candidate(sym, sym, 50_000, 200_000, 20, 0.001, "raydium", "")


def test_checks_pass_and_fail():
    cfg = Config()
    rpc = FakeRpc({"GOOD": mint_bytes(), "RUG": mint_bytes(mint_auth=b"\x09" * 32)})
    jup = FakeJup()
    assert asyncio.run(run_checks(cand("GOOD"), cfg, rpc, jup)).ok
    v = asyncio.run(run_checks(cand("RUG"), cfg, rpc, jup))
    assert not v.ok and "mint auth" in v.failed()


def test_paper_flow():
    cfg = Config(paper=True, buy_sol=0.1, take_profit_pct=30, stop_loss_pct=20)
    eng = Engine(cfg)
    eng.rpc = FakeRpc({"GOOD": mint_bytes(), "BAD": mint_bytes()})
    eng.jup = FakeJup()

    async def go():
        s = await eng.start()
        v = await run_checks(cand("GOOD"), cfg, eng.rpc, eng.jup)
        await eng._boop(cand("GOOD"), v.buy_quote)
        v = await run_checks(cand("BAD"), cfg, eng.rpc, eng.jup)
        await eng._boop(cand("BAD"), v.buy_quote)
        eng.jup.mult = {"GOOD": 1.45, "BAD": 0.7}
        for p in list(s.open):
            await eng._mark(p)
        await eng.close()
        return s

    s = asyncio.run(go())
    good, bad = s.positions
    assert good.status == "WON" and good.exit_reason == "take profit"
    assert bad.status == "LOST" and bad.exit_reason == "stop loss"
    assert abs(s.balance_sol - (5.0 + good.pnl_sol + bad.pnl_sol)) < 1e-9
