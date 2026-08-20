use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use risc0_zkvm::{default_prover, ExecutorEnv, ProverOpts, VerifierContext};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

include!(concat!(env!("OUT_DIR"), "/methods.rs"));

#[derive(Parser)]
#[command(name = "kairo-r0-host")]
#[command(about = "RISC Zero proof host for Kairo RL proofs")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    Prove {
        #[arg(long)]
        kind: String,
        #[arg(long)]
        witness: PathBuf,
        #[arg(long)]
        spec_hash: String,
        #[arg(long)]
        out: PathBuf,
    },
    Verify {
        #[arg(long)]
        kind: String,
        #[arg(long)]
        receipt: PathBuf,
    },
    ImageId {
        #[arg(long)]
        kind: String,
    },
}

#[derive(Serialize, Deserialize)]
struct ProofOutput {
    image_id: String,
    journal: String,
    receipt_path: String,
}

fn get_guest_elf(kind: &str) -> Result<(&'static [u8], [u32; 8])> {
    match kind {
        "rl_reward_batch" => Ok((KAIRO_REWARD_GUEST_ELF, KAIRO_REWARD_GUEST_ID)),
        "rl_filter" => Ok((KAIRO_FILTER_GUEST_ELF, KAIRO_FILTER_GUEST_ID)),
        "rl_grpo" => Ok((KAIRO_GRPO_GUEST_ELF, KAIRO_GRPO_GUEST_ID)),
        "eval_gate" | "rl_cycle" => Ok((KAIRO_GATE_GUEST_ELF, KAIRO_GATE_GUEST_ID)),
        _ => bail!("unknown proof kind: {}", kind),
    }
}

fn prove(kind: &str, witness_path: &PathBuf, spec_hash: &str, out_path: &PathBuf) -> Result<()> {
    let witness_json = fs::read_to_string(witness_path)
        .with_context(|| format!("reading witness from {:?}", witness_path))?;
    let witness: serde_json::Value = serde_json::from_str(&witness_json)?;

    let (elf, image_id) = get_guest_elf(kind)?;

    let env = ExecutorEnv::builder()
        .write(&witness)?
        .write(&spec_hash.to_string())?
        .build()?;

    let prover = default_prover();
    let prove_info = prover.prove_with_opts(env, elf, &ProverOpts::groth16())?;
    let receipt = prove_info.receipt;

    receipt.verify(image_id)?;

    let receipt_bytes = bincode::serialize(&receipt)?;
    let receipt_path = out_path.with_extension("receipt");
    fs::write(&receipt_path, &receipt_bytes)?;

    let journal_hex = hex::encode(receipt.journal.bytes.as_slice());
    let output = ProofOutput {
        image_id: hex::encode(
            image_id
                .iter()
                .flat_map(|x| x.to_le_bytes())
                .collect::<Vec<_>>(),
        ),
        journal: journal_hex,
        receipt_path: receipt_path.to_string_lossy().to_string(),
    };

    let output_json = serde_json::to_string_pretty(&output)?;
    fs::write(out_path, &output_json)?;

    eprintln!("Proof generated: {:?}", out_path);
    Ok(())
}

fn verify(kind: &str, receipt_path: &PathBuf) -> Result<()> {
    let receipt_bytes = fs::read(receipt_path)?;
    let receipt: risc0_zkvm::Receipt = bincode::deserialize(&receipt_bytes)?;

    let (_, image_id) = get_guest_elf(kind)?;
    receipt.verify(image_id)?;

    eprintln!("Receipt verified successfully");
    println!("{}", hex::encode(receipt.journal.bytes.as_slice()));
    Ok(())
}

fn image_id(kind: &str) -> Result<()> {
    let (_, id) = get_guest_elf(kind)?;
    let id_hex = hex::encode(id.iter().flat_map(|x| x.to_le_bytes()).collect::<Vec<_>>());
    println!("{}", id_hex);
    Ok(())
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Prove {
            kind,
            witness,
            spec_hash,
            out,
        } => prove(&kind, &witness, &spec_hash, &out),
        Commands::Verify { kind, receipt } => verify(&kind, &receipt),
        Commands::ImageId { kind } => image_id(&kind),
    }
}
