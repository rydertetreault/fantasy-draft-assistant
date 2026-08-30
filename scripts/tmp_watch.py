#!/usr/bin/env python3
"""Draft-day watch chunk v2 (untracked helper). Read-only.

Watches synaps1 snapshots and exits when something needs the agent:
  0 = OUR TURN (team 2 on the clock)      2 = draft settings date CHANGED
  3 = chunk elapsed, nothing actionable    4 = poller stale (>STALE_S)
  5 = draft COMPLETE                       6 = OUR PICK CONFIRMED (verify mode)

Env: WATCH_SECS (default 900), VERIFY_PICK_ID (player id to confirm as ours),
     BASELINE_DATE_MS (default 1788040800000).
Prints every new pick as it lands: overall, round.pick, team, player, secs-ago.
"""
import csv, glob, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "data", "synaps1", "snapshots")
WATCH_SECS = int(os.environ.get("WATCH_SECS", "900"))
VERIFY_PICK_ID = int(os.environ.get("VERIFY_PICK_ID", "0"))
BASELINE_DATE_MS = int(os.environ.get("BASELINE_DATE_MS", "1788040800000"))
US, STALE_S, CLOCK_S = 2, 20, 90

names = {}
try:
    with open(os.path.join(ROOT, "data", "synaps1", "board.csv")) as f:
        for r in csv.DictReader(f):
            names[int(r["espn_player_id"])] = f"{r['player']} ({r['pos']})"
except Exception as e:
    print(f"warn: no board names: {e}")

def newest():
    files = sorted(glob.glob(os.path.join(SNAP, "*.json")))
    if not files:
        return None, 999
    f = files[-1]
    return f, time.time() - int(os.path.basename(f)[:-5]) / 1000

seen_made = -1
last_change_t = time.time()
deadline = time.time() + WATCH_SECS
while time.time() < deadline:
    f, age = newest()
    if f is None or age > STALE_S:
        print(f"POLLER STALE: snapshot age {age:.0f}s"); sys.exit(4)
    try:
        d = json.load(open(f))
    except Exception:
        time.sleep(1); continue
    date_ms = d.get("settings", {}).get("draftSettings", {}).get("date", BASELINE_DATE_MS)
    if date_ms != BASELINE_DATE_MS:
        print(f"SETTINGS DATE CHANGED: {BASELINE_DATE_MS} -> {date_ms} (new session id suffix)"); sys.exit(2)
    picks = d.get("draftDetail", {}).get("picks", [])
    made = [p for p in picks if p.get("playerId", 0) > 0]
    if seen_made == -1:
        seen_made = len(made)
        print(f"chunk start: {seen_made} picks made, snapshot age {age:.1f}s")
        if VERIFY_PICK_ID and any(p["playerId"] == VERIFY_PICK_ID and p["teamId"] == US for p in made):
            print("OUR PICK CONFIRMED (already present)"); sys.exit(6)
    elif len(made) > seen_made:
        for p in made[seen_made:]:
            nm = names.get(p["playerId"], f"id={p['playerId']}")
            print(f"PICK {p['overallPickNumber']:3d} (r{p['roundId']}.{p['roundPickNumber']}) team {p['teamId']:2d}: {nm}")
            if VERIFY_PICK_ID and p["playerId"] == VERIFY_PICK_ID and p["teamId"] == US:
                print("OUR PICK CONFIRMED"); sys.exit(6)
        seen_made = len(made)
        last_change_t = time.time()
    if len(made) == len(picks) and picks:
        print("DRAFT COMPLETE"); sys.exit(5)
    nxt = picks[len(made)] if len(made) < len(picks) else None
    if nxt and len(made) > 0 and nxt["teamId"] == US and not VERIFY_PICK_ID:
        elapsed = time.time() - last_change_t
        print(f"OUR TURN: overall {nxt['overallPickNumber']} (r{nxt['roundId']}.{nxt['roundPickNumber']}), "
              f"~{max(0, CLOCK_S - elapsed):.0f}s left on clock, snapshot age {age:.1f}s")
        sys.exit(0)
    time.sleep(1)

print(f"chunk elapsed: {seen_made} picks made, nothing actionable"); sys.exit(3)
