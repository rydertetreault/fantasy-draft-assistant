# Strategy: Maximize Championship Odds

## Core idea

We cannot guarantee a win. We can create an edge by combining current projections, market prices, positional replacement value, uncertainty, roster structure, and the probability that a target survives to the next turn. The board must react to the room rather than follow a fixed round-by-round script.

## Synaps1 structural implications

- Ten teams make QB and TE replacement options more available than in deep leagues.
- Full PPR raises target volume and pass-catching RB value.
- Only two required WR slots, versus three in many leagues, keeps strong RBs relatively valuable; FLEX still favors RB/WR.
- Seven bench spots reward high-upside RB/WR bets more than low-ceiling backup QB/TE selections.
- DST and kicker are replaceable and should normally be selected in the final two rounds.

## Decision score

Rank every available player using a distribution, not only one projection:

1. **Expected points above replacement** at the player's position.
2. **Starter value above the best likely FLEX alternative.**
3. **Tier cliff urgency:** the drop to the next realistic option at that position.
4. **Next-turn survival probability:** reach modestly when a tier-ending player is unlikely to return; wait when the market probably will.
5. **Roster fit:** open starter slots, FLEX strength, and bench composition.
6. **Upside:** ceiling and probability of a league-winning outcome.
7. **Risk:** injury, suspension, uncertain role, fragile depth chart, rookie ambiguity, age, and offensive environment.
8. **Market value:** ADP and current ESPN room behavior, used as price—not truth.
9. **Correlation:** quarterback/pass-catcher stacks are a tiebreaker, not a reason to accept a material value loss.
10. **Portfolio exposure:** between Synaps1 and Synaps2, diversify genuinely close decisions while taking obvious value on both teams.

The live output should show one primary candidate and at least two fallbacks, with a reason such as `last player in tier`, `+28 points over replacement`, or `unlikely to survive 17 picks`.

## Roster construction policy

### Early phase

- Draft elite difference-makers rather than forcing a position.
- Favor high-volume WRs and dual-threat/pass-catching RBs in full PPR.
- Take an elite TE or elite QB only where the projected weekly advantage is larger than the RB/WR opportunity cost.
- Do not leave the first four or five rounds with a structurally weak RB/WR core merely to complete every starting position.

### Middle phase

- Attack players whose role can grow: ascending receivers, ambiguous backfields, contingent-value RBs, and concentrated offenses.
- Fill QB/TE when a meaningful tier is ending; otherwise let replaceability work in our favor.
- Compare every selection to the FLEX player it displaces, not merely to the top player at its listed position.

### Late phase

- Bench spots are asymmetric bets. Prefer players who could become weekly starters over predictable low-ceiling veterans.
- Prioritize backup/committee RBs with clear paths to volume and receivers with target-growth paths.
- Usually avoid a second QB or TE unless the starter is risky, the league value is exceptional, or the bench player has genuine breakout/trade value.
- Select DST and K in the final two rounds, adjusted only if platform roster rules force an earlier selection.

## Slot-specific adaptation

The exact plan is created when the randomized slot appears one hour before the draft:

- **Early slot:** take an elite anchor; model the long gap between turns and be willing to close a tier before it vanishes.
- **Middle slot:** maximize flexibility and exploit room runs; survival estimates are less extreme.
- **Late slot:** plan pairs at the turn, but rank each pick independently and avoid forcing predetermined combinations.

For every upcoming turn, simulate likely intervening picks and label targets:

- `TAKE NOW` — expected value of waiting is negative.
- `CAN WAIT` — high probability the player survives.
- `PIVOT` — a room run or injury update changed the tier economics.

## Two-team portfolio

- Optimize each lineup independently first.
- When two candidates are within a small score band, split exposure across Synaps1 and Synaps2.
- Do not pass a clear tier or value advantage merely to diversify.
- Track shared exposure, injury concentration, and offense concentration after each team drafts.

## Anti-patterns

- Blindly following overall rankings or ADP.
- Drafting last season's points instead of the coming role distribution.
- Chasing a positional run after the valuable tier is already gone.
- Filling the starting lineup too early at the cost of RB/WR upside.
- Overvaluing stacks and bye-week balance.
- Drafting handcuffs solely because we roster the starter; standalone upside matters.
- Taking DST/K early or carrying low-upside bench veterans.
- Letting one stale projection source dominate the model.
