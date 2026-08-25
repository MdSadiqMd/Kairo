# fsx_lustre

FSx for Lustre weight-staging filesystem (final_plan.md §9.4, §10.5).

Loading 30B–235B weights takes minutes when pulled per-pod from S3/HF on every
cold start. This module stages weights on a Lustre filesystem hydrated from the
model-artifacts S3 bucket, so pods read from a fast shared mount instead. **Do
not use EFS for weight loading** — its throughput is too low for multi-GB /
multi-hundred-GB checkpoints; that is why this module exists.

`enable_fsx` is `false` by default (dev) because Lustre is an always-on, priced
resource (§16). Enable it for staging/prod, or when cold-start latency on large
models justifies the cost.

Consumed by the `infra/kubernetes/fsx` overlay: the outputs
(`file_system_id`, `mount_name`, `dns_name`) populate a static PersistentVolume
backed by the FSx CSI driver, and a strategic-merge patch mounts the resulting
PVC into the vLLM pods at the Hugging Face cache path.
