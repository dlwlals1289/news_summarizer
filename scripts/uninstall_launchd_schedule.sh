#!/bin/bash
set -euo pipefail

LABEL="com.news-summarizer.daily"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"

echo "Removed launchd job: $LABEL"
echo "Deleted plist: $PLIST_PATH"
