#!/usr/bin/env python
"""Roll a model role back to a prior known-good version.

Thin wrapper over ``kairo-eval rollback``. This flips the registry state; the
fast production rollback is a router traffic flip to a warm blue-green standby,
which this complements.

    python scripts/rollback_model.py --name model-32b --role reasoner \
        --to-version 2026-07-10-002
"""

from __future__ import annotations

import sys

from kairo_ml.evals.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["rollback", *sys.argv[1:]]))
