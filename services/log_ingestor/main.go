// Command log_ingestor consumes InferenceEvent records and writes batched,
// gzipped, time-partitioned NDJSON to the raw-events lake. The default build
// is stdlib-only (file source/sink); build with
// `-tags aws` for the Kinesis source and S3 sink.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/MdSadiqMd/Kairo/internal/ingestor"
	"github.com/MdSadiqMd/Kairo/internal/logx"
)

type options struct {
	// batching
	maxRecords    int
	maxBytes      int
	flushInterval time.Duration
	prefix        string
	batchSize     int

	// default (file) build
	inputFile string
	outputDir string

	// aws build
	region   string
	stream   string
	shardID  string
	bucket   string
	kmsKeyID string
}

func parseFlags(args []string) (options, error) {
	fs := flag.NewFlagSet("log_ingestor", flag.ContinueOnError)
	var o options
	fs.IntVar(&o.maxRecords, "max-records", envInt("INGEST_MAX_RECORDS", 1000), "flush after N records")
	fs.IntVar(&o.maxBytes, "max-bytes", envInt("INGEST_MAX_BYTES", 8<<20), "flush after N buffered bytes")
	fs.DurationVar(&o.flushInterval, "flush-interval", envDuration("INGEST_FLUSH_INTERVAL", 30*time.Second), "flush at least this often")
	fs.StringVar(&o.prefix, "prefix", envStr("INGEST_PREFIX", "raw-events"), "partition root prefix")
	fs.IntVar(&o.batchSize, "batch-size", envInt("INGEST_BATCH_SIZE", 500), "source read batch size")

	fs.StringVar(&o.inputFile, "input", envStr("INGEST_INPUT", ""), "NDJSON input file (default build)")
	fs.StringVar(&o.outputDir, "output-dir", envStr("INGEST_OUTPUT_DIR", ""), "output directory (default build)")

	fs.StringVar(&o.region, "region", envStr("AWS_REGION", "us-west-2"), "AWS region (aws build)")
	fs.StringVar(&o.stream, "stream", envStr("INGEST_STREAM", ""), "Kinesis stream name (aws build)")
	fs.StringVar(&o.shardID, "shard-id", envStr("INGEST_SHARD_ID", ""), "Kinesis shard id (aws build)")
	fs.StringVar(&o.bucket, "bucket", envStr("INGEST_BUCKET", ""), "S3 raw-events bucket (aws build)")
	fs.StringVar(&o.kmsKeyID, "kms-key-id", envStr("INGEST_KMS_KEY_ID", ""), "KMS key id for S3 SSE (aws build)")

	if err := fs.Parse(args); err != nil {
		return options{}, err
	}
	return o, nil
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "log_ingestor: %v\n", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	opts, err := parseFlags(args)
	if err != nil {
		return err
	}
	log := logx.New(os.Stdout)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	source, closeSource, err := buildSource(ctx, opts)
	if err != nil {
		return err
	}
	defer func() { _ = closeSource() }()

	sink, err := buildSink(ctx, opts)
	if err != nil {
		return err
	}

	ing := ingestor.New(ingestor.Config{
		MaxRecords:    opts.maxRecords,
		MaxBytes:      opts.maxBytes,
		FlushInterval: opts.flushInterval,
		Prefix:        opts.prefix,
	}, sink, log)

	log.Info("ingestor.start", "prefix", opts.prefix, "max_records", opts.maxRecords, "max_bytes", opts.maxBytes)
	runErr := ing.Run(ctx, source)

	m := ing.Snapshot()
	log.Info("ingestor.stop",
		"valid", m.Valid, "malformed", m.Malformed,
		"batches", m.Batches, "objects", m.Objects, "bytes", m.Bytes)

	if runErr != nil && ctx.Err() == nil {
		return runErr
	}
	return nil
}

func envStr(key, def string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v, ok := os.LookupEnv(key); ok {
		var n int
		if _, err := fmt.Sscanf(v, "%d", &n); err == nil {
			return n
		}
	}
	return def
}

func envDuration(key string, def time.Duration) time.Duration {
	if v, ok := os.LookupEnv(key); ok {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}
