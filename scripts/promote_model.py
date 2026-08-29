#!/usr/bin/env python
"""Promote a model version if its eval report passed the gate.

Thin wrapper over ``kairo-eval promote``. Refuses to promote on a failed or
mismatched report — the gate is not advisory.

    python scripts/promote_model.py --name model-32b --role reasoner \
        --model-version 2026-07-11-001 --report report.json
"""

from __future__ import annotations

import sys

from kairo_ml.evals.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["promote", *sys.argv[1:]]))
