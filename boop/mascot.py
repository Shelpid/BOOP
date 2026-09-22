"""The little guy. 13x13 pixels, rendered with half-blocks."""
from rich.style import Style
from rich.text import Text

SPRITE = [
    "..##########.",
    ".#YYYYYYYYYY#",
    "#YYY####Y####",
    "#############",
    "#YYY####Y####",
    "#YYYYYYYY#YY#",
    ".###YY#YY#YY#",
    "##Y#YYY###YY#",
    "#YY#YYYYYYY#.",
    "#YY##YYYYYY#.",
    "#YY#Y######..",
    "##Y#YYY#YY#..",
    ".##########..",
]

YELLOW = "#FFE93B"
BLACK = "#0A0905"
DIM = "#8C7D14"
_COL = {"#": BLACK, "Y": YELLOW}


def render(bg: str = YELLOW, flip: bool = False) -> Text:
    rows = [r[::-1] if flip else r for r in SPRITE] + ["." * 13]
    out = Text()
    for y in range(0, len(rows) - 1, 2):
        top, bot = rows[y], rows[y + 1]
        for a, b in zip(top, bot):
            ca, cb = _COL.get(a, bg), _COL.get(b, bg)
            out.append("▀", Style(color=ca, bgcolor=cb))
        out.append("\n")
    out.rstrip()
    return out
