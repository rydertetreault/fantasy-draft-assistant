#!/usr/bin/env python3
"""Offline schedule solver for The Tetreau Invitational (league 1851947).
Keeps weeks 1-9 (ESPN round-robin) and week 14 (owner's rivalry week) fixed.
Rebuilds weeks 10-13 so weeks 10-14 form a full intra-division round-robin,
with the per-week odd-out team from each division playing cross-division.
Pure offline analysis; writes nothing to ESPN."""
import json, itertools
from collections import defaultdict, Counter
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data/leagues/1851947/raw"
s = json.load(open(RAW / "settings_teams.json"))
sc = json.load(open(RAW / "schedule.json"))
names = {t["id"]: t["name"].strip() for t in s["teams"]}
div = {t["id"]: t["divisionId"] for t in s["teams"]}
DIVNAME = {0: "FL/GA", 1: "AL"}
REG_WEEKS = 14
FIXED_WEEKS = set(range(1, 10)) | {14}

weeks = defaultdict(list)
for m in sc["schedule"]:
    if m.get("playoffTierType", "NONE") != "NONE" or m["matchupPeriodId"] > REG_WEEKS:
        continue
    weeks[m["matchupPeriodId"]].append((m["home"]["teamId"], m["away"]["teamId"]))
original = {w: list(ms) for w, ms in weeks.items()}

def near_factorizations(teams, fixed_round):
    """All ways to split K5 edges into 5 near-perfect matchings, one of which is fixed_round."""
    edges = {frozenset(e) for e in itertools.combinations(teams, 2)}
    fixed = {frozenset(e) for e in fixed_round}
    remaining = edges - fixed
    # a round = 2 disjoint edges
    rounds = [frozenset({a, b}) for a, b in itertools.combinations(remaining, 2) if not (a & b)]
    out = []
    for combo in itertools.combinations(rounds, 4):
        used = set().union(*combo)
        if len(used) == 8 and used == remaining:
            out.append([tuple(tuple(e) for e in r) for r in combo])
    return out

def bye_of(teams, rnd):
    return (set(teams) - {t for e in rnd for t in e}).pop()

divteams = {d: [t for t in names if div[t] == d] for d in DIVNAME}
w14 = original[14]
fixed_round = {d: [e for e in w14 if div[e[0]] == d and div[e[1]] == d] for d in DIVNAME}
facts = {d: near_factorizations(divteams[d], fixed_round[d]) for d in DIVNAME}

def score(sched):
    """Lower is better. Hard: no pair >2, all pairs >=1. Soft: spread repeats apart."""
    opp = defaultdict(dict)
    for w, ms in sched.items():
        for h, a in ms:
            opp[h][w] = a; opp[a][w] = h
    cnt = Counter()
    for w, ms in sched.items():
        for h, a in ms:
            cnt[frozenset((h, a))] += 1
    if max(cnt.values()) > 2 or len(cnt) < 45:
        return None
    pen = 0
    for t in names:
        for w in range(1, REG_WEEKS):
            for gap in (1, 2, 3):
                if opp[t].get(w) is not None and opp[t].get(w) == opp[t].get(w + gap):
                    pen += {1: 100, 2: 10, 3: 3}[gap]
    return pen

best = None
for fa in facts[0]:
    for fb in facts[1]:
        for pa in itertools.permutations(fa):
            for pb in itertools.permutations(fb):
                sched = {w: list(ms) for w, ms in original.items() if w in FIXED_WEEKS}
                for i, w in enumerate(range(10, 14)):
                    ra, rb = pa[i], pb[i]
                    sched[w] = [tuple(e) for e in ra] + [tuple(e) for e in rb] + \
                               [(bye_of(divteams[0], ra), bye_of(divteams[1], rb))]
                sc_ = score(sched)
                if sc_ is not None and (best is None or sc_ < best[0]):
                    best = (sc_, sched)

pen, sched = best
short = {1: "Rough Rydahs", 2: "Team Pablo", 3: "The Big Penix", 4: "All i do is WIN", 6: "CeeDeez Purdy TD's",
         5: "Danny's Disciples", 7: "Njigbas In Paris", 8: "Ray Rice Boxing Academy", 10: "BHM Stallion", 11: "FOLLOWtheLIGHT"}
print(f"Best penalty: {pen}\n")
print("=== PROPOSED SCHEDULE (weeks 10-13 changed; * = cross-division) ===")
for w in range(1, REG_WEEKS + 1):
    tag = "" if w in FIXED_WEEKS else "  <-- CHANGE"
    print(f"Week {w:>2}{tag}")
    for h, a in sched[w]:
        star = "*" if div[h] != div[a] else " "
        print(f"   {star} {short[h]:<24} vs  {short[a]}")

cnt = defaultdict(Counter)
for w, ms in sched.items():
    for h, a in ms:
        cnt[h][a] += 1; cnt[a][h] += 1
ids = sorted(names, key=lambda i: (div[i], i))
ab = {1: "RR", 2: "PAB", 3: "BP", 4: "WIN", 6: "CD", 5: "DAN", 7: "NJ", 8: "RRB", 10: "BHM", 11: "FTL"}
print("\n=== OPPONENT COUNTS ===")
print(" " * 26 + "".join(f"{ab[j]:>5}" for j in ids))
for i in ids:
    row = "".join(f"{(cnt[i][j] if i != j else '-'):>5}" for j in ids)
    print(f"{short[i]:<20} {DIVNAME[div[i]]:<5}{row}   div games={sum(cnt[i][j] for j in ids if div[j]==div[i] and j!=i)}")

json.dump({str(w): sched[w] for w in sched}, open(RAW.parent / "proposed_schedule.json", "w"), indent=1)
