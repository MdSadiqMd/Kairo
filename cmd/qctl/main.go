// Command qctl is the Kairo lifecycle orchestrator.
// It orchestrates; Terraform owns. Subcommands: preflight, up, down, verify,
// sweep. Only the stdlib flag package is used — no external CLI framework.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/MdSadiqMd/Kairo/internal/command"
	"github.com/MdSadiqMd/Kairo/internal/config"
	"github.com/MdSadiqMd/Kairo/internal/logx"
	"github.com/MdSadiqMd/Kairo/internal/modelconfig"
	"github.com/MdSadiqMd/Kairo/internal/orchestrator"
	"github.com/MdSadiqMd/Kairo/internal/preflight"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "qctl: %v\n", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `qctl — Kairo lifecycle orchestrator

usage: qctl <command> [flags]

commands:
  preflight   Phase 0: verify tooling, credentials, region, state bucket
  up          Bring the platform up (phases 0→5)
  down        Tear the platform down (ordered teardown)
  verify      Phase 5 only: nodes Ready, vLLM /health, smoke eval
  sweep       Tag-based orphan sweep

Run "qctl <command> -h" for command flags.
`)
}

func run(args []string) error {
	if len(args) == 0 {
		usage()
		return fmt.Errorf("no command given")
	}
	cmd, rest := args[0], args[1:]

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	log := logx.New(os.Stdout)
	runner := &command.ExecRunner{}

	switch cmd {
	case "preflight":
		return cmdPreflight(ctx, rest, runner, log)
	case "up":
		return cmdUp(ctx, rest, runner, log)
	case "down":
		return cmdDown(ctx, rest, runner, log)
	case "verify":
		return cmdVerify(ctx, rest, runner, log)
	case "sweep":
		return cmdSweep(ctx, rest, runner, log)
	case "-h", "--help", "help":
		usage()
		return nil
	default:
		usage()
		return fmt.Errorf("unknown command %q", cmd)
	}
}

func newOrchestrator(env string, local bool, modelProfile string, r command.Runner, log *slog.Logger) (*orchestrator.Orchestrator, error) {
	if local {
		env = "local"
	}
	cfg, err := config.Load(env, ".")
	if err != nil {
		return nil, err
	}
	if cfg.IsLocal() {
		config.ExportLocalAWSEnv(cfg)
	}
	if modelProfile == "" {
		modelProfile = modelconfig.ProfileName(cfg.Env, cfg.IsLocal())
	}
	mcfg, err := modelconfig.LoadConfig(".")
	if err != nil {
		return nil, err
	}
	models, err := mcfg.Profile(modelProfile)
	if err != nil {
		return nil, err
	}
	o := orchestrator.New(cfg, models, r, log, os.Stdout, os.Stdin)
	o.ZKInference = mcfg.ZKInferenceEnabled()
	return o, nil
}

func resolveEnv(env string, local, prod bool) (string, error) {
	if local && prod {
		return "", fmt.Errorf("--local and --prod are mutually exclusive")
	}
	if local {
		return "local", nil
	}
	if prod {
		return "prod", nil
	}
	return env, nil
}

func cmdPreflight(ctx context.Context, args []string, r command.Runner, log *slog.Logger) error {
	fs := flag.NewFlagSet("preflight", flag.ContinueOnError)
	env := fs.String("env", "dev", "target environment (dev/staging/prod)")
	local := fs.Bool("local", false, "target MiniStack local environment")
	prod := fs.Bool("prod", false, "target production AWS environment")
	if err := fs.Parse(args); err != nil {
		return err
	}
	resolvedEnv, err := resolveEnv(*env, *local, *prod)
	if err != nil {
		return err
	}
	cfg, err := config.Load(resolvedEnv, ".")
	if err != nil {
		return err
	}
	if cfg.IsLocal() {
		config.ExportLocalAWSEnv(cfg)
	}
	rep, err := preflight.Run(ctx, r, cfg)
	if err != nil {
		return err
	}
	for _, res := range rep.Results {
		status := "ok"
		if !res.OK {
			status = "FAIL"
		}
		fmt.Printf("[%s] %-22s %s\n", status, res.Name, res.Detail)
		if !res.OK && res.Remediation != "" {
			fmt.Printf("        remediation: %s\n", res.Remediation)
		}
	}
	if !rep.OK() {
		return fmt.Errorf("preflight failed: %d check(s) did not pass", len(rep.Failures()))
	}
	return nil
}

