#![no_main]

use risc0_zkvm::guest::env;
use serde::{Deserialize, Serialize};

risc0_zkvm::guest::entry!(main);

const SCALE: i64 = 1_000_000;
const R_ACCEPT: i64 = 750_000;
const R_REJECT: i64 = -250_000;
const R_NEUTRAL: i64 = 0;
const EDIT_PERSISTENCE_BONUS: i64 = 150_000;
const FOLLOWUP_DISSATISFACTION_PENALTY: i64 = -200_000;

#[derive(Serialize, Deserialize)]
struct RewardWitness {
    prompt_sha256: String,
    output_sha256: String,
    outcome: String,
    edit_persisted: bool,
    followup_dissatisfaction: bool,
    emitted_broken_tool_call: bool,
    deferred_via_clarifying_question: bool,
}

#[derive(Serialize, Deserialize)]
struct RewardOutput {
    prompt_sha256: String,
    output_sha256: String,
    reward_fp: i64,
    spec_hash: String,
}

fn compute_reward(w: &RewardWitness) -> i64 {
    let has_broken_tool_call = w.emitted_broken_tool_call;
    let has_clarifying_deflection = w.deferred_via_clarifying_question && w.outcome == "not_shown";

    let mut base = match w.outcome.as_str() {
        "accepted" => R_ACCEPT,
        "rejected" => R_REJECT,
        "shown_no_action" => R_NEUTRAL,
        "not_shown" => R_NEUTRAL,
        _ => R_NEUTRAL,
    };

    if has_broken_tool_call && base > 0 {
        base = R_REJECT;
    }

    let edit_bonus = if w.edit_persisted && base > 0 {
        EDIT_PERSISTENCE_BONUS
    } else {
        0
    };

    let followup_penalty = if w.followup_dissatisfaction {
        FOLLOWUP_DISSATISFACTION_PENALTY
    } else {
        0
    };

    base + edit_bonus + followup_penalty
}

fn main() {
    let witness: RewardWitness = env::read();
    let spec_hash: String = env::read();

    let reward_fp = compute_reward(&witness);

    let output = RewardOutput {
        prompt_sha256: witness.prompt_sha256,
        output_sha256: witness.output_sha256,
        reward_fp,
        spec_hash,
    };
    env::commit(&output);
}
