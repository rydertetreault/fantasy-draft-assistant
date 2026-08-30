#!/usr/bin/env python3
"""Contextual chooser v2 (untracked rehearsal helper).

Inputs: --history <file: raw textContent of pick-history node>
        --visible <file: JSON list of visible available row texts>
        --exclude <comma names to treat as gone>  --overall N  (current overall)
        --teams N --slot N --league id --teamid id

Attribution: scan history text for board player names by index order —
format-agnostic. Candidates restricted to VISIBLE rows (never click ghosts).
"""
import argparse, json, os, re, sys

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
ap.add_argument("--roster-file", default="", help="file with the room's own roster-panel text (abbrev names) — ground truth incl. autopicks")
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

# ESPN proTeamId -> yahoo team token / city / nickname (lowercase)
TEAM_INFO = {
    1: ("atl", "atlanta", "falcons"), 2: ("buf", "buffalo", "bills"), 3: ("chi", "chicago", "bears"),
    4: ("cin", "cincinnati", "bengals"), 5: ("cle", "cleveland", "browns"), 6: ("dal", "dallas", "cowboys"),
    7: ("den", "denver", "broncos"), 8: ("det", "detroit", "lions"), 9: ("gb", "green bay", "packers"),
    10: ("ten", "tennessee", "titans"), 11: ("ind", "indianapolis", "colts"), 12: ("kc", "kansas city", "chiefs"),
    13: ("lv", "las vegas", "raiders"), 14: ("lar", "los angeles", "rams"), 15: ("mia", "miami", "dolphins"),
    16: ("min", "minnesota", "vikings"), 17: ("ne", "new england", "patriots"), 18: ("no", "new orleans", "saints"),
    19: ("nyg", "new york", "giants"), 20: ("nyj", "new york", "jets"), 21: ("phi", "philadelphia", "eagles"),
    22: ("ari", "arizona", "cardinals"), 23: ("pit", "pittsburgh", "steelers"), 24: ("lac", "los angeles", "chargers"),
    25: ("sf", "san francisco", "49ers"), 26: ("sea", "seattle", "seahawks"), 27: ("tb", "tampa bay", "buccaneers"),
    28: ("was", "washington", "commanders"), 29: ("car", "carolina", "panthers"), 30: ("jax", "jacksonville", "jaguars"),
    33: ("bal", "baltimore", "ravens"), 34: ("hou", "houston", "texans"),
}
name2adp = {r["player"]: float(r["adp"]) for _, r in b.iterrows()}
name2team = {r["player"]: TEAM_INFO.get(int(r["nfl_team_id"]), ("", "", ""))[0] for _, r in b.iterrows()}
name2city = {r["player"]: TEAM_INFO.get(int(r["nfl_team_id"]), ("", "", ""))[1] for _, r in b.iterrows()}
name2nick = {r["player"]: TEAM_INFO.get(int(r["nfl_team_id"]), ("", "", ""))[2] for _, r in b.iterrows()}


config = load_config(os.environ.get("CONFIG_YAML", os.path.join(ROOT, "config.mock.yaml")))
config["league"]["teams"] = a.teams

# ---- drafted set: EXACT count from the announcement, ADP-order identity ---
# The room tells us our exact overall -> exactly overall-1 players are gone.
# Identities are approximated by ADP order (bots and humans track it well
# enough for opponent-need modeling); our own verified picks are exact.
# Candidates are restricted to VISIBLE rows anyway, so identity noise cannot
# make us click a ghost or skip a real player.
visible_rows = [str(v).lower() for v in json.load(open(a.visible))]
def _forms(name: str) -> set:
    n = name.lower()
    parts = n.replace(" jr.", "").replace(" sr.", "").replace(" iii", "").replace(" ii", "").split()
    forms = {n}
    if len(parts) >= 2:
        forms.add(f"{parts[0][0]}. {' '.join(parts[1:])}")
        forms.add(f"{parts[0][0]}.{' '.join(parts[1:])}")
    return forms

def is_visible(name: str, pos: str = "") -> bool:
    """Row must contain the NAME + POSITION + TEAM token. Same-position
    abbreviation collisions (B. Robinson RB Atl vs B. Robinson RB Was) make
    name+pos insufficient; the team token settles it. DSTs match by
    city/nickname + 'def' (board 'Lions D/ST' <-> Yahoo 'Detroit DEF')."""
    p = (pos or name2pos.get(name, "")).lower().replace("dst", "def")
    tm = name2team.get(name, "")
    if p == "def":
        city, nick = name2city.get(name, ""), name2nick.get(name, "")
        for row in visible_rows:
            if " def" in f" {row} " and (city and city in row or nick and nick in row or (tm and f" {tm} " in f" {row} ")):
                return True
        return False
    for row in visible_rows:
        r = f" {row} "
        for f in _forms(name):
            if f in row and (not p or f" {p} " in r) and (not tm or f" {tm} " in r):
                return True
    return False

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
my_roster = list(roster_given)  # our verified clicks
if a.roster_file:
    try:
        rtxt = open(a.roster_file, encoding="utf8", errors="replace").read().lower()
        for nm in name2id:
            if nm in my_roster:
                continue
            parts = nm.replace(" Jr.", "").replace(" Sr.", "").replace(" III", "").replace(" II", "").split()
            if len(parts) >= 2:
                ab = f"{parts[0][0].lower()}. {' '.join(parts[1:]).lower()}"
                pos = name2pos.get(nm, "").lower().replace("dst", "def")
                # pos-adjacent (tolerating injury tags: "J. Love Q RB Ari")
                pat = re.escape(ab) + r"\s+(?:[qdoir]+\s+)?" + re.escape(pos) + r"\b"
                if re.search(pat, rtxt) or f"{pos} {ab}" in rtxt:
                    my_roster.append(nm)
    except Exception:
        pass