func cmdUp(ctx context.Context, args []string, r command.Runner, log *slog.Logger) error {
	fs := flag.NewFlagSet("up", flag.ContinueOnError)
	env := fs.String("env", "dev", "target environment (dev/staging/prod)")
	local := fs.Bool("local", false, "target MiniStack local environment")
	prod := fs.Bool("prod", false, "target production AWS environment")
	model := fs.String("model", "", "override reasoner Hugging Face model id")
	replicas := fs.Int("replicas", 1, "vLLM replica count")
	withRL := fs.Bool("with-rl", false, "provision the RL plumbing")
	planOnly := fs.Bool("plan-only", false, "print terraform plan and exit")
	skipImages := fs.Bool("skip-images", false, "skip building/pushing images")
	modelProfile := fs.String("model-profile", "", "model profile from config/models.json")
	if err := fs.Parse(args); err != nil {
		return err
	}
	resolvedEnv, err := resolveEnv(*env, *local, *prod)
	if err != nil {
		return err
	}
	o, err := newOrchestrator(resolvedEnv, *local, *modelProfile, r, log)
	if err != nil {
		return err
	}
	return o.Up(ctx, orchestrator.UpOptions{
		Model:      *model,
		Replicas:   *replicas,
		WithRL:     *withRL,
		PlanOnly:   *planOnly,
		SkipImages: *skipImages,
	})
}

func cmdDown(ctx context.Context, args []string, r command.Runner, log *slog.Logger) error {
	fs := flag.NewFlagSet("down", flag.ContinueOnError)
	env := fs.String("env", "dev", "target environment (dev/staging/prod)")
	local := fs.Bool("local", false, "target MiniStack local environment")
	prod := fs.Bool("prod", false, "target production AWS environment")
	deleteData := fs.Bool("delete-data", false, "delete retained data buckets")
	nukeState := fs.Bool("nuke-state", false, "remove the terraform state bucket (dev only)")
	force := fs.Bool("force", false, "required for prod teardown")
	modelProfile := fs.String("model-profile", "", "model profile from config/models.json")
	if err := fs.Parse(args); err != nil {
		return err
	}
	resolvedEnv, err := resolveEnv(*env, *local, *prod)
	if err != nil {
		return err
	}
	o, err := newOrchestrator(resolvedEnv, *local, *modelProfile, r, log)
	if err != nil {
		return err
	}
	return o.Down(ctx, orchestrator.DownOptions{
		DeleteData: *deleteData,
		NukeState:  *nukeState,
		Force:      *force,
	})
}

func cmdVerify(ctx context.Context, args []string, r command.Runner, log *slog.Logger) error {
	fs := flag.NewFlagSet("verify", flag.ContinueOnError)
	env := fs.String("env", "dev", "target environment (dev/staging/prod)")
	local := fs.Bool("local", false, "target MiniStack local environment")
	prod := fs.Bool("prod", false, "target production AWS environment")
	modelProfile := fs.String("model-profile", "", "model profile from config/models.json")
	if err := fs.Parse(args); err != nil {
		return err
	}
	resolvedEnv, err := resolveEnv(*env, *local, *prod)
	if err != nil {
		return err
	}
	o, err := newOrchestrator(resolvedEnv, *local, *modelProfile, r, log)
	if err != nil {
		return err
	}
	return o.Verify(ctx)
}

func cmdSweep(ctx context.Context, args []string, r command.Runner, log *slog.Logger) error {
	fs := flag.NewFlagSet("sweep", flag.ContinueOnError)
	env := fs.String("env", "dev", "target environment (dev/staging/prod)")
	local := fs.Bool("local", false, "target MiniStack local environment")
	prod := fs.Bool("prod", false, "target production AWS environment")
	modelProfile := fs.String("model-profile", "", "model profile from config/models.json")
	dryRun := fs.Bool("dry-run", false, "list orphans without deleting")
	if err := fs.Parse(args); err != nil {
		return err
	}
	resolvedEnv, err := resolveEnv(*env, *local, *prod)
	if err != nil {
		return err
	}
	o, err := newOrchestrator(resolvedEnv, *local, *modelProfile, r, log)
	if err != nil {
		return err
	}
	_, err = o.Sweep(ctx, *dryRun)
	return err
}
