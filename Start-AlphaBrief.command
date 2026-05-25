#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
bash "$DIR/scripts/start-macos.sh"
status=$?
if [ "$status" -ne 0 ]; then
  echo ""
  echo "AlphaBrief Agent exited with status $status."
  echo "See logs in: $DIR/data/logs/"
  echo ""
  read -n 1 -s -r -p "Press any key to close this window..."
  echo ""
fi
exit $status
