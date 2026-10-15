#!/usr/bin/env python3
"""Render WaveDrom WaveJSON as a text waveform for the terminal.

Usage:
  wave2term.py FILE.json          # read from file
  wave2term.py -e '{signal:[...]}' # inline
  cat x.json | wave2term.py       # stdin

Options:
  --ascii        plain ASCII instead of Unicode box drawing
  --width N      minimum characters per cycle (default 6, multiplied by config.hscale);
                 cycles are widened automatically so every bus label fits
  --color WHEN   auto (default: only when stdout is a terminal), always, never
  --last         re-render the most recently rendered diagram (saved in ~/.cache/wavedrom/last.json)
                 in colour, e.g. from Claude Code:  ! python3 wave2term.py --last
  --no-url       don't print the WaveDrom editor link
  --url-only     only print the editor link

Accepts relaxed WaveJSON (unquoted keys, single quotes, trailing commas),
the same syntax the WaveDrom editor accepts.

Each signal is drawn on three rows (high / middle / low), like WaveDrom:
levels as lines, bus values as hexagons with crossed transitions,
x as a hatched box, z on the middle row.
"""
import argparse
import json
import math
import os
import re
import sys
import urllib.parse

EDITOR = "https://wavedrom.com/editor.html?"
LAST = os.path.join(os.path.expanduser("~"), ".cache", "wavedrom", "last.json")
BUS = set("=23456789")
CLOCK = set("pnPN")
LEVEL_MAP = {"h": "1", "H": "1", "u": "1", "l": "0", "L": "0", "d": "0"}
MAX_AUTO_WIDTH = 16  # don't widen cycles beyond this for long labels; truncate instead

# WaveDrom's colour order ('=' and '2' uncoloured; 3 yellow, 4 orange, 5 blue, 6 cyan, 7 green,
# 8 pink, 9 red), as saturated 256-colour foregrounds for the box outline and label
BUS_FG = {"3": 220, "4": 208, "5": 39, "6": 51, "7": 77, "8": 213, "9": 203}
STYLE_HATCH = "38;5;244"  # x: grey hatching
STYLE_Z = "38;5;33"       # z: blue, as in WaveDrom
STYLE_EDGE = "38;5;196"   # P/N edge arrows
STYLE_NAME = "1"          # signal names in bold


# ---------------------------------------------------------------- parsing

