"""Quantization: build FP8 / AWQ deployment artifacts

No training loop — this produces the servable artifact. plan() resolves the
quantization recipe and the CLI command with no torch (unit-tested); run()
lazily shells out to / imports the quantizer
"""

from __future__ import annotations

from typing import Any

from kairo_common import get_logger

from kairo_ml.training.config import QuantizationConfig

log = get_logger("quantizer")


class Quantizer:
    def __init__(self, config: QuantizationConfig) -> None:
        self.config = config

    def plan(self) -> dict[str, Any]:
        plan: dict[str, Any] = {
            "job": "quantize",
            "method": self.config.method,
            "base_model": self.config.base_model,
            "output_dir": self.config.output_dir,
        }
        # AWQ is calibration-based (needs sample activations); FP8 here is a
        # calibration-free per-tensor/dynamic scheme, so calibration args only
        # attach to AWQ
        if self.config.method == "awq":
            plan["requires_calibration"] = True
            plan["calibration_dataset_uri"] = self.config.calibration_dataset_uri
            plan["calibration_samples"] = self.config.calibration_samples
        else:
            plan["requires_calibration"] = False
        plan["command"] = self.build_command()
        return plan

    def build_command(self) -> list[str]:
        cmd = [
            "llm-compressor",
            "quantize",
            "--model",
            self.config.base_model,
            "--scheme",
            self.config.method.upper(),
            "--output",
            self.config.output_dir,
        ]
        if self.config.method == "awq":
            if self.config.calibration_dataset_uri:
                cmd += ["--calibration-dataset", self.config.calibration_dataset_uri]
            cmd += ["--num-calibration-samples", str(self.config.calibration_samples)]
        return cmd

    def run(self) -> str:
        import subprocess

        plan = self.plan()
        log.info("running quantization", extra={"method": self.config.method})
        subprocess.run(plan["command"], check=True)
        return self.config.output_dir
