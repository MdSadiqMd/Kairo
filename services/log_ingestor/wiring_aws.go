//go:build aws

package main

import (
	"context"
	"fmt"

	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/kinesis"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"github.com/MdSadiqMd/Kairo/internal/ingestor"
)

// buildSource/buildSink for the production build read from Kinesis and write to
// S3. Compiled only with `-tags aws`.

func buildSource(ctx context.Context, opts options) (ingestor.RecordSource, func() error, error) {
	if opts.stream == "" || opts.shardID == "" {
		return nil, nil, fmt.Errorf("--stream and --shard-id are required with -tags aws")
	}
	cfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(opts.region))
	if err != nil {
		return nil, nil, err
	}
	client := kinesis.NewFromConfig(cfg)
	src, err := ingestor.NewKinesisSource(ctx, client, opts.stream, opts.shardID)
	if err != nil {
		return nil, nil, err
	}
	return src, func() error { return nil }, nil
}

func buildSink(ctx context.Context, opts options) (ingestor.BatchSink, error) {
	if opts.bucket == "" {
		return nil, fmt.Errorf("--bucket is required with -tags aws")
	}
	cfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(opts.region))
	if err != nil {
		return nil, err
	}
	client := s3.NewFromConfig(cfg)
	return ingestor.NewS3Sink(client, opts.bucket, opts.kmsKeyID), nil
}
