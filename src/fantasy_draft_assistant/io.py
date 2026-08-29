from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

DEFAULT_STATE = {"drafted": [], "my_roster": []}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else repo_root() / "config.yaml"
    if not cfg_path.exists():
        cfg_path = repo_root() / "config.example.yaml"
    return yaml.safe_load(cfg_path.read_text())


def load_players(path: str | Path | None = None) -> pd.DataFrame:
    players_path = Path(path) if path else repo_root() / "data" / "players.csv"
    df = pd.read_csv(players_path)
    required = {"player", "team", "pos", "bye", "projection", "adp", "tier"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"players CSV missing columns: {sorted(missing)}")
    # Normalize accidental column swaps in manually-edited CSVs.
    df["pos"] = df["pos"].astype(str).str.upper()
    return df


def state_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else repo_root() / "data" / "draft_state.json"


def load_state(path: str | Path | None = None) -> dict[str, Any]:
    p = state_path(path)
    if not p.exists():
        save_state(DEFAULT_STATE.copy(), p)
    return json.loads(p.read_text())


def save_state(state: dict[str, Any], path: str | Path | None = None) -> None:
    p = state_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
