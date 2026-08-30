#!/usr/bin/env python3
"""Contextual chooser v2 (untracked rehearsal helper).

Inputs: --history <file: raw textContent of pick-history node>
        --visible <file: JSON list of visible available row texts>
        --exclude <comma names to treat as gone>  --overall N  (current overall)
        --teams N --slot N --league id --teamid id

Attribution: scan history text for board player names by index order —
format-agnostic. Candidates restricted to VISIBLE rows (never click ghosts).
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import pandas as pd
from fantasy_draft_assistant.context import TeamPick, contextual_recommend, snake_slot_for_overall
from fantasy_draft_assistant.io import load_config
from fantasy_draft_assistant.ranking import recommend

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("--history", required=True)
ap.add_argument("--visible", required=True)
ap.add_argument("--exclude", default="")
ap.add_argument("--roster", default="", help="comma-separated names of OUR verified picks (authoritative)")
ap.add_argument("--overall", type=int, required=True)
ap.add_argument("--slot", type=int, required=True)
ap.add_argument("--teams", type=int, default=12)
ap.add_argument("--league", type=int, required=True)
ap.add_argument("--teamid", type=int, required=True)
a = ap.parse_args()

b = pd.read_csv(os.environ.get("BOARD_CSV", os.path.join(ROOT, "data/synaps1/board.csv")))
players = pd.DataFrame({
    "player": b["player"], "team": b["nfl_team_id"], "pos": b["pos"].replace("D/ST", "DST"),
    "bye": 0, "projection": b["projection"], "adp": b["adp"], "tier": b["tier"],
})
name2id = {r["player"]: int(r["espn_player_id"]) for _, r in b.iterrows()}
name2pos = {r["player"]: str(r["pos"]).replace("D/ST", "DST") for _, r in b.iterrows()}

config = load_config(os.environ.get("CONFIG_YAML", os.path.join(ROOT, "config.mock.yaml")))
config["league"]["teams"] = a.teams

# ---- drafted set: EXACT count from the announcement, ADP-order identity ---
# The room tells us our exact overall -> exactly overall-1 players are gone.
# Identities are approximated by ADP order (bots and humans track it well
# enough for opponent-need modeling); our own verified picks are exact.
# Candidates are restricted to VISIBLE rows anyway, so identity noise cannot
# make us click a ghost or skip a real player.
visible_rows = [str(v).lower() for v in json.load(open(a.visible))]
def is_visible(name: str) -> bool:
    n = name.lower()
    return any(n in row for row in visible_rows)

roster_given = [x.strip() for x in a.roster.split(",") if x.strip()]
excludes = {x.strip() for x in a.exclude.split(",") if x.strip()}
current_overall = a.overall if a.overall > 0 else 1
n_drafted = max(0, current_overall - 1)
known_gone = list(dict.fromkeys(roster_given + sorted(excludes)))
adp_order = b.sort_values("adp")["player"].tolist()

# history text (ws frames / disappearance log): identity evidence only —
# it refines WHO is gone but can never change HOW MANY are gone (the
# announcement count is exact; additive history re-inflated it: r10 bug).
hist = open(a.history, encoding="utf8", errors="replace").read().lower()
hist_names = [n for n in name2id if n.lower() in hist and n not in known_gone and not is_visible(n)]
fill = [n for n in adp_order if n not in known_gone and n not in hist_names and not is_visible(n)]
drafted_names = (known_gone + hist_names + fill)[:max(n_drafted, len(known_gone))]

# attribution: drafted players in ADP order approximates draft order -> snake
by_adp = sorted((n for n in drafted_names if n in name2pos), key=lambda n: float(b.set_index("player")["adp"].get(n, 999)))
picks = [
    TeamPick(o + 1, snake_slot_for_overall(o + 1, a.teams), name, name2pos[name])
    for o, name in enumerate(by_adp)
]
my_roster = roster_given  # authoritative: our verified clicks only
round_no = (current_overall - 1) // a.teams + 1
pick_no = current_overall - (round_no - 1) * a.teams

state = {"drafted": drafted_names, "my_roster": my_roster}
base = recommend(players, state, config, round_no=round_no, pick_no=pick_no, limit=40)
ctx = contextual_recommend(
    players, base, picks, my_roster, a.slot, config, limit=15,
    current_overall=current_overall,
)

choice = None
for _, r in ctx.iterrows():
    nm = str(r["player"])
    if nm in excludes or not is_visible(nm):
        continue
    choice = r
    break

if choice is None:
    # slot-aware fallback: best visible player at the lineup slot they would
    # fill — NEVER raw board order (raw projection order = QBs, the r8
    # Mahomes / r11 Goff bug).
    from fantasy_draft_assistant.context import (
        position_cap, replacement_levels, slot_adjusted_vorp,
    )
    from fantasy_draft_assistant.ranking import roster_counts

    repl = replacement_levels(players, a.teams)
    counts = roster_counts(my_roster, players)
    best, best_val, best_slot = None, float("-inf"), ""
    for _, r in b.iterrows():
        nm = str(r["player"])
        if nm in excludes or nm in drafted_names or not is_visible(nm):
            continue
        pos = str(r["pos"]).replace("D/ST", "DST")
        if counts[pos] >= position_cap(pos, config):
            continue  # HARD cap: never a 3rd QB/TE, never a 2nd K/DST
        val, slot_label = slot_adjusted_vorp(
            pos, float(r["projection"]), my_roster, players, config, repl
        )
        if val > best_val:
            best, best_val, best_slot = r, val, slot_label
    if best is not None:
        print(json.dumps({"playerId": int(best["espn_player_id"]), "playerName": str(best["player"]),
                          "leagueId": a.league, "teamId": a.teamid, "pos": str(best["pos"]),
                          "why": {"fallback": f"slot-aware: {best_slot} value {best_val:.1f}"},
                          "alternatives": []}))
        sys.exit(0)
    print(json.dumps({"error": "no visible candidate"})); sys.exit(1)

print(json.dumps({
    "playerId": name2id.get(str(choice["player"]), 0),
    "playerName": str(choice["player"]),
    "leagueId": a.league, "teamId": a.teamid, "pos": str(choice["pos"]),
    "why": {
        "vorp": float(choice["vorp"]), "survival": float(choice["survival"]),
        "wait_loss": float(choice["wait_loss"]), "slot": str(choice["slot"]),
        "run_pressure": float(choice["run_pressure"]), "ctx_score": float(choice["ctx_score"]),
        "round": round_no, "picks_known": len(picks),
        "my_roster_pos": [name2pos.get(n, "?") for n in my_roster],
    },
    "alternatives": [
        {"player": str(r["player"]), "pos": str(r["pos"]), "ctx_score": float(r["ctx_score"])}
        for _, r in ctx.head(4).iterrows()
    ],
}))
