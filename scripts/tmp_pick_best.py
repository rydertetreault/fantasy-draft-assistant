#!/usr/bin/env python3
"""Best-available pick from newest room snapshot + board (untracked helper).

Prints a JSON actuate payload for the top board player NOT seen in the room's
pick history and NOT already ours (data/<TEAM>/our_picks.json). Simple caps:
skip QB/TE after 1, K/DST entirely (mock rehearsal). Matches history against
full name and "F. Last" abbreviation.

Env: TEAM=mock, LEAGUE_ID (mock room league id, required), TEAM_ID (our slot).
"""
import csv, glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEAM = os.environ.get("TEAM", "mock")
LEAGUE_ID = int(os.environ["LEAGUE_ID"])
TEAM_ID = int(os.environ.get("TEAM_ID", "0"))
SNAP = os.path.join(ROOT, "data", TEAM, "room_snapshots")
OURS = os.path.join(ROOT, "data", TEAM, "our_picks.json")

snap = sorted(glob.glob(os.path.join(SNAP, "*.json")))[-1]
hist = (json.load(open(snap)).get("pick_history_text") or "").lower()
ours = json.load(open(OURS)) if os.path.exists(OURS) else []
our_pos = [p["pos"] for p in ours]
our_ids = {p["playerId"] for p in ours}

def taken(name):
    full = name.lower()
    parts = name.split()
    abbr = f"{parts[0][0]}. {' '.join(parts[1:])}".lower() if len(parts) > 1 else full
    return full in hist or abbr in hist

with open(os.path.join(ROOT, "data", "synaps1", "board.csv")) as f:
    for r in csv.DictReader(f):
        pos = r["pos"]
        if pos in ("K", "DST", "D/ST"):
            continue
        if pos == "QB" and our_pos.count("QB") >= 1:
            continue
        if pos == "TE" and our_pos.count("TE") >= 1:
            continue
        pid = int(r["espn_player_id"])
        if pid in our_ids or taken(r["player"]):
            continue
        print(json.dumps({"playerId": pid, "playerName": r["player"],
                          "leagueId": LEAGUE_ID, "teamId": TEAM_ID,
                          "pos": pos}))
        sys.exit(0)

print("NO CANDIDATE", file=sys.stderr)
sys.exit(1)
