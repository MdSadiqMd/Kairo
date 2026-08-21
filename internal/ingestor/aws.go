//go:build aws

// Production AWS adapters: a Kinesis RecordSource and an S3 BatchSink. This
// file compiles only with `-tags aws`, which is the only build that pulls
// aws-sdk-go-v2 into the module graph. The default (untagged) build stays
// standard-library only and offline.
package ingestor

import (
	"bytes"
	"context"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/kinesis"
	"github.com/aws/aws-sdk-go-v2/service/kinesis/types"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// KinesisAPI is the subset of the Kinesis client the source uses.
type KinesisAPI interface {
	GetShardIterator(ctx context.Context, in *kinesis.GetShardIteratorInput, optFns ...func(*kinesis.Options)) (*kinesis.GetShardIteratorOutput, error)
	GetRecords(ctx context.Context, in *kinesis.GetRecordsInput, optFns ...func(*kinesis.Options)) (*kinesis.GetRecordsOutput, error)
}

// KinesisSource reads records from a single Kinesis shard. For multi-shard
// streams, run one KinesisSource per shard (KCL-style) behind a fan-in.
type KinesisSource struct {
	client   KinesisAPI
	stream   string
	shardID  string
	iterator *string
	pollWait time.Duration
}

// NewKinesisSource starts reading shardID of stream from LATEST.
func NewKinesisSource(ctx context.Context, client KinesisAPI, stream, shardID string) (*KinesisSource, error) {
	out, err := client.GetShardIterator(ctx, &kinesis.GetShardIteratorInput{
		StreamName:        aws.String(stream),
		ShardId:           aws.String(shardID),
		ShardIteratorType: types.ShardIteratorTypeLatest,
	})
	if err != nil {
		return nil, fmt.Errorf("get shard iterator: %w", err)
	}
	return &KinesisSource{
		client:   client,
		stream:   stream,
		shardID:  shardID,
		iterator: out.ShardIterator,
		pollWait: time.Second,
	}, nil
}

// Next returns the data payloads of the next Kinesis batch. An empty poll waits
// pollWait before the caller retries, respecting the GetRecords rate limit.
func (s *KinesisSource) Next(ctx context.Context) ([][]byte, error) {
	if s.iterator == nil {
		return nil, fmt.Errorf("shard %s closed", s.shardID)
	}
	out, err := s.client.GetRecords(ctx, &kinesis.GetRecordsInput{ShardIterator: s.iterator})
	if err != nil {
		return nil, fmt.Errorf("get records: %w", err)
	}
	s.iterator = out.NextShardIterator
	if len(out.Records) == 0 {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(s.pollWait):
		}
		return [][]byte{}, nil
	}
	batch := make([][]byte, 0, len(out.Records))
	for _, r := range out.Records {
		batch = append(batch, r.Data)
	}
	return batch, nil
}

// S3API is the subset of the S3 client the sink uses.
type S3API interface {
	PutObject(ctx context.Context, in *s3.PutObjectInput, optFns ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

// S3Sink writes gzipped batches to the raw-events bucket with KMS encryption.
type S3Sink struct {
	client   S3API
	bucket   string
	kmsKeyID string
}

// NewS3Sink writes to bucket; kmsKeyID may be empty to use the bucket default.
func NewS3Sink(client S3API, bucket, kmsKeyID string) *S3Sink {
	return &S3Sink{client: client, bucket: bucket, kmsKeyID: kmsKeyID}
}

// Write puts gzipped at s3://bucket/key and returns the full s3 URI.
func (s *S3Sink) Write(ctx context.Context, key string, gzipped []byte) (string, error) {
	in := &s3.PutObjectInput{
		Bucket:          aws.String(s.bucket),
		Key:             aws.String(key),
		Body:            bytes.NewReader(gzipped),
		ContentType:     aws.String("application/gzip"),
		ContentEncoding: aws.String("gzip"),
	}
	if s.kmsKeyID != "" {
		in.ServerSideEncryption = "aws:kms"
		in.SSEKMSKeyId = aws.String(s.kmsKeyID)
	}
	if _, err := s.client.PutObject(ctx, in); err != nil {
		return "", fmt.Errorf("put object: %w", err)
	}
	return fmt.Sprintf("s3://%s/%s", s.bucket, key), nil
}
