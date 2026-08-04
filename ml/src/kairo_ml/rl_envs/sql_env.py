"""SQL RL environment

Validator: run the agent's query against a hidden in-memory `sqlite3` fixture
and compare its result set to the result of a hidden reference query. The agent
sees the schema DDL and the task prompt, never the seed data or the reference
query. Comparison is order-insensitive unless the reference query declares an
`ORDER BY` (then row order is significant). Reward is binary
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import ClassVar

from kairo_common import get_logger

from kairo_ml.rl_envs.base import (
    Action,
    Done,
    Info,
    Observation,
    Reward,
    RLEnvironment,
    ScoreReport,
)

log = get_logger("kairo-ml.rl_envs.sql")

Rows = list[tuple[object, ...]]


@dataclass(frozen=True)
class SqlTask:
    task_id: str
    prompt: str
    schema_ddl: str  # shown to the agent
    seed_sql: str  # hidden fixture data
    reference_query: str  # hidden expected query


_TASKS: dict[str, SqlTask] = {
    "top_customer": SqlTask(
        task_id="top_customer",
        prompt="Return the name of the customer with the highest total order amount.",
        schema_ddl=(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);\n"
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL);"
        ),
        seed_sql=(
            "INSERT INTO customers VALUES (1,'Ada'),(2,'Bo'),(3,'Cy');\n"
            "INSERT INTO orders VALUES (1,1,10.0),(2,1,5.0),(3,2,20.0),(4,3,4.0);"
        ),
        reference_query=(
            "SELECT c.name FROM customers c JOIN orders o ON o.customer_id = c.id "
            "GROUP BY c.id ORDER BY SUM(o.amount) DESC LIMIT 1;"
        ),
    ),
    "active_users": SqlTask(
        task_id="active_users",
        prompt="Return the ids of users whose status is 'active', sorted ascending.",
        schema_ddl="CREATE TABLE users (id INTEGER PRIMARY KEY, status TEXT);",
        seed_sql="INSERT INTO users VALUES (1,'active'),(2,'inactive'),(3,'active');",
        reference_query="SELECT id FROM users WHERE status = 'active' ORDER BY id;",
    ),
}


def _run_query(conn: sqlite3.Connection, query: str) -> Rows:
    cur = conn.execute(query)
    return [tuple(row) for row in cur.fetchall()]


def _build_fixture(task: SqlTask) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(task.schema_ddl)
    conn.executescript(task.seed_sql)
    return conn


def result_sets_match(expected: Rows, actual: Rows, *, ordered: bool) -> bool:
    if ordered:
        return expected == actual
    return sorted(expected, key=repr) == sorted(actual, key=repr)


class SqlEnv(RLEnvironment):
    name: ClassVar[str] = "sql"

    def __init__(self, *, no_network: bool = True) -> None:
        super().__init__(no_network=no_network)
        self._task: SqlTask | None = None
        self._submitted: str | None = None

    def available_tasks(self) -> list[str]:
        return sorted(_TASKS)

    def reset(self, task_id: str) -> Observation:
        if task_id not in _TASKS:
            raise KeyError(f"unknown sql task: {task_id!r}")
        self._task = _TASKS[task_id]
        self._task_id = task_id
        self._submitted = None
        obs = Observation(
            task_id=task_id,
            text=self._task.prompt,
            data={"schema_ddl": self._task.schema_ddl},
        )
        self._transcript.record_observation(obs.text, task_id=task_id)
        return obs

    def step(self, action: Action) -> tuple[Observation, Reward, Done, Info]:
        if self._task is None:
            raise RuntimeError("call reset() before step()")
        self._submitted = action.content.strip()
        self._transcript.record_action(self._submitted, verb=action.kind)
        passed, detail = self._evaluate(self._submitted)
        reward = Reward(value=1.0 if passed else 0.0, info=detail)
        obs = Observation(task_id=self._task.task_id, text="submitted")
        return obs, reward, True, detail

    def _evaluate(self, query: str) -> tuple[bool, dict[str, object]]:
        assert self._task is not None
        ordered = "order by" in self._task.reference_query.lower()
        conn = _build_fixture(self._task)
        try:
            expected = _run_query(conn, self._task.reference_query)
            try:
                actual = _run_query(conn, query)
            except sqlite3.Error as exc:
                return False, {"error": str(exc)}
            passed = result_sets_match(expected, actual, ordered=ordered)
            return passed, {"expected_rows": len(expected), "actual_rows": len(actual)}
        finally:
            conn.close()

    def score(self) -> ScoreReport:
        if self._task is None:
            raise RuntimeError("call reset() before score()")
        query = self._submitted or ""
        passed, detail = self._evaluate(query)
        report = ScoreReport(
            task_id=self._task.task_id,
            reward=1.0 if passed else 0.0,
            passed=passed,
            details={"submitted": query, **detail},
        )
        self._transcript.record_score(str(report.reward), passed=passed)
        return report
