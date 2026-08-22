from __future__ import annotations

from kairo_ml.rl_envs.base import Action
from kairo_ml.rl_envs.code_repair import CodeRepairEnv

_CORRECT = (
    "def sum_to(n):\n"
    "    total = 0\n"
    "    for i in range(1, n + 1):\n"
    "        total += i\n"
    "    return total\n"
)


def test_hidden_tests_unreadable_before_scoring() -> None:
    with CodeRepairEnv() as env:
        env.reset("off_by_one_sum")
        # Agent can see the source file but not the hidden test.
        assert env.sandbox.exists("solution.py")
        assert not env.sandbox.exists(".hidden_scorer/test_solution.py")


def test_correct_fix_scores_full_reward() -> None:
    with CodeRepairEnv() as env:
        env.reset("off_by_one_sum")
        env.step(Action(kind="write_file", content=_CORRECT, args={"path": "solution.py"}))
        env.step(Action(kind="submit"))
        report = env.score()
        assert report.passed
        assert report.reward == 1.0
        assert report.details["tests_passed"] == report.details["tests_total"] > 0


def test_unfixed_code_fails() -> None:
    with CodeRepairEnv() as env:
        env.reset("off_by_one_sum")
        env.step(Action(kind="submit"))  # leave the bug in place
        report = env.score()
        assert not report.passed
        assert report.reward < 1.0


def test_hidden_tests_mounted_only_at_score_time() -> None:
    with CodeRepairEnv() as env:
        env.reset("off_by_one_sum")
        env.step(Action(kind="write_file", content=_CORRECT, args={"path": "solution.py"}))
        env.step(Action(kind="submit"))
        assert not env.sandbox.exists(".hidden_scorer/test_solution.py")
        env.score()
        # After scoring the tests are present (agent has already stopped).
        assert env.sandbox.exists(".hidden_scorer/test_solution.py")
