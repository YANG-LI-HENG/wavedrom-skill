#!/bin/bash
# Install the Python WaveDrom port (used by wave2img.py for SVG output) into its own venv.
# Works without sudo, even when python3-venv/ensurepip is missing.
set -e
VENV="$HOME/.local/share/wavedrom-venv"
python3 -m venv --without-pip "$VENV"
if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    tmp=$(mktemp -d)
    curl -sSL https://bootstrap.pypa.io/get-pip.py -o "$tmp/get-pip.py"
    "$VENV/bin/python" -I "$tmp/get-pip.py" -q
    rm -rf "$tmp"
fi
"$VENV/bin/python" -m pip install -q wavedrom
"$VENV/bin/python" -c "import wavedrom; print('wavedrom installed in $VENV')"
