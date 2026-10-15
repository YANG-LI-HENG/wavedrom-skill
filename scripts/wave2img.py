#!/usr/bin/env python3
"""Render WaveDrom WaveJSON to an HTML page (official WaveDrom renderer) and an SVG file.

Usage:
  wave2img.py -n NAME -e '{signal:[...]}'   # inline
  wave2img.py -n NAME FILE.json             # from file
  cat x.json | wave2img.py -n NAME          # stdin

Writes NAME.json, NAME.html and NAME.svg into the output directory
(default ~/waveforms) and opens the HTML in the Windows default browser.

Options:
  -n, --name NAME   file name (default: from head.text, else a timestamp)
  -o, --out DIR     output directory (default ~/waveforms)
  -d, --desc TEXT   a caption shown under the diagram on the HTML page
  --no-open         don't open the browser
  --no-svg          skip the SVG file

The HTML loads WaveDrom from cdnjs, so the diagram looks exactly like
wavedrom.com; it falls back to the embedded SVG when offline. The SVG
comes from the Python port of WaveDrom (see setup.sh), which may differ
from the official renderer in small details.
"""
import argparse
import datetime
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wave2term import load  # relaxed WaveJSON parser  # noqa: E402

VENV_PY = os.path.expanduser("~/.local/share/wavedrom-venv/bin/python")
WAVEDROM_CDN = "https://cdnjs.cloudflare.com/ajax/libs/wavedrom/3.5.0/"
EDITOR = "https://wavedrom.com/editor.html?"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="{cdn}skins/default.js"></script>
<script src="{cdn}wavedrom.min.js"></script>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; background: #fff; }}
  h1 {{ font-size: 1.2rem; margin: 0 0 .25rem; }}
  .meta {{ color: #777; font-size: .85rem; margin-bottom: 1.25rem; }}
  .diagram {{ overflow-x: auto; padding: 1rem; border: 1px solid #ddd; border-radius: 8px; }}
  .desc {{ margin-top: 1rem; white-space: pre-wrap; line-height: 1.5; max-width: 60rem; }}
  .bar {{ margin-top: 1rem; display: flex; gap: .5rem; flex-wrap: wrap; }}
  button, a.btn {{ font: inherit; font-size: .85rem; padding: .35rem .8rem; border: 1px solid #bbb;
    border-radius: 6px; background: #f6f6f6; color: #222; cursor: pointer; text-decoration: none; }}
  button:hover, a.btn:hover {{ background: #eee; }}
  #fallback {{ display: none; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">{stamp} &middot; {files}</div>
<div class="diagram">
  <div id="live"><script type="WaveDrom">{wavejson}</script></div>
  <div id="fallback">{fallback}</div>
</div>
<div class="desc">{desc}</div>
<div class="bar">
  <button onclick="save('svg')">Download SVG</button>
  <button onclick="save('png')">Download PNG</button>
  <a class="btn" href="{editor}" target="_blank" rel="noopener">Open in WaveDrom editor</a>
</div>
<script>
  const NAME = {name_js};
  window.addEventListener('load', () => {{
    if (window.WaveDrom) {{
      WaveDrom.ProcessAll();
    }} else {{  // offline: show the SVG rendered locally
      document.getElementById('live').style.display = 'none';
      document.getElementById('fallback').style.display = 'block';
    }}
  }});
  function svgText() {{
    const svg = document.querySelector('#live svg');
    if (!svg) {{ alert('Offline: use the ' + NAME + '.svg file next to this page.'); throw 0; }}
    const clone = svg.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    return [new XMLSerializer().serializeToString(clone), svg.getBoundingClientRect()];
  }}
  function download(blob, ext) {{
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = NAME + '.' + ext;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }}
  function save(kind) {{
    const [text, box] = svgText();
    const blob = new Blob([text], {{ type: 'image/svg+xml' }});
    if (kind === 'svg') return download(blob, 'svg');
    const img = new Image(), scale = 2;
    img.onload = () => {{
      const c = document.createElement('canvas');
      c.width = box.width * scale; c.height = box.height * scale;
      const g = c.getContext('2d');
      g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(img, 0, 0, c.width, c.height);
      c.toBlob(b => download(b, 'png'));
    }};
    img.src = URL.createObjectURL(blob);
  }}
</script>
</body>
</html>
"""


def slug(text):
    s = re.sub(r"[^\w\-]+", "_", text.strip(), flags=re.UNICODE).strip("_")
    return s[:60] or None


def render_svg(strict_json, path):
    """SVG via the Python WaveDrom port in its venv; returns an error string or None."""
    if not os.path.exists(VENV_PY):
        return "Python WaveDrom not installed (run %s)" % os.path.join(os.path.dirname(__file__), "setup.sh")
    code = "import sys, wavedrom; wavedrom.render(sys.stdin.read()).saveas(sys.argv[1])"
    r = subprocess.run([VENV_PY, "-I", "-c", code, path], input=strict_json, text=True,
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        return lines[-1] if lines else "exit %d" % r.returncode
    return None


def open_in_browser(path):
    if shutil.which("wslpath") and shutil.which("explorer.exe"):
        win = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True).stdout.strip()
        subprocess.run(["explorer.exe", win], capture_output=True)  # exits 1 even on success
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", path], capture_output=True)
    elif shutil.which("open"):
        subprocess.run(["open", path], capture_output=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("-e", "--expr")
    ap.add_argument("-n", "--name")
    ap.add_argument("-o", "--out", default=os.path.expanduser("~/waveforms"))
    ap.add_argument("-d", "--desc", default="")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--no-svg", action="store_true")
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
        sys.exit("wave2img: cannot parse WaveJSON: %s" % e)

    head = doc.get("head") or {}
    now = datetime.datetime.now()
    name = slug(a.name or "") or slug(str(head.get("text", ""))) or now.strftime("wave_%Y%m%d_%H%M%S")
    os.makedirs(a.out, exist_ok=True)
    base = os.path.join(os.path.abspath(a.out), name)

    strict = json.dumps(doc, ensure_ascii=False, indent=1)
    with open(base + ".json", "w", encoding="utf-8") as f:
        f.write(strict + "\n")

    has_svg, svg_err = False, None
    if not a.no_svg:
        svg_err = render_svg(strict, base + ".svg")
        has_svg = svg_err is None

    files = [name + ".json", name + ".html"] + ([name + ".svg"] if has_svg else [])
    page = PAGE.format(
        title=html.escape(str(head.get("text") or name)),
        cdn=WAVEDROM_CDN,
        stamp=now.strftime("%Y-%m-%d %H:%M"),
        files=html.escape(" · ".join(files)),
        wavejson=strict.replace("</", "<\\/"),
        fallback=('<img src="%s.svg" alt="waveform">' % html.escape(name)) if has_svg
        else "<p>Offline and no SVG available: open the WaveDrom editor link when online.</p>",
        desc=html.escape(a.desc),
        editor=html.escape(EDITOR + urllib.parse.quote(json.dumps(doc, ensure_ascii=False,
                                                                  separators=(",", ":")), safe="")),
        name_js=json.dumps(name),
    )
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(page)

    print("HTML: " + base + ".html")
    if has_svg:
        print("SVG:  " + base + ".svg")
    elif svg_err:
        print("SVG:  skipped (%s)" % svg_err, file=sys.stderr)
    print("JSON: " + base + ".json")
    if not a.no_open:
        open_in_browser(base + ".html")


if __name__ == "__main__":
    main()
