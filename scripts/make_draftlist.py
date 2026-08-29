"""Generate a static pre-draft ranking (VORP order, DST/K tail) from a board.csv.

Usage: .venv/bin/python scripts/make_draftlist.py data/synaps1/board.csv /tmp/draftlist.json
"""
from __future__ import annotations

import csv
import json
import sys

REPL_IDX = {"QB": 11, "RB": 27, "WR": 27, "TE": 11, "DST": 9, "K": 9}
SKILL_CAP, TAIL_CAP = 230, 20


def main(board_path: str, out_path: str) -> None:
    rows = list(csv.DictReader(open(board_path)))
    for r in rows:
        r["projection"] = float(r["projection"])
    bypos: dict[str, list[dict]] = {}
    for r in rows:
        bypos.setdefault(r["pos"], []).append(r)
    for lst in bypos.values():
        lst.sort(key=lambda r: -r["projection"])
    repl = {
        pos: (lst[min(REPL_IDX.get(pos, 11), len(lst) - 1)]["projection"] if lst else 0.0)
        for pos, lst in bypos.items()
    }
    skill = sorted(
        (r for r in rows if r["pos"] not in ("DST", "K")),
        key=lambda r: -(r["projection"] - repl[r["pos"]]),
    )
    tail = sorted((r for r in rows if r["pos"] in ("DST", "K")), key=lambda r: -r["projection"])
    ranked = skill[:SKILL_CAP] + tail[:TAIL_CAP]
    ids = [int(r["espn_player_id"]) for r in ranked]
    json.dump(ids, open(out_path, "w"))
    print(f"wrote {len(ids)} ids to {out_path}; top3: {[r['player'] for r in ranked[:3]]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
