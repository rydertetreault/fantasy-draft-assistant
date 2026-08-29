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


def cmd_build_board(args: argparse.Namespace) -> None:
    from .pipeline import build_board

    board_path = build_board(args.raw, args.team, args.out)
    console.print(f"Board written: [bold]{board_path}[/bold]")


def _load_board_rows(path: str):
    """Board rows from either board.csv or a raw ESPN players JSON."""
    from .pipeline import assign_tiers, load_board, parse_players

    if str(path).endswith(".json"):
        import dataclasses
        import json as _json
        from pathlib import Path as _Path

        raw = _json.loads(_Path(path).read_text(encoding="utf-8"))
        rows, _rejects = parse_players(raw)
        return [dataclasses.asdict(r) for r in assign_tiers(rows)]
    return load_board(path)


def cmd_replay(args: argparse.Namespace) -> int:
    from .replay import ReplayRunner, generate_script

    config = load_config(args.config or "config.synaps1.yaml")
    board_rows = _load_board_rows(args.board)
    if args.generate:
        rounds = 16 if args.generate == "full" else 3
        generate_script(board_rows, args.script, rounds=rounds)
        console.print(f"Generated {args.generate} DraftScript: [bold]{args.script}[/bold]")
    report = ReplayRunner(config, board_rows).run(args.script)

    console.print(f"[bold]Replay report[/bold] — {args.script}")
    table = Table(title=f"Our picks (team {report.our_team_id})")
    for col in ["Overall", "Player", "Status"]:
        table.add_column(col)
    for pick in report.our_picks:
        table.add_row(str(pick["overall"]), pick["player"], pick["status"])
    console.print(table)
    timings = [t["observe_to_recommend_ms"] for t in report.timings]
    avg = sum(timings) / len(timings) if timings else 0.0
    console.print(
        f"events={report.total_events} confirmed={len(report.our_picks)}/"
        f"{len(report.expected_our_overalls)} blocked={len(report.blocked)} "
        f"halts={len(report.halts)} corrupt_rejected={report.corrupt_rejected} "
        f"duplicate_noops={report.duplicate_noops}"
    )
    for entry in report.blocked:
        console.print(f"  blocked @ on_clock={entry['on_clock']}: {entry['reason']}")
    console.print(
        f"timing: max={report.max_latency_ms:.1f}ms avg={avg:.1f}ms "
        f"budget={3000}ms -> {'OK' if report.max_latency_ms < 3000 else 'OVER BUDGET'}"
    )
    verdict = "PASS" if report.ok else "FAIL"
    console.print(f"replay verdict: [bold]{verdict}[/bold]")
    return 0 if report.ok else 1


def cmd_dashboard(args: argparse.Namespace) -> int:
    from .dashboard import build_dashboard

    text = build_dashboard(
        team=args.team,
        data_dir=args.data,
        config_path=args.config or f"config.{args.team}.yaml",
        now_ms=args.now_ms,
    )
    print(text)
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from .preflight import run_preflight

    report = run_preflight(
        args.team,
        config_path=args.config or f"config.{args.team}.yaml",
        data_dir=args.data,
        grant_path=args.grant_file,
        max_age_hours=args.max_age_hours,
    )
    for check in report["checks"]:
        print(f"[{check['status'].upper():4s}] {check['name']}: {check['detail']}")
    print(f"report written: {report['report_path']}")
    print(f"preflight: {'PASS' if report['ok'] else 'FAIL'}")
    return 0 if report["ok"] else 1


def cmd_run(args: argparse.Namespace) -> int:
    from .runner import run_live

    return run_live(
        team=args.team,
        config_path=args.config or f"config.{args.team}.yaml",
        data_dir=args.data,
        mode=args.mode,
        grant_path=args.grant_file,
        poll_ms=args.poll_ms,
        snapshot_dir=args.snapshot_dir,
    )


