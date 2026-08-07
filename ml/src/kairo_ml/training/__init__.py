"""Training plane

Offline gated training jobs (SFT, preference, reward/verifier/critic,
distillation, quantization) plus the shared config, dataset, and MLflow-tracking
plumbing they build on. Heavy ML dependencies (torch, transformers, peft, trl,
mlflow) are imported lazily inside `train()`/`run()` methods only, so this
package imports and its plans build with none of them installed
"""
