package ingestor

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/rand"
	"fmt"
	"io"
	"log/slog"
	"sort"
	"sync"
	"time"
)

// RecordSource yields batches of raw, newline-free JSON records. Next must
// honour ctx cancellation and return io.EOF when the source is exhausted.
type RecordSource interface {
	Next(ctx context.Context) ([][]byte, error)
}

// BatchSink persists an already-gzipped batch under key and returns the final
// storage key (a sink may prefix a bucket/path).
type BatchSink interface {
	Write(ctx context.Context, key string, gzipped []byte) (string, error)
}

// Config bounds a batch. A flush fires on whichever threshold trips first.
type Config struct {
	MaxRecords    int
	MaxBytes      int
	FlushInterval time.Duration
	Prefix        string // partition root, e.g. "raw-events"
}

func (c Config) withDefaults() Config {
	if c.MaxRecords <= 0 {
		c.MaxRecords = 1000
	}
	if c.MaxBytes <= 0 {
		c.MaxBytes = 8 << 20 // 8 MiB
	}
	if c.FlushInterval <= 0 {
		c.FlushInterval = 30 * time.Second
	}
	if c.Prefix == "" {
		c.Prefix = "raw-events"
	}
	return c
}

// Metrics is a snapshot of counters. Safe to read after Ingestor.Snapshot.
type Metrics struct {
	Valid     int64
	Malformed int64
	Batches   int64
	Objects   int64
	Bytes     int64
}

type entry struct {
	raw []byte
	ts  time.Time
}

// Ingestor batches validated records and writes gzipped, time-partitioned
// NDJSON objects to the sink. It is safe for concurrent Ingest/Flush calls.
type Ingestor struct {
	cfg   Config
	sink  BatchSink
	log   *slog.Logger
	genID func() string
	now   func() time.Time

	mu       sync.Mutex
	buf      []entry
	bufBytes int
	metrics  Metrics
}

// New builds an Ingestor. log may be nil.
func New(cfg Config, sink BatchSink, log *slog.Logger) *Ingestor {
	if log == nil {
		log = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	return &Ingestor{
		cfg:   cfg.withDefaults(),
		sink:  sink,
		log:   log,
		genID: newUUID,
		now:   time.Now,
	}
}

// Snapshot returns a copy of the current counters.
func (i *Ingestor) Snapshot() Metrics {
	i.mu.Lock()
	defer i.mu.Unlock()
	return i.metrics
}

// Ingest validates each raw record, buffers the valid ones, and flushes if a
// size/count threshold trips. Malformed records are dropped and counted; they
// never block the pipeline.
func (i *Ingestor) Ingest(ctx context.Context, records [][]byte) error {
	i.mu.Lock()
	var flushNow bool
	for _, raw := range records {
		raw = trimNewline(raw)
		if len(raw) == 0 {
			continue
		}
		_, ts, err := parseEvent(raw)
		if err != nil {
			i.metrics.Malformed++
			i.log.Warn("record.dropped", "err", err.Error())
			continue
		}
		// Copy so callers may reuse their buffer.
		rec := append([]byte(nil), raw...)
		i.buf = append(i.buf, entry{raw: rec, ts: ts})
		i.bufBytes += len(rec) + 1 // +1 for the NDJSON newline
		i.metrics.Valid++
		if len(i.buf) >= i.cfg.MaxRecords || i.bufBytes >= i.cfg.MaxBytes {
			flushNow = true
		}
	}
	i.mu.Unlock()

	if flushNow {
		return i.Flush(ctx)
	}
	return nil
}

// Flush groups all buffered records by partition (derived from each record's
// event timestamp), gzips one NDJSON object per partition, and writes them.
func (i *Ingestor) Flush(ctx context.Context) error {
	i.mu.Lock()
	if len(i.buf) == 0 {
		i.mu.Unlock()
		return nil
	}
	pending := i.buf
	i.buf = nil
	i.bufBytes = 0
	i.metrics.Batches++
	i.mu.Unlock()

	groups := make(map[string][]entry)
	for _, e := range pending {
		p := PartitionPrefix(i.cfg.Prefix, e.ts)
		groups[p] = append(groups[p], e)
	}

	// Deterministic order keeps logs/tests stable.
	prefixes := make([]string, 0, len(groups))
	for p := range groups {
		prefixes = append(prefixes, p)
	}
	sort.Strings(prefixes)

	for _, p := range prefixes {
		key := fmt.Sprintf("%s/%s.ndjson.gz", p, i.genID())
		gzipped, err := gzipNDJSON(groups[p])
		if err != nil {
			return err
		}
		finalKey, err := i.sink.Write(ctx, key, gzipped)
		if err != nil {
			return fmt.Errorf("sink write %s: %w", key, err)
		}
		i.mu.Lock()
		i.metrics.Objects++
		i.metrics.Bytes += int64(len(gzipped))
		i.mu.Unlock()
		i.log.Info("batch.written", "key", finalKey, "records", len(groups[p]), "bytes", len(gzipped))
	}
	return nil
}

// Run drives the ingestor from source until ctx is cancelled or the source is
// exhausted, flushing on the configured interval and once more on shutdown
// (graceful drain, so in-flight records are not lost).
func (i *Ingestor) Run(ctx context.Context, source RecordSource) error {
	ticker := time.NewTicker(i.cfg.FlushInterval)
	defer ticker.Stop()

	flushCtx := context.WithoutCancel(ctx)
	for {
		select {
		case <-ctx.Done():
			return i.Flush(flushCtx)
		case <-ticker.C:
			if err := i.Flush(ctx); err != nil {
				return err
			}
		default:
		}

		batch, err := source.Next(ctx)
		if err == io.EOF {
			return i.Flush(flushCtx)
		}
		if err != nil {
			if ctx.Err() != nil {
				return i.Flush(flushCtx)
			}
			return fmt.Errorf("source: %w", err)
		}
		if err := i.Ingest(ctx, batch); err != nil {
			return err
		}
	}
}

// PartitionPrefix derives the S3 partition prefix from an event timestamp,
// e.g. raw-events/dt=2026-07-11/hour=14.
func PartitionPrefix(root string, ts time.Time) string {
	ts = ts.UTC()
	return fmt.Sprintf("%s/dt=%s/hour=%02d", root, ts.Format("2006-01-02"), ts.Hour())
}

func gzipNDJSON(entries []entry) ([]byte, error) {
	var buf bytes.Buffer
	gw := gzip.NewWriter(&buf)
	for _, e := range entries {
		if _, err := gw.Write(e.raw); err != nil {
			return nil, err
		}
		if _, err := gw.Write([]byte{'\n'}); err != nil {
			return nil, err
		}
	}
	if err := gw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func trimNewline(b []byte) []byte {
	for len(b) > 0 && (b[len(b)-1] == '\n' || b[len(b)-1] == '\r') {
		b = b[:len(b)-1]
	}
	return b
}

// newUUID returns an RFC 4122 v4 UUID using crypto/rand (stdlib only).
func newUUID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}
