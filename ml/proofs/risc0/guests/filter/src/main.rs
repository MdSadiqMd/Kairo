#![no_main]

use risc0_zkvm::guest::env;
use serde::{Deserialize, Serialize};

risc0_zkvm::guest::entry!(main);

#[derive(Serialize, Deserialize)]
struct Rollout {
    id: String,
    policy_step: u64,
    hacking_flag: bool,
    commitment: String,
}

#[derive(Serialize, Deserialize)]
struct FilterWitness {
    rollouts: Vec<Rollout>,
    current_policy_step: u64,
    max_staleness: u64,
}

#[derive(Serialize, Deserialize)]
struct FilterOutput {
    kept_ids: Vec<String>,
    dropped_stale_ids: Vec<String>,
    dropped_hacking_ids: Vec<String>,
    kept_commitment: String,
    spec_hash: String,
}

fn filter_rollouts(
    rollouts: &[Rollout],
    current_policy_step: u64,
    max_staleness: u64,
) -> (Vec<String>, Vec<String>, Vec<String>) {
    let mut kept = Vec::new();
    let mut dropped_stale = Vec::new();
    let mut dropped_hacking = Vec::new();

    for r in rollouts {
        if r.hacking_flag {
            dropped_hacking.push(r.id.clone());
        } else if current_policy_step.saturating_sub(r.policy_step) > max_staleness {
            dropped_stale.push(r.id.clone());
        } else {
            kept.push(r.id.clone());
        }
    }
    (kept, dropped_stale, dropped_hacking)
}

fn commit_sequence(ids: &[String]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    for id in ids {
        hasher.update(id.as_bytes());
        hasher.update(b"\n");
    }
    hex::encode(hasher.finalize())
}

fn main() {
    let witness: FilterWitness = env::read();
    let spec_hash: String = env::read();

    let (kept, dropped_stale, dropped_hacking) =
        filter_rollouts(&witness.rollouts, witness.current_policy_step, witness.max_staleness);

    let kept_commitment = commit_sequence(&kept);

    let output = FilterOutput {
        kept_ids: kept,
        dropped_stale_ids: dropped_stale,
        dropped_hacking_ids: dropped_hacking,
        kept_commitment,
        spec_hash,
    };
    env::commit(&output);
}
