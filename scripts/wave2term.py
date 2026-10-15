#!/usr/bin/env python3
"""Render WaveDrom WaveJSON as a text waveform for the terminal.

Usage:
  wave2term.py FILE.json          # read from file
  wave2term.py -e '{signal:[...]}' # inline
  cat x.json | wave2term.py       # stdin

Options:
  --ascii        plain ASCII instead of Unicode box drawing
  --width N      characters per cycle (default 4, multiplied by config.hscale)
  --no-url       don't print the WaveDrom editor link
  --url-only     only print the editor link

Accepts relaxed WaveJSON (unquoted keys, single quotes, trailing commas),
the same syntax the WaveDrom editor accepts.
"""
import argparse
import json
import re
import sys
import urllib.parse

EDITOR = "https://wavedrom.com/editor.html?"
BUS = set("=23456789")
CLOCK = set("pnPN")
LEVEL_MAP = {"h": "1", "H": "1", "u": "1", "l": "0", "L": "0", "d": "0"}


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
                if text[j] == '"':
                    buf.append('\\"')
                else:
                    buf.append(text[j])
                j += 1
            out.append('"' + "".join(buf).replace("\\'", "'") + '"')
            i = j + 1
        elif c == "/" and text[i:i + 2] == "//":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and text[i:i + 2] == "/*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c.isalpha() or c in "_$":
            m = re.match(r"[A-Za-z_$][\w$]*", text[i:])
            word = m.group(0)
            rest = text[i + len(word):].lstrip()
            if rest.startswith(":") or word not in ("true", "false", "null"):
                out.append('"%s"' % word if rest.startswith(":") else word)
            else:
                out.append(word)
            i += len(word)
        else:
            out.append(c)
            i += 1
    s = "".join(out)
    s = re.sub(r",(\s*[\]}])", r"\1", s)
    return json.loads(s)


