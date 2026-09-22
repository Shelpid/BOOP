from __future__ import annotations

import time

from rich import box
from rich.align import Align
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import mascot
from .config import Config
from .engine import STAGES, State

Y, K, D, D2 = mascot.YELLOW, mascot.BLACK, mascot.DIM, "#3A340C"
ON_Y = f"{K} on {Y}"
ON_K = f"{Y} on {K}"

# 3x5 block digits for the big PnL counter
GLYPHS = {
    "0": ["███", "█ █", "█ █", "█ █", "███"], "1": [" █ ", "██ ", " █ ", " █ ", "███"],
    "2": ["███", "  █", "███", "█  ", "███"], "3": ["███", "  █", "███", "  █", "███"],
    "4": ["█ █", "█ █", "███", "  █", "  █"], "5": ["███", "█  ", "███", "  █", "███"],
    "6": ["███", "█  ", "███", "█ █", "███"], "7": ["███", "  █", " █ ", " █ ", " █ "],
    "8": ["███", "█ █", "███", "█ █", "███"], "9": ["███", "█ █", "███", "  █", "███"],
    "+": ["   ", " █ ", "███", " █ ", "   "], "-": ["   ", "   ", "███", "   ", "   "],
    ".": ["   ", "   ", "   ", "   ", " █ "],
}


def big(s: str, style: str) -> Text:
    lines = ["".join(GLYPHS.get(ch, ["   "] * 5)[r] + " " for ch in s) for r in range(5)]
    return Text("\n".join(lines), style=style)


