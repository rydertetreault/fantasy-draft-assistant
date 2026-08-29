from __future__ import annotations

import argparse
from difflib import get_close_matches

from rich.console import Console
from rich.table import Table

from .io import load_config, load_players, load_state, save_state
from .ranking import recommend as make_recommendations

console = Console()


def find_player_name(query: str, names: list[str]) -> str:
    lower = {n.lower(): n for n in names}
    if query.lower() in lower:
        return lower[query.lower()]
    matches = get_close_matches(query, names, n=1, cutoff=0.6)
    if not matches:
        raise SystemExit(f"No player found matching: {query}")
    return matches[0]


def cmd_recommend(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    players = load_players(args.players)
    state = load_state(args.state)
    recs = make_recommendations(players, state, config, args.round, args.pick, args.limit)

    table = Table(title=f"Best available — round {args.round}, pick {args.pick}")
    for col in ["Rank", "Player", "Team", "Pos", "Bye", "Proj", "ADP", "Tier", "Value", "Score"]:
        table.add_column(col)
    for idx, row in enumerate(recs.itertuples(index=False), start=1):
        table.add_row(
            str(idx),
            row.player,
            row.team,
            row.pos,
            str(row.bye),
            f"{row.projection:.1f}",
            f"{row.adp:.1f}",
            str(row.tier),
            f"{row.value_vs_pick:.1f}",
            f"{row.score:.1f}",
        )
    console.print(table)


def cmd_draft(args: argparse.Namespace) -> None:
    players = load_players(args.players)
    state = load_state(args.state)
    name = find_player_name(args.player, players["player"].tolist())
    if name not in state["drafted"]:
        state["drafted"].append(name)
    if args.mine and name not in state["my_roster"]:
        state["my_roster"].append(name)
    save_state(state, args.state)
    console.print(f"Drafted: [bold]{name}[/bold]" + (" to your roster" if args.mine else ""))


def cmd_undo(args: argparse.Namespace) -> None:
    players = load_players(args.players)
    state = load_state(args.state)
    name = find_player_name(args.player, players["player"].tolist())
    state["drafted"] = [p for p in state.get("drafted", []) if p != name]
    state["my_roster"] = [p for p in state.get("my_roster", []) if p != name]
    save_state(state, args.state)
    console.print(f"Removed: [bold]{name}[/bold]")


def cmd_roster(args: argparse.Namespace) -> None:
    players = load_players(args.players)
    state = load_state(args.state)
    mine = players[players["player"].isin(state.get("my_roster", []))].sort_values(["pos", "projection"], ascending=[True, False])
    table = Table(title="My roster")
    for col in ["Player", "Team", "Pos", "Bye", "Proj"]:
        table.add_column(col)
    for row in mine.itertuples(index=False):
        table.add_row(row.player, row.team, row.pos, str(row.bye), f"{row.projection:.1f}")
    console.print(table)


def cmd_reset(args: argparse.Namespace) -> None:
    save_state({"drafted": [], "my_roster": []}, args.state)
    console.print("Draft state reset")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fantasy-draft")
    parser.add_argument("--players", default=None, help="Path to players CSV")
    parser.add_argument("--state", default=None, help="Path to draft_state.json")
    parser.add_argument("--config", default=None, help="Path to config YAML")
    sub = parser.add_subparsers(required=True)

    rec = sub.add_parser("recommend", help="Show best available players")
    rec.add_argument("--round", type=int, required=True)
    rec.add_argument("--pick", type=int, required=True, help="Pick number within the round")
    rec.add_argument("--limit", type=int, default=15)
    rec.set_defaults(func=cmd_recommend)

    draft = sub.add_parser("draft", help="Mark a player drafted")
    draft.add_argument("player")
    draft.add_argument("--mine", action="store_true", help="Add to my roster")
    draft.set_defaults(func=cmd_draft)

    undo = sub.add_parser("undo", help="Remove a player from draft state")
    undo.add_argument("player")
    undo.set_defaults(func=cmd_undo)

    roster = sub.add_parser("roster", help="Show my roster")
    roster.set_defaults(func=cmd_roster)

    reset = sub.add_parser("reset", help="Clear draft state")
    reset.set_defaults(func=cmd_reset)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