def relaxed_json(text):
    """Convert JSON5-ish WaveJSON into strict JSON and parse it."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            q, j, buf = c, i + 1, []
            while j < n and text[j] != q:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                buf.append('\\"' if text[j] == '"' else text[j])
                j += 1
            out.append('"' + "".join(buf).replace("\\'", "'") + '"')
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c.isalpha() or c in "_$":
            word = re.match(r"[A-Za-z_$][\w$]*", text[i:]).group(0)
            is_key = text[i + len(word):].lstrip().startswith(":")
            out.append('"%s"' % word if is_key else word)
            i += len(word)
        else:
            out.append(c)
            i += 1
    return json.loads(re.sub(r",(\s*[\]}])", r"\1", "".join(out)))


def load(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return relaxed_json(text)


# ---------------------------------------------------------------- waves

HI, LO, MID, BOX, BLANK = "hi", "lo", "mid", "box", "blank"
KIND = {"1": HI, "0": LO, "z": MID, " ": BLANK}


def segments(wave):
    """Split a wave string into [state, ncycles, gap_cycle_offsets]."""
    segs = []
    for ch in wave:
        if ch in ".|":
            if not segs:
                segs.append([" ", 0, []])
            if ch == "|":
                segs[-1][2].append(segs[-1][1])
            segs[-1][1] += 1
        else:
            segs.append([LEVEL_MAP.get(ch, ch), 1, []])
    return segs


def primitives(segs, L, labels):
    """Turn segments into drawing primitives: (kind, start, end, label, edge_mark).

    Clocks expand into alternating hi/lo pieces; bus values and x become boxes.
    """
    labels = list(labels)
    prims, pos = [], 0
    for state, n, _ in segs:
        if state in CLOCK:
            h = max(1, L // 2)
            first, second = (HI, LO) if state in "pP" else (LO, HI)
            mark = {"P": "↑", "N": "↓"}.get(state)
            for k in range(n):
                s = pos + k * L
                prims.append([first, s, s + h, None, mark, state])
                prims.append([second, s + h, s + L, None, None, state])
        elif state in BUS:
            prims.append([BOX, pos, pos + n * L, str(labels.pop(0)) if labels else "", None, state])
        elif state in KIND:
            prims.append([KIND[state], pos, pos + n * L, None, None, state])
        else:  # x and anything unknown
            prims.append([BOX, pos, pos + n * L, None, None, "x"])
        pos += n * L
    # merge adjacent identical levels (e.g. '1' after a clock that ended high)
    merged = []
    for p in prims:
        if merged and p[0] == merged[-1][0] and p[0] in (HI, LO, MID, BLANK):
            merged[-1][2] = p[2]
        else:
            merged.append(p)
    return merged


def draw(prims, total, hatch):
    """Return (rows, styles): three rows of characters and a parallel grid of ANSI SGR codes."""
    rows = [[" "] * total for _ in range(3)]
    styles = [[None] * total for _ in range(3)]

    def put(r, c, ch, style=None):
        if 0 <= c < total:
            rows[r][c] = ch
            if style:
                styles[r][c] = style

    # bodies
    for kind, s, e, label, _, state in prims:
        for c in range(s, e):
            if kind == HI:
                put(0, c, "─")
            elif kind == LO:
                put(2, c, "─")
            elif kind == MID:
                put(1, c, "─", STYLE_Z)
            elif kind == BOX:
                put(0, c, "─")
                put(2, c, "─")
        if kind == BOX:
            inner_s, inner_e = s + (2 if s else 1), e - 1
            if label is None:
                for c in range(inner_s, inner_e):
                    put(1, c, hatch, STYLE_HATCH)
            elif label:
                room = max(0, inner_e - inner_s)
                text = label if len(label) <= room else label[:max(0, room - 1)] + "…"
                off = inner_s + (room - len(text)) // 2
                for k, ch in enumerate(text):
                    put(1, off + k, ch)

    # transitions
    for prev, cur in zip(prims, prims[1:]):
        a, k, b = prev[0], cur[0], cur[1]
        if BLANK in (a, k):
            continue
        if a == BOX and k == BOX:
            put(0, b - 1, "╲"); put(0, b, " "); put(0, b + 1, "╱")
            put(1, b, "╳")
            put(2, b - 1, "╱"); put(2, b, " "); put(2, b + 1, "╲")
        elif a == BOX:
            if k in (LO, MID):
                put(0, b - 1, "╲"); put(0, b, " ")
            if k in (HI, MID):
                put(2, b - 1, "╱"); put(2, b, " ")
            if k == LO:
                put(1, b, "╲")
            elif k == HI:
                put(1, b, "╱")
        elif k == BOX:
            if a == LO:
                put(0, b, " "); put(1, b, "╱"); put(0, b + 1, "╱")
            elif a == HI:
                put(2, b, " "); put(1, b, "╲"); put(2, b + 1, "╲")
            else:  # MID
                put(0, b, "╱"); put(2, b, "╲")
        else:
            edge = {
                (LO, HI): ("┌", "│", "┘"), (HI, LO): ("┐", "│", "└"),
                (MID, HI): ("┌", "┘", None), (MID, LO): (None, "┐", "└"),
                (HI, MID): ("┐", "└", None), (LO, MID): (None, "┌", "┘"),
            }[(a, k)]
            for r, ch in enumerate(edge):
                if ch:
                    put(r, b, ch)
            if cur[4] and a in (HI, LO) and k in (HI, LO):
                put(1, b, cur[4], STYLE_EDGE)  # P / N: arrow on the active edge

    # coloured bus values: outline and label in the value's colour
    for kind, s, e, _, _, state in prims:
        if kind == BOX and state in BUS_FG:
            st = "38;5;%d" % BUS_FG[state]
            for c in range(s, min(e, total)):
                for r in range(3):
                    if rows[r][c] != " ":
                        styles[r][c] = st
    return rows, styles


def cells(chars, styles, table):
    """Turn characters (+ optional SGR codes) into printable cells, one per column."""
    out = []
    for ch, st in zip(chars, styles):
        if table:
            ch = ch.translate(table)
        out.append("\033[%sm%s\033[0m" % (st, ch) if st else ch)
    return out


def overlay_gaps(rows, segs, L, gap):
    pos = 0
    for _, n, gaps in segs:
        for c in gaps:
            col = pos + c * L + L // 2
            for r in rows:
                if col < len(r):
                    r[col] = gap
        pos += n * L


def node_row(nodes, L, total):
    row = [" "] * total
    for i, ch in enumerate(nodes):
        col = i * L + L // 2
        if ch != "." and col < total:
            row[col] = ch
    return "".join(row)


ASCII = str.maketrans({"─": "-", "│": "|", "┌": "+", "┐": "+", "└": "+", "┘": "+",
                       "╱": "/", "╲": "\\", "╳": "X", "…": "~", "↑": "^", "↓": "v",
                       "≈": "~"})


# ---------------------------------------------------------------- layout

def flatten(items, depth=0):
    """Yield (depth, item): item is a signal dict, a group name str, or None (spacer)."""
    for it in items:
        if isinstance(it, list):
            if it and isinstance(it[0], str):
                yield depth, it[0]
                yield from flatten(it[1:], depth + 1)
            else:
                yield from flatten(it, depth + 1)
        elif isinstance(it, dict) and "wave" in it:
            yield depth, it
        else:
            yield depth, None


def signal_info(it):
    period = max(1, int(round(float(it.get("period", 1)))))
    wave = str(it.get("wave", ""))
    data = it.get("data", [])
    if isinstance(data, str):
        data = data.split()
    return period, wave, segments(wave), [str(d) for d in data]


def cycle_width(entries, base):
    """Smallest per-cycle width >= base such that every bus label fits its box."""
    W = base
    for _, it in entries:
        if not isinstance(it, dict):
            continue
        period, _, segs, data = signal_info(it)
        labels = iter(data)
        for state, n, _ in segs:
            if state in BUS:
                label = next(labels, "")
                need = len(label) + 4  # crossing on each side + one space margin
                W = max(W, math.ceil(need / (n * period)))
    return W


def render(doc, base_width=6, ascii_mode=False, color=False):
    hscale = int((doc.get("config") or {}).get("hscale", 1) or 1)
    entries = list(flatten(doc.get("signal", [])))
    W = min(max(base_width * hscale, cycle_width(entries, base_width * hscale)),
            max(MAX_AUTO_WIDTH, base_width * hscale))
    W = max(W, 4)
    hatch = "/" if ascii_mode else "╱"
    gap = "~" if ascii_mode else "≈"
    group_mark = "> " if ascii_mode else "▸ "

    blocks = []  # (label, rows, label_row)
    ncycles = 0
    for depth, it in entries:
        indent = "  " * depth
        if it is None:
            blocks.append(("", [[]], 0))
            continue
        if isinstance(it, str):
            blocks.append((indent + group_mark + it, [[]], 0))
            continue
        period, wave, segs, data = signal_info(it)
        L = W * period
        cycles = sum(n for _, n, _ in segs)
        total = cycles * L
        ncycles = max(ncycles, cycles * period)
        rows, styles = draw(primitives(segs, L, data), total, hatch)
        overlay_gaps(rows, segs, L, gap)
        if not color:
            styles = [[None] * total for _ in rows]
        table = ASCII if ascii_mode else None
        rows = [cells(r, st, table) for r, st in zip(rows, styles)]
        if it.get("node"):
            rows.append(list(node_row(str(it["node"]), L, total)))
        shift = int(round(float(it.get("phase", 0)) * W))
        if shift > 0:
            rows = [r[shift:] for r in rows]
        elif shift < 0:
            rows = [[" "] * -shift + r for r in rows]
        blocks.append((indent + str(it.get("name", "")), rows, 1))

    name_w = max([len(l) for l, _, _ in blocks] + [0]) + 2
    head = doc.get("head") or {}
    tick = head.get("tick", 0)
    tick0 = int(tick) if str(tick).lstrip("-").isdigit() else 0

    out = []
    if head.get("text"):
        out.append(" " * name_w + str(head["text"]))
    hdr = [" "] * (ncycles * W + 4)
    for c in range(ncycles):
        s = str(tick0 + c)
        hdr[c * W:c * W + len(s)] = list(s)
    out.append(" " * name_w + "".join(hdr).rstrip())
    for i, (label, rows, label_row) in enumerate(blocks):
        if i and label_row and blocks[i - 1][2]:
            out.append("")  # breathing room between adjacent signals, like WaveDrom
        for k, r in enumerate(rows):
            while r and r[-1] == " ":
                r = r[:-1]
            name = (label if k == label_row or len(rows) == 1 else "").ljust(name_w)
            if color and name.strip():
                name = name.replace(label, "\033[%sm%s\033[0m" % (STYLE_NAME, label), 1)
            out.append((name + "".join(r)).rstrip())
    edges = doc.get("edge") or []
    if edges:
        out.append("")
        out.append("edges: " + "; ".join(str(e) for e in edges))
    foot = doc.get("foot") or {}
    if foot.get("text"):
        out.append(str(foot["text"]))
    art = "\n".join(out)
    if color:  # merge adjacent cells that share a style
        merge = re.compile(r"\x1b\[([\d;]+)m([^\x1b]*)\x1b\[0m\x1b\[\1m")
        while True:
            merged = merge.sub(lambda m: "\x1b[%sm%s" % (m.group(1), m.group(2)), art)
            if merged == art:
                break
            art = merged
    if ascii_mode:
        art = art.translate(ASCII)  # group marks, title etc.; waves were translated per cell
    return art, name_w + ncycles * W


def editor_url(text):
    return EDITOR + urllib.parse.quote(text, safe="")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("-e", "--expr")
    ap.add_argument("--ascii", action="store_true")
    ap.add_argument("--width", type=int, default=6)
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    ap.add_argument("--last", action="store_true")
    ap.add_argument("--no-url", action="store_true")
    ap.add_argument("--url-only", action="store_true")
    a = ap.parse_args()

    if a.last:
        if not os.path.exists(LAST):
            sys.exit("wave2term: no diagram rendered yet (%s missing)" % LAST)
        with open(LAST, encoding="utf-8") as f:
            text = f.read()
    elif a.expr is not None:
        text = a.expr
    elif a.file and a.file != "-":
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    try:
        doc = load(text)
    except (json.JSONDecodeError, ValueError) as e:
        sys.exit("wave2term: cannot parse WaveJSON: %s" % e)
    if not a.last:
        try:
            os.makedirs(os.path.dirname(LAST), exist_ok=True)
            with open(LAST, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    if not a.url_only:
        # --last exists to view colour (e.g. via Claude Code's `!`, which isn't a tty), so it forces colour
        color = a.color == "always" or (a.color == "auto" and (a.last or sys.stdout.isatty())
                                         and not os.environ.get("NO_COLOR"))
        art, width = render(doc, a.width, a.ascii, color)
        print(art)
        if width > 120:
            print("wave2term: warning: %d columns wide; consider fewer cycles or a smaller --width" % width,
                  file=sys.stderr)
    if not a.no_url:
        compact = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        print(("\n" if not a.url_only else "") + "WaveDrom editor: " + editor_url(compact))


if __name__ == "__main__":
    main()
