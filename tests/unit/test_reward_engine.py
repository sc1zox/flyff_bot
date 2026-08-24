from flyff_bot.features.rl.rewards import RewardConfig, RewardEngine, RewardEvent


def test_reward_combines_positive_progress_and_negative_costs() -> None:
    engine = RewardEngine(RewardConfig(kill_weight=2.0, travel_weight=0.1))
    reward = engine.reward(
        RewardEvent(verified_kill=True, quest_progress_delta=1.0, travel_seconds=3.0)
    )
    assert reward == 2.2