def build_parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--players", default=None, help="Path to players CSV")
    shared.add_argument("--state", default=None, help="Path to draft_state.json")
    shared.add_argument("--config", default=None, help="Path to config YAML")

    parser = argparse.ArgumentParser(prog="fantasy-draft", parents=[shared])
    sub = parser.add_subparsers(required=True)

    rec = sub.add_parser("recommend", help="Show best available players", parents=[shared])
    rec.add_argument("--round", type=int, required=True)
    rec.add_argument("--pick", type=int, required=True, help="Pick number within the round")
    rec.add_argument("--limit", type=int, default=15)
    rec.set_defaults(func=cmd_recommend)

    draft = sub.add_parser("draft", help="Mark a player drafted", parents=[shared])
    draft.add_argument("player")
    draft.add_argument("--mine", action="store_true", help="Add to my roster")
    draft.set_defaults(func=cmd_draft)

    undo = sub.add_parser("undo", help="Remove a player from draft state", parents=[shared])
    undo.add_argument("player")
    undo.set_defaults(func=cmd_undo)

    roster = sub.add_parser("roster", help="Show my roster", parents=[shared])
    roster.set_defaults(func=cmd_roster)

    reset = sub.add_parser("reset", help="Clear draft state", parents=[shared])
    reset.set_defaults(func=cmd_reset)

    board = sub.add_parser(
        "build-board", help="Build data/<team>/board.csv from raw ESPN players JSON"
    )
    board.add_argument("--team", required=True, help="Team alias (e.g. synaps1)")
    board.add_argument(
        "--raw", default="data/raw/players.json", help="Path to raw players.json"
    )
    board.add_argument("--out", default="data", help="Output data directory")
    board.set_defaults(func=cmd_build_board)

    rep = sub.add_parser(
        "replay", help="Run an unattended DraftScript replay", parents=[shared]
    )
    rep.add_argument("script", help="Path to a DraftScript .jsonl file")
    rep.add_argument(
        "--board", default="data/synaps1/board.csv",
        help="board.csv or raw players JSON used for recommendations",
    )
    rep.add_argument(
        "--generate", choices=["full", "smoke"], default=None,
        help="Generate the script at SCRIPT before running (full=16 rounds, smoke=3)",
    )
    rep.set_defaults(func=cmd_replay)

    dash = sub.add_parser(
        "dashboard", help="Render the draft-day dashboard from files", parents=[shared]
    )
    dash.add_argument("--team", required=True, help="Team alias (e.g. synaps1)")
    dash.add_argument("--data", default="data", help="Data directory")
    dash.add_argument(
        "--now-ms", type=int, default=None, help="Override wall clock (tests/demos)"
    )
    dash.set_defaults(func=cmd_dashboard)

    pre = sub.add_parser(
        "preflight", help="Draft-day readiness checks + report", parents=[shared]
    )
    pre.add_argument("--team", required=True, help="Team alias (e.g. synaps1)")
    pre.add_argument("--data", default="data", help="Data directory")
    pre.add_argument("--grant-file", default=None, help="Ephemeral grant JSON to validate")
    pre.add_argument(
        "--max-age-hours", type=float, default=12.0,
        help="Staleness threshold for raw source and board.csv (default 12h)",
    )
    pre.set_defaults(func=cmd_preflight)

    run = sub.add_parser(
        "run",
        help="Long-running live loop: observe snapshots, advise, or autopick",
        parents=[shared],
    )
    run.add_argument("--team", required=True, help="Team alias (e.g. synaps1)")
    run.add_argument("--data", default="data", help="Data directory")
    run.add_argument(
        "--mode", required=True, choices=["observe", "advisory", "autopick"],
        help="observe=read-only, advisory=print recommendations, "
        "autopick=guarded submission (requires --grant-file)",
    )
    run.add_argument(
        "--grant-file", default=None,
        help="Ephemeral autopick grant JSON (required for --mode autopick)",
    )
    run.add_argument(
        "--poll-ms", type=int, default=2000, help="Snapshot poll interval (ms)"
    )
    run.add_argument(
        "--snapshot-dir", default=None,
        help="Directory the external poller writes to "
        "(default data/<team>/snapshots/)",
    )
    run.set_defaults(func=cmd_run)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if isinstance(result, int) and result != 0:
        raise SystemExit(result)


if __name__ == "__main__":
    main()
