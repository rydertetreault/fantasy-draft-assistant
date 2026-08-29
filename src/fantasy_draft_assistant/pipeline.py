"""Reproducible data pipeline: raw ESPN kona_player_info -> validated board.

Checkpoint 2, Task 2 (docs/live-draft-operator.plan.md):

- Parse ``data/raw/players.json`` into validated board rows.
- Positions come from a CLOSED enum (QB/RB/WR/TE/DST/K). Anything else is
  visibly rejected — written to stderr and to a per-team rejects report —
  never silently coerced.
- Rows with a missing/malformed 2026 projection are rejected the same way.
- Tiers are derived per position from projection drop-off gaps.
- Output: ``data/<team>/board.csv`` plus ``board_meta.json`` carrying the
  source timestamp and reject counts. Columns are compatible with
  ``board.recommend`` (player/pos/projection/tier/adp keys).

Reading raw data and writing the board are the only side effects, and they
live in ``build_board``; all parsing/validation/tiering is pure.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO


class Position(str, Enum):
    """Closed position enum. Unknown ESPN position ids are rejected."""

    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    DST = "DST"
    K = "K"


#: ESPN defaultPositionId -> closed enum. Anything absent here is rejected.
ESPN_POSITION_IDS: Mapping[int, Position] = {
    1: Position.QB,
    2: Position.RB,
    3: Position.WR,
    4: Position.TE,
    5: Position.K,
    16: Position.DST,
}

#: Stat split identifying the full-season 2026 projection.
PROJECTION_KEY = (2026, 1, 0)  # (seasonId, statSourceId, statSplitTypeId)
LAST_SEASON_KEY = (2025, 0, 0)

BOARD_COLUMNS = [
    "player",
    "espn_player_id",
    "pos",
    "nfl_team_id",
    "projection",
    "last_season_points",
    "adp",
    "percent_owned",
    "injury_status",
    "tier",
]

#: Minimum projection gap (points) that opens a new tier at a position.
MIN_TIER_GAP = 8.0


@dataclass(frozen=True, slots=True)
class BoardRow:
    """One validated board row."""

    player: str
    espn_player_id: int
    pos: str
    nfl_team_id: int | None
    projection: float
    last_season_points: float | None
    adp: float | None
    percent_owned: float | None
    injury_status: str
    tier: int = 0


@dataclass(frozen=True, slots=True)
class Reject:
    """A visibly rejected raw entry (never silently coerced)."""

    espn_player_id: int | None
    player: str
    reason: str


def _stat_total(stats: Any, key: tuple[int, int, int]) -> float | None:
    if not isinstance(stats, list):
        return None
    for s in stats:
        if not isinstance(s, dict):
            continue
        if (s.get("seasonId"), s.get("statSourceId"), s.get("statSplitTypeId")) == key:
            total = s.get("appliedTotal")
            if isinstance(total, (int, float)) and not isinstance(total, bool):
                return float(total)
    return None


def _opt_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def parse_players(raw: Mapping[str, Any]) -> tuple[list[BoardRow], list[Reject]]:
    """Validate raw kona_player_info into board rows + explicit rejects."""
    entries = raw.get("players")
    if not isinstance(entries, list):
        raise ValueError("raw players payload has no 'players' list")
    rows: list[BoardRow] = []
    rejects: list[Reject] = []
    for entry in entries:
        player = entry.get("player") if isinstance(entry, dict) else None
        if not isinstance(player, dict):
            rejects.append(Reject(None, "<malformed>", "entry has no player object"))
            continue
        pid = player.get("id")
        name = player.get("fullName")
        if not isinstance(name, str) or not name.strip():
            rejects.append(Reject(_opt_int(pid), "<unnamed>", "missing fullName"))
            continue
        if _opt_int(pid) is None:
            rejects.append(Reject(None, name, "missing/invalid player id"))
            continue
        pos = ESPN_POSITION_IDS.get(player.get("defaultPositionId"))
        if pos is None:
            rejects.append(
                Reject(
                    _opt_int(pid),
                    name,
                    f"position id {player.get('defaultPositionId')!r} not in closed enum",
                )
            )
            continue
        projection = _stat_total(player.get("stats"), PROJECTION_KEY)
        if projection is None:
            rejects.append(Reject(_opt_int(pid), name, "missing 2026 projection"))
            continue
        ownership = player.get("ownership") or {}
        rows.append(
            BoardRow(
                player=name.strip(),
                espn_player_id=int(pid),
                pos=pos.value,
                nfl_team_id=_opt_int(player.get("proTeamId")),
                projection=projection,
                last_season_points=_stat_total(player.get("stats"), LAST_SEASON_KEY),
                adp=_opt_float(ownership.get("averageDraftPosition")),
                percent_owned=_opt_float(ownership.get("percentOwned")),
                injury_status=str(player.get("injuryStatus") or "UNKNOWN"),
            )
        )
    return rows, rejects


def _opt_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def assign_tiers(rows: Sequence[BoardRow], min_gap: float = MIN_TIER_GAP) -> list[BoardRow]:
    """Derive per-position tiers from projection drop-off gaps.

    Within each position (sorted by projection desc) a new tier opens
    whenever the gap to the previous player is at least ``min_gap`` points.
    Deterministic; ties broken by name for stability.
    """
    tiered: list[BoardRow] = []
    by_pos: dict[str, list[BoardRow]] = {}
    for row in rows:
        by_pos.setdefault(row.pos, []).append(row)
    for pos_rows in by_pos.values():
        pos_rows.sort(key=lambda r: (-r.projection, r.player))
        tier = 1
        prev: float | None = None
        for row in pos_rows:
            if prev is not None and (prev - row.projection) >= min_gap:
                tier += 1
            prev = row.projection
            tiered.append(BoardRow(**{**asdict(row), "tier": tier}))
    tiered.sort(key=lambda r: (-r.projection, r.player))
    return tiered


def build_board(
    raw_path: str | Path,
    team: str,
    out_dir: str | Path,
    *,
    stderr: TextIO | None = None,
) -> Path:
    """Build ``<out_dir>/<team>/board.csv`` from raw ESPN players JSON.

    Rejected rows are reported to stderr AND written to ``rejects.csv``;
    ``board_meta.json`` records the raw-source timestamp and counts.
    """
    err = stderr if stderr is not None else sys.stderr
    raw_path = Path(raw_path)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    rows, rejects = parse_players(raw)
    rows = assign_tiers(rows)

    team_dir = Path(out_dir) / team
    team_dir.mkdir(parents=True, exist_ok=True)
    board_path = team_dir / "board.csv"
    with board_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=BOARD_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    rejects_path = team_dir / "rejects.csv"
    with rejects_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["espn_player_id", "player", "reason"])
        for r in rejects:
            writer.writerow([r.espn_player_id, r.player, r.reason])
            print(f"REJECT: {r.player} ({r.espn_player_id}): {r.reason}", file=err)

    source_timestamp = datetime.fromtimestamp(
        raw_path.stat().st_mtime, tz=timezone.utc
    ).isoformat(timespec="seconds")
    meta = {
        "source": str(raw_path),
        "source_timestamp": source_timestamp,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(rows),
        "rejects": len(rejects),
    }
    (team_dir / "board_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return board_path


def load_board(board_path: str | Path) -> list[dict[str, Any]]:
    """Load board.csv as dict rows ready for ``board.recommend``."""
    with Path(board_path).open(newline="", encoding="utf-8") as fh:
        out: list[dict[str, Any]] = []
        for rec in csv.DictReader(fh):
            out.append(
                {
                    "player": rec["player"],
                    "espn_player_id": int(rec["espn_player_id"]),
                    "pos": rec["pos"],
                    "nfl_team_id": int(rec["nfl_team_id"]) if rec["nfl_team_id"] else None,
                    "projection": float(rec["projection"]),
                    "last_season_points": (
                        float(rec["last_season_points"]) if rec["last_season_points"] else None
                    ),
                    "adp": float(rec["adp"]) if rec["adp"] else None,
                    "percent_owned": (
                        float(rec["percent_owned"]) if rec["percent_owned"] else None
                    ),
                    "injury_status": rec["injury_status"],
                    "tier": int(rec["tier"]),
                }
            )
        return out
