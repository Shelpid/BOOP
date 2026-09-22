from __future__ import annotations

import argparse
import asyncio
import signal

from rich.console import Console
from rich.live import Live
from rich.table import Table

from . import mascot
from .checks import run_checks
from .config import LAMPORTS, SOL_MINT, Config
from .engine import Engine
from .ui import render

console = Console()


async def cmd_run(cfg: Config) -> None:
    eng = Engine(cfg)
    state = await eng.start()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, eng.stop)
        except NotImplementedError:  # windows
            pass
    task = asyncio.create_task(eng.run())
    with Live(render(state, cfg), console=console, screen=True, refresh_per_second=8) as live:
        while not task.done():
            live.update(render(state, cfg))
            await asyncio.sleep(0.125)
    if state.open:
        console.print(f"[{mascot.YELLOW}]closing {len(state.open)} open position(s)…")
        await eng.close_all()
    await eng.close()
    pnl = state.realized
    console.print(mascot.render(bg=mascot.BLACK))
    console.print(f"[bold {mascot.YELLOW}]session over · {len(state.closed)} boops · {pnl:+.4f} SOL")


async def cmd_check(cfg: Config, mint: str) -> None:
    eng = Engine(cfg)
    cands = await eng.sniffer.describe([mint])
    if not cands:
        console.print("[red]no pair found on DexScreener")
        return await eng.close()
    v = await run_checks(cands[0], cfg, eng.rpc, eng.jup)
    t = Table(title=f"${cands[0].symbol} · {mint}", style=mascot.YELLOW)
    t.add_column("check")
    t.add_column("result")
    t.add_column("detail")
    for c in v.checks:
        t.add_row(c.name, "✓" if c.ok else "✗", c.detail)
    console.print(t)
    console.print(f"[bold {mascot.YELLOW}]{'BOOPABLE' if v.ok else 'NOPE'}")
    await eng.close()


async def cmd_quote(cfg: Config, mint: str, sol: float) -> None:
    eng = Engine(cfg)
    q = await eng.jup.quote(SOL_MINT, mint, int(sol * LAMPORTS), cfg.slippage_bps)
    if not q:
        console.print("[red]no route")
    else:
        impact = float(q.get("priceImpactPct") or 0) * 100
        console.print(f"[{mascot.YELLOW}]{sol} SOL → {q['outAmount']} raw units · impact {impact:.2f}% · {len(q.get('routePlan', []))} hop(s)")
    await eng.close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="boop", description="tiny Solana trading terminal with a pixel mascot")
    ap.add_argument("--env", default=".env", help="path to .env file")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="start the terminal")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--paper", action="store_true", help="simulate fills from live Jupiter quotes")
    g.add_argument("--live", action="store_true", help="send real transactions")
    c = sub.add_parser("check", help="run safety checks on a mint")
    c.add_argument("mint")
    q = sub.add_parser("quote", help="quote SOL → token")
    q.add_argument("mint")
    q.add_argument("sol", type=float)
    args = ap.parse_args()

    cfg = Config.from_env(args.env)
    if args.cmd in (None, "run"):
        if getattr(args, "paper", False):
            cfg.paper = True
        if getattr(args, "live", False):
            cfg.paper = False
        cfg.validate()
        asyncio.run(cmd_run(cfg))
    elif args.cmd == "check":
        asyncio.run(cmd_check(cfg, args.mint))
    elif args.cmd == "quote":
        asyncio.run(cmd_quote(cfg, args.mint, args.sol))


if __name__ == "__main__":
    main()
