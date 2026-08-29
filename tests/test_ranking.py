from fantasy_draft_assistant.io import load_config, load_players
from fantasy_draft_assistant.ranking import recommend


def test_recommend_returns_available_players():
    players = load_players("data/players.csv")
    config = load_config("config.example.yaml")
    state = {"drafted": ["Christian McCaffrey"], "my_roster": []}
    recs = recommend(players, state, config, round_no=1, pick_no=2, limit=5)
    assert len(recs) == 5
    assert "Christian McCaffrey" not in set(recs["player"])
    assert recs.iloc[0]["score"] >= recs.iloc[-1]["score"]
