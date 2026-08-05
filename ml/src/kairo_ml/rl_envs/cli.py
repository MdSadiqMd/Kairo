"""RL environment CLI

    kairo-rlenv run --env math --task sum_halves --submit "1/2"
    kairo-rlenv run --env sql  --task active_users --submit "SELECT id FROM users ..."
    kairo-rlenv list                # list environments
    kairo-rlenv list --env math     # list an environment's tasks

`run` resets a task, applies a single `--submit` action (a submit-style
action carrying the answer/query), then prints the isolated `score()` report
as JSON. Exit code is 0 when the task passed, 1 otherwise
"""

from __future__ import annotations

import argparse
import json
import sys

from kairo_common import configure_logging, get_logger

from kairo_ml.rl_envs.base import Action
from kairo_ml.rl_envs.registry import available, make

log = get_logger("kairo-rlenv")


def _cmd_list(args: argparse.Namespace) -> int:
    if args.env:
        env = make(args.env)
        try:
            print(json.dumps({"env": args.env, "tasks": env.available_tasks()}, indent=2))
        finally:
            env.cleanup()
    else:
        print(json.dumps({"environments": available()}, indent=2))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    env = make(args.env, no_network=not args.allow_network)
    try:
        env.reset(args.task)
        if args.submit is not None:
            env.step(Action(kind="submit", content=args.submit))
        report = env.score()
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.passed else 1
    finally:
        env.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kairo-rlenv", description="Run RL environments offline.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="reset a task, submit an answer, print the score")
    p_run.add_argument("--env", required=True, choices=available())
    p_run.add_argument("--task", required=True)
    p_run.add_argument("--submit", default=None, help="answer/query for the submit action")
    p_run.add_argument("--allow-network", action="store_true", help="disable default-deny network")
    p_run.set_defaults(func=_cmd_run)

    p_list = sub.add_parser("list", help="list environments, or tasks for one env")
    p_list.add_argument("--env", default=None, choices=available())
    p_list.set_defaults(func=_cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging("kairo-rlenv")
    parser = build_parser()
    args = parser.parse_args(argv)
    func = args.func
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())
