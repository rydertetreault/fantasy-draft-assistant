"""Behavioral scenarios: per-team draft state isolation (Checkpoint 1, Task 1).

Contract under test (per docs/live-draft-operator.plan.md Task 1 and the spec's
"Synaps1 and Synaps2 state files, strategies, and browser sessions cannot
contaminate one another"):

    from fantasy_draft_assistant.models import DraftState

    state = DraftState(team="synaps1")
    state.record_pick(overall=1, player="Justin Jefferson", position="WR")
    state.save(data_dir)                      # writes data_dir/<team>/... only
    loaded = DraftState.load(data_dir, "synaps1")

- Each team alias persists to its own state file under its own directory.
- Picks recorded for synaps1 never appear in synaps2's state.
- Loading/mutating one team's state cannot mutate another team's state.
"""

import copy

import pytest

from fantasy_draft_assistant.models import DraftState


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


def _pick_players(state):
    """Return the set of player names recorded in a state's picks."""
    return {p["player"] if isinstance(p, dict) else p.player for p in state.picks}


# ---------------------------------------------------------------------------
# Separate state files per team alias
# ---------------------------------------------------------------------------

class TestSeparateStateFiles:
    def test_each_team_saves_to_its_own_path(self, data_dir):
        s1 = DraftState(team="synaps1")
        s2 = DraftState(team="synaps2")
        p1 = s1.save(data_dir)
        p2 = s2.save(data_dir)
        assert p1 != p2, "both teams persisted to the same file"
        assert "synaps1" in str(p1)
        assert "synaps2" in str(p2)

    def test_state_files_live_under_team_scoped_directories(self, data_dir):
        # Spec project structure: `data/<team>/` — isolated draft state.
        p1 = DraftState(team="synaps1").save(data_dir)
        p2 = DraftState(team="synaps2").save(data_dir)
        assert "synaps2" not in str(p1)
        assert "synaps1" not in str(p2)

    def test_saving_one_team_does_not_touch_the_other_file(self, data_dir):
        s1 = DraftState(team="synaps1")
        s2 = DraftState(team="synaps2")
        s2_path = s2.save(data_dir)
        before = s2_path.read_bytes()

        s1.record_pick(overall=1, player="Justin Jefferson", position="WR")
        s1.save(data_dir)

        assert s2_path.read_bytes() == before, (
            "saving synaps1 state modified synaps2's state file"
        )


# ---------------------------------------------------------------------------
# Picks never leak across teams
# ---------------------------------------------------------------------------

class TestPickIsolation:
    def test_synaps1_picks_never_appear_in_synaps2_state(self, data_dir):
        s1 = DraftState(team="synaps1")
        s1.record_pick(overall=1, player="Justin Jefferson", position="WR")
        s1.record_pick(overall=18, player="Puka Nacua", position="WR")
        s1.save(data_dir)

        s2 = DraftState(team="synaps2")
        s2.record_pick(overall=5, player="Bijan Robinson", position="RB")
        s2.save(data_dir)

        loaded2 = DraftState.load(data_dir, "synaps2")
        assert _pick_players(loaded2) == {"Bijan Robinson"}
        assert "Justin Jefferson" not in _pick_players(loaded2)
        assert "Puka Nacua" not in _pick_players(loaded2)

        loaded1 = DraftState.load(data_dir, "synaps1")
        assert _pick_players(loaded1) == {"Justin Jefferson", "Puka Nacua"}
        assert "Bijan Robinson" not in _pick_players(loaded1)

    def test_fresh_team_state_starts_empty_even_after_other_team_drafted(self, data_dir):
        s1 = DraftState(team="synaps1")
        s1.record_pick(overall=1, player="Justin Jefferson", position="WR")
        s1.save(data_dir)

        s2 = DraftState(team="synaps2")
        assert len(s2.picks) == 0


# ---------------------------------------------------------------------------
# Loading one team's state cannot mutate another's
# ---------------------------------------------------------------------------

class TestNoCrossMutation:
    def test_mutating_loaded_state_does_not_bleed_into_other_team(self, data_dir):
        DraftState(team="synaps1").save(data_dir)
        s2 = DraftState(team="synaps2")
        s2.record_pick(overall=5, player="Bijan Robinson", position="RB")
        s2.save(data_dir)

        loaded1 = DraftState.load(data_dir, "synaps1")
        loaded1.record_pick(overall=2, player="Ja'Marr Chase", position="WR")
        loaded1.save(data_dir)

        reloaded2 = DraftState.load(data_dir, "synaps2")
        assert _pick_players(reloaded2) == {"Bijan Robinson"}

    def test_load_does_not_return_shared_mutable_objects(self, data_dir):
        s1 = DraftState(team="synaps1")
        s1.record_pick(overall=1, player="Justin Jefferson", position="WR")
        s1.save(data_dir)

        a = DraftState.load(data_dir, "synaps1")
        b = DraftState.load(data_dir, "synaps1")
        snapshot = copy.deepcopy(list(b.picks))

        a.record_pick(overall=2, player="Ja'Marr Chase", position="WR")

        assert list(b.picks) == snapshot, (
            "two loads of the same file share mutable pick storage"
        )

    def test_team_alias_is_stamped_on_loaded_state(self, data_dir):
        DraftState(team="synaps1").save(data_dir)
        loaded = DraftState.load(data_dir, "synaps1")
        assert loaded.team == "synaps1"
