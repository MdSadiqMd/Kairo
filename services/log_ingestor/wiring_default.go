//go:build !aws

package main

import (
	"context"
	"fmt"

	"github.com/MdSadiqMd/Kairo/internal/ingestor"
)

// buildSource/buildSink for the default (offline, stdlib-only) build read and
// write local files. The AWS Kinesis/S3 wiring lives in wiring_aws.go behind
// the `aws` build tag.

func buildSource(_ context.Context, opts options) (ingestor.RecordSource, func() error, error) {
	if opts.inputFile == "" {
		return nil, nil, fmt.Errorf("--input is required in the default build (use -tags aws for Kinesis)")
	}
	src, err := ingestor.OpenFileSource(opts.inputFile, opts.batchSize)
	if err != nil {
		return nil, nil, err
	}
	return src, src.Close, nil
}

func buildSink(_ context.Context, opts options) (ingestor.BatchSink, error) {
	if opts.outputDir == "" {
		return nil, fmt.Errorf("--output-dir is required in the default build (use -tags aws for S3)")
	}
	return ingestor.NewFileSink(opts.outputDir), nil
}
