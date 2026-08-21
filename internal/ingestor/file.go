package ingestor

import (
	"bufio"
	"context"
	"io"
	"os"
	"path/filepath"
)

// FileSource reads newline-delimited JSON from an io.Reader and yields it in
// fixed-size batches. It backs local dev and tests (the AWS Kinesis source is
// the production counterpart).
type FileSource struct {
	scanner   *bufio.Scanner
	batchSize int
	closer    io.Closer
}

// NewFileSource reads NDJSON from r in batches of batchSize records.
func NewFileSource(r io.Reader, batchSize int) *FileSource {
	if batchSize <= 0 {
		batchSize = 500
	}
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 0, 64*1024), 16*1024*1024)
	fs := &FileSource{scanner: sc, batchSize: batchSize}
	if c, ok := r.(io.Closer); ok {
		fs.closer = c
	}
	return fs
}

// OpenFileSource opens path for reading as an NDJSON source.
func OpenFileSource(path string, batchSize int) (*FileSource, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	return NewFileSource(f, batchSize), nil
}

// Next returns the next batch of raw records, or io.EOF when the input ends.
func (s *FileSource) Next(ctx context.Context) ([][]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	var batch [][]byte
	for len(batch) < s.batchSize {
		if !s.scanner.Scan() {
			break
		}
		line := s.scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		batch = append(batch, append([]byte(nil), line...))
	}
	if err := s.scanner.Err(); err != nil {
		return nil, err
	}
	if len(batch) == 0 {
		return nil, io.EOF
	}
	return batch, nil
}

// Close releases the underlying reader if it is a Closer.
func (s *FileSource) Close() error {
	if s.closer != nil {
		return s.closer.Close()
	}
	return nil
}

// FileSink writes gzipped batches to a base directory, mirroring the S3 key as
// a relative path. It backs local dev and tests (the AWS S3 sink is the
// production counterpart).
type FileSink struct {
	baseDir string
}

// NewFileSink writes objects under baseDir.
func NewFileSink(baseDir string) *FileSink {
	return &FileSink{baseDir: baseDir}
}

// Write stores gzipped at baseDir/key, creating parent directories, and returns
// the key unchanged.
func (s *FileSink) Write(_ context.Context, key string, gzipped []byte) (string, error) {
	dest := filepath.Join(s.baseDir, filepath.FromSlash(key))
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return "", err
	}
	if err := os.WriteFile(dest, gzipped, 0o644); err != nil {
		return "", err
	}
	return key, nil
}
