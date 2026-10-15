#!/usr/bin/env python3
"""Render WaveDrom WaveJSON to an HTML page (official WaveDrom renderer) and an SVG file.

Usage:
  wave2img.py -n NAME -e '{signal:[...]}'   # inline
  wave2img.py -n NAME FILE.json             # from file
  cat x.json | wave2img.py -n NAME          # stdin

Writes NAME.json, NAME.html and the image (NAME.png by default) into the
output directory (default ~/waveforms) and opens the HTML in the browser.

Options:
  -n, --name NAME     file name (default: from head.text, else a timestamp)
  -o, --out DIR       output directory
  -d, --desc TEXT     a caption shown under the diagram on the HTML page
  -f, --format FMT    image format: png (white background), svg, both, none
  --scale N           PNG scale factor (default 2)
  --overwrite         replace existing files with the same name (default: add _2, _3, ...)
  --artifact PATH     instead of the files above, write one artifact page (templates/artifact.html
                      filled in) to PATH, for Claude Code Desktop / claude.ai to show inline
  --no-open           don't open the browser

Defaults come from ~/.config/wavedrom-skill/config.json, e.g.
  {"format": "png", "out": "~/waveforms", "scale": 2, "open": true}
and command-line options override them.

The HTML loads WaveDrom from cdnjs, so the diagram looks exactly like
wavedrom.com; offline it shows the local image instead. The image comes
from the Python port of WaveDrom (see setup.sh), which may differ from
the official renderer in small details.
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
CONFIG = os.path.expanduser("~/.config/wavedrom-skill/config.json")
DEFAULTS = {"format": "png", "out": "~/waveforms", "scale": 2, "open": True}
FORMATS = ("png", "svg", "both", "none")
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
    if (!svg) {{ alert('Offline: use the image file next to this page.'); throw 0; }}
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


RENDER = """
import sys, wavedrom
base, fmt, scale = sys.argv[1], sys.argv[2], float(sys.argv[3])
svg = wavedrom.render(sys.stdin.read()).tostring()
if fmt in ("svg", "both"):
    open(base + ".svg", "w", encoding="utf-8").write(svg)
if fmt in ("png", "both"):
    import cairosvg
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=base + ".png",
                     background_color="white", scale=scale)
"""


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print("wave2img: ignoring %s: %s" % (CONFIG, e), file=sys.stderr)
    return cfg


def render_images(strict_json, base, fmt, scale):
    """Images via the Python WaveDrom port in its venv; returns an error string or None."""
    if not os.path.exists(VENV_PY):
        return "Python WaveDrom not installed (run %s)" % os.path.join(os.path.dirname(__file__), "setup.sh")
    r = subprocess.run([VENV_PY, "-I", "-c", RENDER, base, fmt, str(scale)], input=strict_json,
                       text=True, capture_output=True, timeout=60)
    if r.returncode != 0:
        lines = (r.stderr or r.stdout).strip().splitlines()
        return lines[-1] if lines else "exit %d" % r.returncode
    return None


def write_artifact(doc, path, desc, name):
    """Fill templates/artifact.html: no ~/waveforms files, no browser."""
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "artifact.html")
    with open(tpl, encoding="utf-8") as f:
        page = f.read()
    head = doc.get("head") or {}
    compact = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    fill = {
        "__TITLE__": html.escape(str(head.get("text") or name or "Waveform")),
        "__WAVEJSON__": json.dumps(doc, ensure_ascii=False, indent=1).replace("</", "<\\/"),
        "__CAPTION__": html.escape(desc),
        "__EDITOR_URL__": html.escape(EDITOR + urllib.parse.quote(compact, safe="")),
    }
    for key, value in fill.items():
        page = page.replace(key, value)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    print("Artifact page: " + os.path.abspath(path))


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
    ap.add_argument("-o", "--out")
    ap.add_argument("-d", "--desc", default="")
    ap.add_argument("-f", "--format", choices=FORMATS)
    ap.add_argument("--scale", type=float)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--artifact", metavar="PATH")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    fmt = a.format or cfg["format"]
    if fmt not in FORMATS:
        sys.exit("wave2img: format must be one of %s (got %r in %s)" % (", ".join(FORMATS), fmt, CONFIG))
    out_dir = os.path.expanduser(a.out or cfg["out"])
    scale = a.scale or float(cfg["scale"])
    should_open = cfg["open"] and not a.no_open

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
    if a.artifact:
        write_artifact(doc, a.artifact, a.desc, a.name)
        return
    now = datetime.datetime.now()
    name = slug(a.name or "") or slug(str(head.get("text", ""))) or now.strftime("wave_%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(os.path.abspath(out_dir), name)
    if not a.overwrite:  # keep earlier diagrams: pick the first free name_2, name_3, ...
        n = 1
        while any(os.path.exists(base + ext) for ext in (".json", ".html", ".png", ".svg")):
            n += 1
            base = os.path.join(os.path.abspath(out_dir), "%s_%d" % (name, n))
        name = os.path.basename(base)

    strict = json.dumps(doc, ensure_ascii=False, indent=1)
    with open(base + ".json", "w", encoding="utf-8") as f:
        f.write(strict + "\n")

    images, img_err = [], None
    if fmt != "none":
        for ext in ("png", "svg"):  # drop stale images from an earlier run with another format
            if os.path.exists(base + "." + ext):
                os.remove(base + "." + ext)
        img_err = render_images(strict, base, fmt, scale)
        if img_err is None:
            images = [ext for ext in ("png", "svg") if os.path.exists(base + "." + ext)]

    files = [name + ".json", name + ".html"] + [name + "." + ext for ext in images]
    page = PAGE.format(
        title=html.escape(str(head.get("text") or name)),
        cdn=WAVEDROM_CDN,
        stamp=now.strftime("%Y-%m-%d %H:%M"),
        files=html.escape(" · ".join(files)),
        wavejson=strict.replace("</", "<\\/"),
        fallback=('<img src="%s.%s" alt="waveform">' % (html.escape(name), images[0])) if images
        else "<p>Offline and no image available: open the WaveDrom editor link when online.</p>",
        desc=html.escape(a.desc),
        editor=html.escape(EDITOR + urllib.parse.quote(json.dumps(doc, ensure_ascii=False,
                                                                  separators=(",", ":")), safe="")),
        name_js=json.dumps(name),
    )
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(page)

    print("HTML: " + base + ".html")
    for ext in images:
        print("%-5s %s.%s" % (ext.upper() + ":", base, ext))
    if img_err:
        print("Image: skipped (%s)" % img_err, file=sys.stderr)
    print("JSON: " + base + ".json")
    if should_open:
        open_in_browser(base + ".html")


if __name__ == "__main__":
    main()
