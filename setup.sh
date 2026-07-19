#!/bin/bash
# One-time setup: creates the Python environment the tools need.
set -e
cd "$(dirname "$0")"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
echo
echo "Done. Try:  ./bambu-optimize path/to/part.stl --material PETG --strength functional"
