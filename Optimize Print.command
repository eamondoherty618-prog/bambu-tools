#!/bin/bash
# Double-click this. It asks for a part file (drag it in), then material + strength,
# then installs a ready-to-pick preset into Bambu Studio.
cd "$HOME/bambu-tools" || exit 1
echo "========================================"
echo "   Bambu X1C Print Optimizer"
echo "========================================"
echo
echo "Drag your part file (STL / STEP / 3MF) into this window, then press Enter:"
read -r RAW
# a drag-and-dropped path arrives with spaces/& backslash-escaped and maybe quoted
FILE=$(printf '%s' "$RAW" | sed -e 's/\\//g' -e "s/^[[:space:]]*//" -e "s/[[:space:]]*$//" -e "s/^['\"]//" -e "s/['\"]$//")
if [ ! -f "$FILE" ]; then
  echo; echo "Couldn't find that file:"; echo "  $FILE"
  echo; echo "Press Enter to close."; read; exit 1
fi
"$HOME/bambu-tools/venv/bin/python" "$HOME/bambu-tools/bambu_optimize.py" "$FILE"
echo
echo "Press Enter to close."
read
