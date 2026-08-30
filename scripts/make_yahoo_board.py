#!/usr/bin/env python3
"""Build the Yahoo half-PPR draft board from ESPN's projection data.

ESPN per-stat projections include receptions (stat id 53). Our raw fetch was
made in a full-PPR league context, so:  half_ppr = appliedTotal - 0.5 * rec.
Everything else (names, positions, ADP as board-pressure proxy) carries over;
name-substring matching is the cross-platform glue in the draft room.

Usage: .venv/bin/python scripts/make_yahoo_board.py [out_csv]
       (default out: data/yahoo/board.csv; input: data/raw/players.json)
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "players.json")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "yahoo", "board.csv")

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
RECEPTIONS_STAT = "53"

d = json.load(open(RAW))
players = d.get("players", d if isinstance(d, list) else [])
rows = []
for p in players:
    pl = p.get("player", p)
    pos = POS.get(pl.get("defaultPositionId"))
    if not pos:
        continue
    proj = None
    rec = 0.0
    for s in pl.get("stats", []):
        if s.get("seasonId") == 2026 and s.get("statSourceId") == 1 and s.get("statSplitTypeId") == 0:
            proj = s.get("appliedTotal")
            rec = float((s.get("stats") or {}).get(RECEPTIONS_STAT, 0.0) or 0.0)
            break
    if proj is None or float(proj) <= 0:
        continue
    half_ppr = float(proj) - 0.5 * rec
    own = pl.get("ownership") or {}
    adp = own.get("averageDraftPosition")
    rows.append({
        "player": pl.get("fullName", ""),
        "espn_player_id": pl.get("id", 0),
        "pos": pos,
        "nfl_team_id": pl.get("proTeamId", 0),
        "projection": round(half_ppr, 4),
        "full_ppr_projection": round(float(proj), 4),
        "receptions": round(rec, 2),
        "adp": round(float(adp), 2) if adp else 999.0,
        "tier": 0,
    })

rows.sort(key=lambda r: -r["projection"])
# simple per-position tiers: rank buckets of 6
rank_at_pos: dict[str, int] = {}
for r in rows:
    rank_at_pos[r["pos"]] = rank_at_pos.get(r["pos"], 0) + 1
    r["tier"] = (rank_at_pos[r["pos"]] - 1) // 6 + 1

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"wrote {len(rows)} players -> {OUT}")
print("top 5 half-PPR:", [f'{r["player"]} {r["pos"]} {r["projection"]:.0f}' for r in rows[:5]])
wr = [r for r in rows if r["pos"] == "WR"][:2]
print("PPR->half check:", [f'{r["player"]}: {r["full_ppr_projection"]:.0f} -> {r["projection"]:.0f} ({r["receptions"]} rec)' for r in wr])