def clock(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


def _header(s: State, now: float) -> Text:
    t = Text(style=ON_Y)
    blink = "■" if int(now * 2) % 2 else "□"
    t.append(f" {blink} BOOP ", style=f"bold {ON_Y}")
    t.append(f"│ {s.mode} ", style=f"bold {K} on {Y}")
    w = s.wallet
    t.append(f"│ {w[:4]}…{w[-4:]} " if len(w) > 12 else f"│ {w} ")
    t.append(f"│ SESSION {clock(now - s.started_at)} ")
    t.append(f"│ scanned {s.scanned} · rejected {s.rejected} ")
    status = s.halted.upper() if s.halted and not s.open else f"{s.stage}ING {s.stage_detail}".replace("BOOPING", "BOOPING!")
    t.append(f"│ {status} ")
    return t


def _left(s: State, cfg: Config, now: float) -> Panel:
    pnl = s.realized + s.unrealized
    # mascot hops for 2s after a boop / bank
    last = s.log[-1] if s.log else (0, "", "")
    fresh = now - last[0] < 2 and last[2] in ("b", "w", "l")
    bubble = {"b": "BOOP!", "w": "BAG!", "l": "oof"}.get(last[2], "") if fresh else ""
    hop = "\n" if not fresh or int(now * 6) % 2 else ""
    head = Table.grid(padding=(0, 2))
    head.add_row(Text(hop) + mascot.render(Y), Text("\nB O O P\n", style=f"bold {ON_Y}") + Text(bubble, style=f"bold {Y} on {K}"))

    closed = s.closed
    wins = sum(1 for p in closed if p.status == "WON")
    stats = Table(box=box.SQUARE, show_header=False, expand=True, style=ON_Y, border_style=K)
    stats.add_column(style=ON_Y)
    stats.add_column(style=ON_Y)
    stats.add_row(Text("START\n", style="bold") + Text(f"{s.start_sol:.3f}"), Text("BALANCE\n", style="bold") + Text(f"{s.balance_sol + sum(p.value_sol for p in s.open):.3f}"))
    stats.add_row(
        Text("WIN RATE\n", style="bold") + Text(f"{wins / len(closed) * 100:.0f}%" if closed else "—"),
        Text("BOOPS\n", style="bold") + Text(f"{len(s.positions):02d}/{cfg.max_boops:02d}"),
    )

    # per-boop bars
    bars = Text()
    mx = max([abs(p.pnl_sol) for p in s.positions] + [1e-9])
    levels = "▁▂▃▄▅▆▇█"
    for p in s.positions[-12:]:
        h = min(7, round(abs(p.pnl_sol) / mx * 7))
        bars.append(levels[h] * 2 if p.pnl_sol >= 0 else "░░", style=ON_Y)
        bars.append(" ", style=ON_Y)
    bars_line = Text("PNL PER BOOP  ", style=f"bold {ON_Y}") + (bars or Text("—", style=ON_Y))

    body = Group(
        head,
        Text("─" * 38, style=ON_Y),
        Text("NET PROFIT / SESSION · SOL", style=f"bold {ON_Y}"),
        Text(""),
        big(f"{pnl:+.2f}", f"bold {ON_Y}"),
        Text(f"realized {s.realized:+.3f} · open {s.unrealized:+.3f}", style=ON_Y),
        Text(""),
        stats,
        Text(""),
        bars_line,
        Text(""),
        Text(f"TP +{cfg.take_profit_pct:.0f}% · SL -{cfg.stop_loss_pct:.0f}% · TRAIL {cfg.trailing_pct:.0f}%", style=ON_Y),
        Text(f"SIZE {cfg.buy_sol} SOL · MAX OPEN {cfg.max_open} · SLIP {cfg.slippage_bps / 100:.1f}%", style=ON_Y),
    )
    return Panel(body, style=ON_Y, border_style=K, box=box.HEAVY, padding=(1, 2))


def _pipeline(s: State, now: float) -> Table:
    t = Table.grid(expand=True, padding=(0, 1))
    for _ in STAGES:
        t.add_column(ratio=1)
    cells = []
    active = STAGES.index(s.stage) if s.stage in STAGES else -1
    for i, name in enumerate(STAGES):
        on = i == active
        style = ON_Y if on else f"{D} on {K}"
        dots = "▮" * (1 + int((now - s.stage_at) * 4) % 6) if on else ""
        txt = Text(f"0{i + 1}  {name}\n", style=f"bold {style}") + Text(f"{dots:<6}", style=style)
        cells.append(Panel(txt, style=style, border_style=Y if on else D2, box=box.SQUARE))
    t.add_row(*cells)
    return t


def _board(s: State, cfg: Config) -> Panel:
    t = Table(box=box.SIMPLE_HEAD, expand=True, style=ON_K, header_style=f"bold {D}", border_style=D2)
    for col, j in (("#", "left"), ("TOKEN", "left"), ("COST", "right"), ("VALUE", "right"), ("PNL SOL", "right"), ("%", "right"), ("HOLD", "right"), ("STATUS", "left")):
        t.add_column(col, justify=j)
    now = time.time()
    for p in s.positions[-12:]:
        live = p.status in ("OPEN", "CLOSING")
        val = p.value_sol if live else p.proceeds_sol
        hold = (now if live else p.closed_at) - p.opened_at
        if p.status == "WON":
            row_style = f"bold {Y} on {K}"
            tag = Text(style=f"{D} on {K}"); tag.append(" BAG ", style=f"bold {ON_Y}"); tag.append(f" {p.exit_reason}")
        elif p.status == "LOST":
            row_style = f"{D} on {K}"
            tag = Text(style=f"{D} on {K}"); tag.append(" oof ", style=f"bold {Y} on {D2}"); tag.append(f" {p.exit_reason}")
        else:
            row_style = f"{Y} on {K}"
            tag = Text(f" {p.status} " + "▮" * (1 + int(now * 3) % 3), style=f"{Y} on {K}")
        t.add_row(f"{p.n:02d}", f"${p.symbol}", f"{p.cost_sol:.3f}", f"{val:.3f}", f"{p.pnl_sol:+.3f}", f"{p.pnl_pct:+.1f}", clock(hold)[3:], tag, style=row_style)
    for i in range(len(s.positions[-12:]), min(cfg.max_boops, 12)):
        t.add_row(f"{i + 1:02d}", "·", "", "", "", "", "", "waiting", style=f"{D2} on {K}")
    return Panel(t, title="[bold]BOOP BOARD", title_align="left", style=ON_K, border_style=Y, box=box.SQUARE)


def _log(s: State, rows: int) -> Panel:
    out = Text()
    for ts, msg, kind in list(s.log)[-rows:]:
        out.append(time.strftime("%H:%M:%S ", time.localtime(ts)), style=D)
        style = {"b": f"bold {Y}", "w": ON_Y, "l": f"bold {Y}", "e": f"{D} italic", "d": Y}.get(kind, Y)
        out.append(msg + "\n", style=style)
    return Panel(out, title="[bold]BOOP.LOG", title_align="left", style=ON_K, border_style=Y, box=box.SQUARE)


def render(s: State, cfg: Config, now: float | None = None) -> Layout:
    now = now or time.time()
    root = Layout()
    root.split_column(Layout(name="head", size=1), Layout(name="body"))
    root["head"].update(Align.left(_header(s, now), style=ON_Y))
    root["body"].split_row(Layout(name="left", size=46), Layout(name="right"))
    root["left"].update(_left(s, cfg, now))
    right = Layout()
    right.split_column(Layout(name="pipe", size=4), Layout(name="board", ratio=3), Layout(name="log", ratio=2))
    right["pipe"].update(_pipeline(s, now))
    right["board"].update(_board(s, cfg))
    right["log"].update(_log(s, 10))
    root["body"]["right"].update(right)
    return root
