#![no_main]

use risc0_zkvm::guest::env;
use serde::{Deserialize, Serialize};

risc0_zkvm::guest::entry!(main);

const SCALE: i64 = 1_000_000;

#[derive(Serialize, Deserialize)]
struct GateSpec {
    min_sample_size: u32,
    pass_rate_floor_fp: i64,
    max_regression_prob_fp: i64,
    max_safety_regression_fp: i64,
    max_cost_increase_fp: i64,
    max_latency_p99_increase_fp: i64,
    bootstrap_iterations: u32,
    bootstrap_seed: u64,
}

#[derive(Serialize, Deserialize)]
struct EvalMetrics {
    sample_size: u32,
    pass_rate_fp: i64,
    safety_score_fp: i64,
    avg_cost_fp: i64,
    latency_p99_fp: i64,
    item_passed: Vec<bool>,
}

#[derive(Serialize, Deserialize)]
struct GateWitness {
    candidate: EvalMetrics,
    baseline: EvalMetrics,
    spec: GateSpec,
}

#[derive(Serialize, Deserialize)]
struct GateOutput {
    promotable: bool,
    reasons: Vec<String>,
    regression_prob_fp: i64,
    spec_hash: String,
}

struct Mt19937 {
    mt: [u32; 624],
    mti: usize,
}

impl Mt19937 {
    fn new(seed: u64) -> Self {
        let mut mt = [0u32; 624];
        mt[0] = seed as u32;
        for i in 1..624 {
            mt[i] = 1812433253u32
                .wrapping_mul(mt[i - 1] ^ (mt[i - 1] >> 30))
                .wrapping_add(i as u32);
        }
        Mt19937 { mt, mti: 624 }
    }

    fn generate_numbers(&mut self) {
        for i in 0..624 {
            let y = (self.mt[i] & 0x80000000) | (self.mt[(i + 1) % 624] & 0x7fffffff);
            self.mt[i] = self.mt[(i + 397) % 624] ^ (y >> 1);
            if y % 2 != 0 {
                self.mt[i] ^= 0x9908b0df;
            }
        }
        self.mti = 0;
    }

    fn next_u32(&mut self) -> u32 {
        if self.mti >= 624 {
            self.generate_numbers();
        }
        let mut y = self.mt[self.mti];
        self.mti += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c5680;
        y ^= (y << 15) & 0xefc60000;
        y ^= y >> 18;
        y
    }

    fn next_usize(&mut self, max: usize) -> usize {
        (self.next_u32() as usize) % max
    }
}

fn wilson_lower_bound(passed: u32, total: u32, z_fp: i64) -> i64 {
    if total == 0 {
        return 0;
    }
    let n = total as i64;
    let p_fp = (passed as i64 * SCALE) / n;
    let z2 = (z_fp * z_fp) / SCALE;

    let numerator = p_fp + z2 / (2 * n)
        - z_fp * isqrt((p_fp * (SCALE - p_fp) / n + z2 / (4 * n * n)) * SCALE) / SCALE;
    let denominator = SCALE + z2 / n;

    if denominator == 0 {
        return 0;
    }
    (numerator * SCALE) / denominator
}

fn isqrt(n: i64) -> i64 {
    if n <= 0 {
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

fn paired_bootstrap_regression_prob(
    candidate_passed: &[bool],
    baseline_passed: &[bool],
    iterations: u32,
    seed: u64,
) -> i64 {
    let n = candidate_passed.len();
    if n == 0 || n != baseline_passed.len() {
        return SCALE;
    }

    let mut rng = Mt19937::new(seed);
    let mut regressions = 0u32;

    for _ in 0..iterations {
        let mut cand_sum = 0i64;
        let mut base_sum = 0i64;
        for _ in 0..n {
            let idx = rng.next_usize(n);
            cand_sum += if candidate_passed[idx] { 1 } else { 0 };
            base_sum += if baseline_passed[idx] { 1 } else { 0 };
        }
        if cand_sum < base_sum {
            regressions += 1;
        }
    }

    (regressions as i64 * SCALE) / (iterations as i64)
}

fn evaluate_gate(witness: &GateWitness) -> (bool, Vec<String>, i64) {
    let mut reasons = Vec::new();
    let spec = &witness.spec;
    let cand = &witness.candidate;
    let base = &witness.baseline;

    if cand.sample_size < spec.min_sample_size {
        reasons.push(format!("sample_size {} < {}", cand.sample_size, spec.min_sample_size));
    }

    let z_fp = 1_960_000;
    let lower = wilson_lower_bound(
        cand.item_passed.iter().filter(|&&p| p).count() as u32,
        cand.sample_size,
        z_fp,
    );
    if lower < spec.pass_rate_floor_fp {
        reasons.push(format!("pass_rate_lower_bound {} < floor {}", lower, spec.pass_rate_floor_fp));
    }

    let regression_prob = paired_bootstrap_regression_prob(
        &cand.item_passed,
        &base.item_passed,
        spec.bootstrap_iterations,
        spec.bootstrap_seed,
    );
    if regression_prob > spec.max_regression_prob_fp {
        reasons.push(format!("regression_prob {} > max {}", regression_prob, spec.max_regression_prob_fp));
    }

    let safety_drop = base.safety_score_fp - cand.safety_score_fp;
    if safety_drop > spec.max_safety_regression_fp {
        reasons.push(format!("safety_regression {} > max {}", safety_drop, spec.max_safety_regression_fp));
    }

    let cost_increase = cand.avg_cost_fp - base.avg_cost_fp;
    if cost_increase > spec.max_cost_increase_fp {
        reasons.push(format!("cost_increase {} > max {}", cost_increase, spec.max_cost_increase_fp));
    }

    let latency_increase = cand.latency_p99_fp - base.latency_p99_fp;
    if latency_increase > spec.max_latency_p99_increase_fp {
        reasons.push(format!("latency_increase {} > max {}", latency_increase, spec.max_latency_p99_increase_fp));
    }

    let promotable = reasons.is_empty();
    (promotable, reasons, regression_prob)
}

fn main() {
    let witness: GateWitness = env::read();
    let spec_hash: String = env::read();

    let (promotable, reasons, regression_prob_fp) = evaluate_gate(&witness);

    let output = GateOutput {
        promotable,
        reasons,
        regression_prob_fp,
        spec_hash,
    };
    env::commit(&output);
}
