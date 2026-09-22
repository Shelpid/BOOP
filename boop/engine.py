from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

import httpx
from solders.transaction import VersionedTransaction

from .checks import run_checks
from .config import LAMPORTS, SOL_MINT, Config
from .jupiter import Jupiter
from .rpc import Rpc
from .sniff import Candidate, Sniffer
from .wallet import load_keypair

STAGES = ("SNIFF", "CHECK", "BOOP", "BANK")


@dataclass
class Position:
    n: int
    mint: str
    symbol: str
    cost_sol: float
    amount_raw: int
    opened_at: float
    value_sol: float = 0.0
    peak_sol: float = 0.0
    status: str = "OPEN"  # OPEN | CLOSING | WON | LOST
    proceeds_sol: float = 0.0
    exit_reason: str = ""
    closed_at: float = 0.0

    @property
    def pnl_sol(self) -> float:
        v = self.proceeds_sol if self.status in ("WON", "LOST") else self.value_sol
        return v - self.cost_sol

    @property
    def pnl_pct(self) -> float:
        return self.pnl_sol / self.cost_sol * 100 if self.cost_sol else 0.0


@dataclass
class State:
    mode: str
    wallet: str
    start_sol: float
    balance_sol: float
    started_at: float = field(default_factory=time.time)
    stage: str = "SNIFF"
    stage_detail: str = "warming up"
    stage_at: float = field(default_factory=time.time)
    positions: list[Position] = field(default_factory=list)
    log: deque = field(default_factory=lambda: deque(maxlen=200))
    scanned: int = 0
    rejected: int = 0
    halted: str = ""

    def say(self, msg: str, kind: str = "") -> None:
        self.log.append((time.time(), msg, kind))

    def set_stage(self, stage: str, detail: str = "") -> None:
        self.stage, self.stage_detail, self.stage_at = stage, detail, time.time()

    @property
    def open(self) -> list[Position]:
        return [p for p in self.positions if p.status in ("OPEN", "CLOSING")]

    @property
    def closed(self) -> list[Position]:
        return [p for p in self.positions if p.status in ("WON", "LOST")]

    @property
    def realized(self) -> float:
        return sum(p.pnl_sol for p in self.closed)

    @property
    def unrealized(self) -> float:
        return sum(p.pnl_sol for p in self.open)


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = httpx.AsyncClient(headers={"user-agent": "boop/0.1"})
        self.rpc = Rpc(cfg.rpc_url, self.http)
        self.jup = Jupiter(cfg.jup_base, self.http, cfg.jup_api_key)
        self.sniffer = Sniffer(cfg.dexscreener_base, self.http, cfg.watchlist)
        self.kp = load_keypair(cfg.private_key) if cfg.private_key else None
        self.pub = str(self.kp.pubkey()) if self.kp else "paper-wallet"
        self.seen: set[str] = set()
        self.state: State | None = None
        self._stop = asyncio.Event()

    # ---------- lifecycle ----------
    async def start(self) -> State:
        if self.cfg.paper:
            bal = self.cfg.paper_balance_sol
        else:
            bal = await self.rpc.balance(self.pub) / LAMPORTS
        self.state = State("PAPER" if self.cfg.paper else "LIVE", self.pub, bal, bal)
        self.state.say(f"boop online · {self.state.mode} · {bal:.3f} SOL", "d")
        return self.state

    async def run(self) -> None:
        await asyncio.gather(self._sniff_loop(), self._monitor_loop())

    def stop(self) -> None:
        self._stop.set()

    async def close(self) -> None:
        await self.http.aclose()

    # ---------- loops ----------
    async def _sleep(self, sec: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=sec)
        except asyncio.TimeoutError:
            pass

    def _can_boop(self) -> bool:
        s, c = self.state, self.cfg
        if s.realized <= -c.max_session_loss_sol:
            s.halted = "session loss limit"
        elif len(s.positions) >= c.max_boops:
            s.halted = f"{c.max_boops} boops done"
        else:
            s.halted = ""
        return not s.halted and len(s.open) < c.max_open and s.balance_sol > c.buy_sol + 0.01

    async def _sniff_loop(self) -> None:
        s = self.state
        while not self._stop.is_set():
            try:
                if self._can_boop():
                    await self._sniff_once()
                elif not s.open and s.halted:
                    s.set_stage("BANK", s.halted)
            except Exception as e:  # keep the little guy alive
                s.say(f"sniff error: {e!s:.60}", "e")
            await self._sleep(self.cfg.sniff_every_sec)

    async def _sniff_once(self) -> None:
        s = self.state
        s.set_stage("SNIFF", "scanning fresh pools")
        mints = [m for m in await self.sniffer.fresh_mints() if m not in self.seen]
        if not mints:
            return
        cands = await self.sniffer.describe(mints)
        self.seen.update(mints)
        s.scanned += len(cands)
        s.say(f"sniff  {len(cands)} new tokens", "d")
        for c in sorted(cands, key=lambda x: -x.liquidity_usd):
            if self._stop.is_set() or not self._can_boop():
                return
            s.set_stage("CHECK", f"${c.symbol}")
            v = await run_checks(c, self.cfg, self.rpc, self.jup)
            if not v.ok:
                s.rejected += 1
                continue
            s.say(f"check  ${c.symbol:<8} ✓ " + " ".join(f"{x.name} {x.detail}" for x in v.checks[-2:]), "d")
            await self._boop(c, v.buy_quote)

    async def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            for p in list(self.state.open):
                try:
                    await self._mark(p)
                except Exception as e:
                    self.state.say(f"mark ${p.symbol}: {e!s:.50}", "e")
            await self._sleep(self.cfg.monitor_every_sec)

    # ---------- trading ----------
    async def _execute(self, quote: dict) -> str:
        raw = await self.jup.swap_tx(quote, self.pub, self.cfg.priority_max_lamports)
        tx = VersionedTransaction.from_bytes(raw)
        signed = VersionedTransaction(tx.message, [self.kp])
        sig = await self.rpc.send(bytes(signed))
        if not await self.rpc.confirm(sig):
            raise RuntimeError(f"not confirmed {sig[:10]}…")
        return sig

    async def _boop(self, c: Candidate, quote: dict) -> None:
        s = self.state
        s.set_stage("BOOP", f"${c.symbol}")
        n = len(s.positions) + 1
        if self.cfg.paper:
            amount = int(quote["outAmount"])
            cost = self.cfg.buy_sol
        else:
            before = await self.rpc.balance(self.pub)
            sig = await self._execute(quote)
            await asyncio.sleep(2)
            amount = await self.rpc.token_balance(self.pub, c.mint)
            cost = (before - await self.rpc.balance(self.pub)) / LAMPORTS
            s.say(f"tx     {sig[:16]}…", "d")
        if amount <= 0:
            s.say(f"boop   ${c.symbol} got 0 tokens, skipping", "e")
            return
        s.balance_sol -= cost
        p = Position(n, c.mint, c.symbol, cost, amount, time.time(), value_sol=cost, peak_sol=cost)
        s.positions.append(p)
        s.say(f"BOOP   #{n:02d} ${c.symbol} buy {cost:.3f} SOL", "b")

    async def _mark(self, p: Position) -> None:
        cfg = self.cfg
        q = await self.jup.quote(p.mint, SOL_MINT, p.amount_raw, cfg.slippage_bps)
        if not q:
            return
        p.value_sol = int(q["outAmount"]) / LAMPORTS
        p.peak_sol = max(p.peak_sol, p.value_sol)
        pct = p.pnl_pct
        drop = (1 - p.value_sol / p.peak_sol) * 100 if p.peak_sol else 0
        reason = ""
        if pct >= cfg.take_profit_pct:
            reason = "take profit"
        elif pct <= -cfg.stop_loss_pct:
            reason = "stop loss"
        elif p.peak_sol > p.cost_sol * 1.1 and drop >= cfg.trailing_pct:
            reason = "trailing stop"
        elif time.time() - p.opened_at >= cfg.max_hold_sec:
            reason = "max hold"
        if reason:
            await self._bank(p, q, reason)

    async def _bank(self, p: Position, quote: dict, reason: str) -> None:
        s = self.state
        s.set_stage("BANK", f"${p.symbol}")
        p.status = "CLOSING"
        try:
            if self.cfg.paper:
                proceeds = int(quote["outAmount"]) / LAMPORTS
            else:
                before = await self.rpc.balance(self.pub)
                await self._execute(quote)
                await asyncio.sleep(2)
                proceeds = (await self.rpc.balance(self.pub) - before) / LAMPORTS
        except Exception as e:
            p.status = "OPEN"
            s.say(f"bank   ${p.symbol} failed: {e!s:.40}", "e")
            return
        p.proceeds_sol = proceeds
        p.closed_at = time.time()
        p.exit_reason = reason
        p.status = "WON" if p.pnl_sol >= 0 else "LOST"
        s.balance_sol += proceeds
        sign = "+" if p.pnl_sol >= 0 else "-"
        s.say(f"bank   #{p.n:02d} ${p.symbol} {sign}{abs(p.pnl_sol):.3f} SOL · {reason}", "w" if p.pnl_sol >= 0 else "l")

    async def close_all(self) -> None:
        for p in list(self.state.open):
            q = await self.jup.quote(p.mint, SOL_MINT, p.amount_raw, self.cfg.slippage_bps)
            if q:
                await self._bank(p, q, "manual exit")
