#!/usr/bin/env python3
"""Fast turn-watcher on room-DOM snapshots (untracked helper). Read-only.

Exit codes:
  0 = OUR TURN (enabled DRAFT buttons appeared)   4 = feed stale (>6s)
  3 = chunk elapsed, nothing actionable           5 = frozen-room alarm ticks

Prints clock + new pick-history lines as they change. Env: WATCH_SECS=240,
TEAM=mock.
"""
import glob, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEAM = os.environ.get("TEAM", "mock")
SNAP = os.path.join(ROOT, "data", TEAM, "room_snapshots")
WATCH_SECS = int(os.environ.get("WATCH_SECS", "240"))

def newest():
    files = sorted(glob.glob(os.path.join(SNAP, "*.json")))
    if not files:
        return None, 999
    f = files[-1]
    return f, time.time() - int(os.path.basename(f)[:-5]) / 1000

last_hist = None
last_clock = None
deadline = time.time() + WATCH_SECS
while time.time() < deadline:
    f, age = newest()
    if f is None or age > 6:
        print(f"FEED STALE: {age:.0f}s"); sys.exit(4)
    try:
        d = json.load(open(f))
    except Exception:
        time.sleep(0.3); continue
    hist = d.get("pick_history_text") or ""
    if hist != last_hist:
        new = hist[len(last_hist):] if last_hist and hist.startswith(last_hist) else hist
        print(f"[{d.get('round_text')}] {d.get('clock_text')} | history+: {new[-200:]}")
        last_hist = hist
    if d.get("frozen_ticks", 0) >= 10:
        print(f"FROZEN ROOM: {d['frozen_ticks']} ticks"); sys.exit(5)
    if d.get("enabled_draft_buttons", 0) > 0:
        print(f"OUR TURN: {d['enabled_draft_buttons']} DRAFT buttons enabled, "
              f"clock {d.get('clock_text')} ({d.get('clock_seconds')}s), age {age:.1f}s")
        for r in d.get("draft_button_rows") or []:
            print(f"  row: {r}")
        sys.exit(0)
    if d.get("clock_text") != last_clock:
        last_clock = d.get("clock_text")
    time.sleep(0.3)

print("chunk elapsed, nothing actionable"); sys.exit(3)
