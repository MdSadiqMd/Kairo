#![no_main]

use risc0_zkvm::guest::env;
use serde::{Deserialize, Serialize};

risc0_zkvm::guest::entry!(main);

const SCALE: i64 = 1_000_000;

#[derive(Serialize, Deserialize)]
struct GrpoWitness {
    group_id: String,
    rewards_fp: Vec<i64>,
}

#[derive(Serialize, Deserialize)]
struct GrpoOutput {
    group_id: String,
    advantages_fp: Vec<i64>,
    mean_fp: i64,
    std_fp: i64,
    spec_hash: String,
}

fn isqrt(n: i64) -> i64 {
    if n < 0 {
        return 0;
    }
    if n == 0 {
        return 0;
    }
    let mut x = n;
    let mut y = (x + 1) / 2;
    while y < x {
        x = y;
        y = (x + n / x) / 2;
    }
    x
}

fn group_normalize_fixed(rewards: &[i64]) -> (Vec<i64>, i64, i64) {
    let n = rewards.len() as i64;
    if n == 0 {
        return (vec![], 0, 0);
    }
    let sum: i64 = rewards.iter().sum();
    let mean = sum / n;

    let var_scaled: i64 = rewards.iter().map(|&r| {
        let diff = r - mean;
        diff * diff / SCALE
    }).sum::<i64>() / n;

    if var_scaled == 0 {
        return (vec![0; rewards.len()], mean, 0);
    }

    let std = isqrt(var_scaled * SCALE);
    if std == 0 {
        return (vec![0; rewards.len()], mean, 0);
    }

    let advantages: Vec<i64> = rewards.iter().map(|&r| {
        ((r - mean) * SCALE) / std
    }).collect();

    (advantages, mean, std)
}

fn main() {
    let witness: GrpoWitness = env::read();
    let spec_hash: String = env::read();

    let (advantages_fp, mean_fp, std_fp) = group_normalize_fixed(&witness.rewards_fp);

    let output = GrpoOutput {
        group_id: witness.group_id,
        advantages_fp,
        mean_fp,
        std_fp,
        spec_hash,
    };
    env::commit(&output);
}