for nm in my_roster:
    if nm not in drafted_names:
        drafted_names.append(nm)
round_no = (current_overall - 1) // a.teams + 1
pick_no = current_overall - (round_no - 1) * a.teams

state = {"drafted": drafted_names, "my_roster": my_roster}
base = recommend(players, state, config, round_no=round_no, pick_no=pick_no, limit=100)
ctx = contextual_recommend(
    players, base, picks, my_roster, a.slot, config, limit=30,
    current_overall=current_overall,
)
# HARD round floors (profile-gated): the shared formula's wait_until_round
# is only a -30 base-funnel penalty — the ctx re-sort ignores it (r2 Josh
# Allen, mock #4). Profiles with hard_wait_floors drop floored positions
# HERE so neither the choice nor the filter-click "wanted" can chase them
# early. Never filters to an empty board (safety).
hard_floors = (config["strategy"].get("wait_until_round", {}) or {}) if config["strategy"].get("hard_wait_floors") else {}
ghost_skill_only = bool(config["strategy"].get("adp_ghost_skill_only"))
if hard_floors:
    _mask = ctx["pos"].map(lambda p: round_no >= int(hard_floors.get(str(p).replace("D/ST", "DST"), 0) or 0))
    if _mask.any():
        ctx = ctx[_mask]

choice = None
top_any = None
for _, r in ctx.iterrows():
    nm = str(r["player"])
    if nm in excludes:
        continue
    # ADP sanity: an elite player 30+ picks past ADP is a ghost row collision
    # (Bijan vs Brian Robinson, same team/pos/abbrev), never a real faller.
    # K/DST are exempt (profile-gated): they ALWAYS fall past ESPN ADP
    # (Aubrey adp 86.6 vs r14/15 reality) and can't abbrev-collide — the
    # name+pos+team visibility lock already settles their clicks.
    if (
        name2adp.get(nm, 999) + 30 < current_overall
        and not (ghost_skill_only and str(r["pos"]).replace("D/ST", "DST") in ("K", "DST"))
    ):
        continue
    if top_any is None:
        top_any = r
    if not is_visible(nm):
        continue
    choice = r
    break
wanted = None
if top_any is not None and (choice is None or float(top_any["ctx_score"]) > float(choice["ctx_score"]) + 5.0):
    wanted = {"pos": str(top_any["pos"]), "player": str(top_any["player"]), "gain": round(float(top_any["ctx_score"]) - (float(choice["ctx_score"]) if choice is not None else 0.0), 2)}

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
    # pass 1 respects hard floors; pass 2 (only if pass 1 found nobody)
    # ignores them — an on-clock emergency pick beats an autopick.
    for allow_floored in (False, True):
        for _, r in b.iterrows():
            nm = str(r["player"])
            if nm in excludes or nm in drafted_names or not is_visible(nm):
                continue
            pos = str(r["pos"]).replace("D/ST", "DST")
            if name2adp.get(nm, 999) + 30 < current_overall and not (
                ghost_skill_only and pos in ("K", "DST")
            ):
                continue
            if counts[pos] >= position_cap(pos, config):
                continue  # HARD cap: never a 3rd QB/TE, never a 2nd K/DST
            if not allow_floored and hard_floors and round_no < int(hard_floors.get(pos, 0) or 0):
                continue
            val, slot_label = slot_adjusted_vorp(
                pos, float(r["projection"]), my_roster, players, config, repl
            )
            if val > best_val:
                best, best_val, best_slot = r, val, slot_label
        if best is not None:
            break
    if best is not None:
        print(json.dumps({"playerId": int(best["espn_player_id"]), "playerName": str(best["player"]),
                          "leagueId": a.league, "teamId": a.teamid, "pos": str(best["pos"]),
                          "why": {"fallback": f"slot-aware: {best_slot} value {best_val:.1f}"},
                          "alternatives": []}))
        sys.exit(0)
    print(json.dumps({"error": "no visible candidate"})); sys.exit(1)

out_extra = {"wanted": wanted} if wanted else {}
out_extra["teamTok"] = name2team.get(str(choice["player"]), "")
out_extra["cityTok"] = name2city.get(str(choice["player"]), "")
out_extra["nickTok"] = name2nick.get(str(choice["player"]), "")
print(json.dumps({
    **out_extra,
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
