#!/bin/zsh
# StockScout daily job. Lives in ~/stockscout_jobs/ (NOT in ~/Desktop — macOS blocks launchd there).
# Runs the morning digest and posts it to the StockScout Discord channel.
set -u
PROJECT="$HOME/stockscout"
LOG="$HOME/stockscout_jobs/stockscout_daily.log"
cd "$PROJECT" || { echo "$(date) cannot cd to $PROJECT" >> "$LOG"; exit 1; }
echo "===== $(date) StockScout daily start =====" >> "$LOG"
/usr/bin/python3 run_scout.py daily --post >> "$LOG" 2>&1
RC=$?
echo "===== $(date) exit $RC =====" >> "$LOG"
exit $RC
