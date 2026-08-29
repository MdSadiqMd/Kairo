#!/usr/bin/env python
"""Run a private eval suite against a served model.

Thin wrapper over ``kairo-eval run``. Exits non-zero if the promotion gate fails,
so CI (`eval-candidate.yml`) and the eval-runner Job can gate on it directly.

    python scripts/run_eval_suite.py --suite smoke_v1 \
        --model model-30b-a3b-dev --model-version 2026-07-11-001 \
        --router-url https://<alb>/ --out report.json
"""

from __future__ import annotations

import sys

from kairo_ml.evals.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["run", *sys.argv[1:]]))