def load(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return relaxed_json(text)


# ---------------------------------------------------------------- glyphs

class Glyphs:
    def __init__(self, ascii_mode):
        self.ascii = ascii_mode
        self.cross = "X" if ascii_mode else "╳"
        self.gap = "~" if ascii_mode else "≈"
        self.group = "> " if ascii_mode else "▸ "

    def two_row(self, top, bot):
        if not self.ascii:
            return top, bot
        t = {"─": "_", "┌": " ", "┐": " ", "░": "x", "┄": " "}
        b = {"─": "_", "┘": "|", "└": "|", "░": "x", "┄": "-", "↑": "^", "↓": "v"}
        return ("".join(t.get(c, c) for c in top),
                "".join(b.get(c, c) for c in bot))

    def one_row(self, row):
        if not self.ascii:
            return row
        m = {"‾": "^", "░": "x", "─": "-", "╳": "X", "≈": "~"}
        return "".join(m.get(c, c) for c in row)


# ---------------------------------------------------------------- segments

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


def clock_cell(state, L, prev_level):
    h = max(1, L // 2)
    lo = L - h
    if state in "pP":
        if prev_level == "1":
            top, bot = "─" * h, " " * h
        else:
            top, bot = "┌" + "─" * (h - 1), ("↑" if state == "P" else "┘") + " " * (h - 1)
        top += "┐" + " " * (lo - 1)
        bot += "└" + "─" * (lo - 1)
        return top, bot, "0"
    if prev_level == "0":
        top, bot = " " * h, "─" * h
    else:
        top, bot = "┐" + " " * (h - 1), ("↓" if state == "N" else "└") + "─" * (h - 1)
    top += "┌" + "─" * (lo - 1)
    bot += "┘" + " " * (lo - 1)
    return top, bot, "1"


FILL = {"1": ("─", " "), "0": (" ", "─"), "x": ("░", "░"), "z": (" ", "┄"), " ": (" ", " ")}


def render_bits(segs, L):
    top, bot = [], []
    level = None
    for state, n, _ in segs:
        if state in CLOCK:
            for _ in range(n):
                t, b, level = clock_cell(state, L, level)
                top.append(t)
                bot.append(b)
            continue
        ft, fb = FILL.get(state, FILL["x"])
        t, b = ft * (n * L), fb * (n * L)
        if level == "0" and state == "1":
            t, b = "┌" + t[1:], "┘" + b[1:]
        elif level == "1" and state == "0":
            t, b = "┐" + t[1:], "└" + b[1:]
        top.append(t)
        bot.append(b)
        level = state if state in "01" else None
    return "".join(top), "".join(bot)


def render_bus(segs, L, labels, g):
    row, labels = [], list(labels)
    for k, (state, n, _) in enumerate(segs):
        width = n * L
        if state in BUS:
            label = str(labels.pop(0)) if labels else ""
            body = (" " + label)[:width - (1 if k else 0)]
            cell = body.ljust(width - (1 if k else 0))
        elif state in CLOCK:
            cell = ("┌┐" * width)[:width - (1 if k else 0)]
        else:
            ch = {"1": "‾", "0": "_", "z": "─", "x": "░", " ": " "}.get(state, "░")
            cell = ch * (width - (1 if k else 0))
        row.append((g.cross if k else "") + cell)
    if segs and segs[-1][0] in BUS:
        row.append(g.cross)  # close the last value so it doesn't look cut off
    return "".join(row)


def overlay_gaps(rows, segs, L, g):
    pos = 0
    rows = [list(r) for r in rows]
    for _, n, gaps in segs:
        for c in gaps:
            col = pos + c * L + L // 2
            hit = False
            for r in rows:
                if col < len(r) and r[col] != " ":
                    r[col] = g.gap
                    hit = True
            if not hit and rows and col < len(rows[0]):
                rows[0][col] = g.gap
        pos += n * L
    return ["".join(r) for r in rows]


def node_row(nodes, L):
    row = [" "] * (len(nodes) * L)
    for i, ch in enumerate(nodes):
        if ch != ".":
            row[i * L + L // 2] = ch
    return "".join(row)


# ---------------------------------------------------------------- layout

def flatten(items, depth=0):
    """Yield (depth, item) where item is a signal dict, group name str, or None (spacer)."""
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


def render(doc, cycle_width=4, ascii_mode=False):
    g = Glyphs(ascii_mode)
    hscale = int((doc.get("config") or {}).get("hscale", 1) or 1)
    W = max(2, cycle_width * hscale)
    entries = list(flatten(doc.get("signal", [])))

    lines = []  # (label, [rows])
    ncycles = 0
    for depth, it in entries:
        indent = "  " * depth
        if it is None:
            lines.append(("", [""]))
            continue
        if isinstance(it, str):
            lines.append((indent + g.group + it, []))
            continue
        period = max(1, int(round(float(it.get("period", 1)))))
        L = W * period
        wave = str(it.get("wave", ""))
        segs = segments(wave)
        data = it.get("data", [])
        if isinstance(data, str):
            data = data.split()
        if any(c in BUS for c in wave):
            rows = [g.one_row(overlay_gaps([render_bus(segs, L, data, g)], segs, L, g)[0])]
        else:
            rows = list(g.two_row(*overlay_gaps(list(render_bits(segs, L)), segs, L, g)))
        if it.get("node"):
            rows.append(node_row(str(it["node"]), L))
        shift = int(round(float(it.get("phase", 0)) * W))
        if shift > 0:
            rows = [r[shift:] for r in rows]
        elif shift < 0:
            rows = [" " * -shift + r for r in rows]
        lines.append((indent + str(it.get("name", "")), rows))
        ncycles = max(ncycles, sum(n for _, n, _ in segs) * period)

    name_w = max([len(l) for l, _ in lines] + [0]) + 2
    head = doc.get("head") or {}
    tick0 = int(head.get("tick", 0)) if str(head.get("tick", "")).lstrip("-").isdigit() else 0

    out = []
    if head.get("text"):
        out.append(str(head["text"]))
    step = 1 if W >= 3 else 5
    hdr = [" "] * (ncycles * W + 4)
    for c in range(0, ncycles, step):
        s = str(tick0 + c)
        hdr[c * W:c * W + len(s)] = list(s)
    out.append(" " * name_w + "".join(hdr).rstrip())
    for label, rows in lines:
        if not rows:
            out.append(label)
            continue
        for k, r in enumerate(rows):
            out.append(((label if k == 0 else "").ljust(name_w) + r).rstrip())
    edges = doc.get("edge") or []
    if edges:
        out.append("")
        out.append("edges: " + "; ".join(str(e) for e in edges))
    foot = doc.get("foot") or {}
    if foot.get("text"):
        out.append(str(foot["text"]))
    return "\n".join(out), name_w + ncycles * W


def editor_url(text):
    return EDITOR + urllib.parse.quote(text, safe="")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("-e", "--expr")
    ap.add_argument("--ascii", action="store_true")
    ap.add_argument("--width", type=int, default=4)
    ap.add_argument("--no-url", action="store_true")
    ap.add_argument("--url-only", action="store_true")
    a = ap.parse_args()

    if a.expr is not None:
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

    if not a.url_only:
        art, width = render(doc, a.width, a.ascii)
        print(art)
        if width > 110:
            print("wave2term: warning: %d columns wide; consider fewer cycles or --width 3" % width,
                  file=sys.stderr)
    if not a.no_url:
        compact = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        print(("\n" if not a.url_only else "") + "WaveDrom editor: " + editor_url(compact))


if __name__ == "__main__":
    main()
