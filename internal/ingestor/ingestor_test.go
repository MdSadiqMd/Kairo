package ingestor

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
	"time"
)

// memSink captures written batches in memory for assertions.
type memSink struct {
	mu      sync.Mutex
	objects map[string][]byte // key -> gzipped bytes
}

func newMemSink() *memSink { return &memSink{objects: map[string][]byte{}} }

func (s *memSink) Write(_ context.Context, key string, gzipped []byte) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.objects[key] = append([]byte(nil), gzipped...)
	return key, nil
}

func (s *memSink) keys() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, 0, len(s.objects))
	for k := range s.objects {
		out = append(out, k)
	}
	return out
}

func (s *memSink) decode(t *testing.T, key string) []string {
	t.Helper()
	s.mu.Lock()
	raw := s.objects[key]
	s.mu.Unlock()
	gr, err := gzip.NewReader(bytes.NewReader(raw))
	if err != nil {
		t.Fatalf("gzip reader: %v", err)
	}
	data, err := io.ReadAll(gr)
	if err != nil {
		t.Fatalf("gzip read: %v", err)
	}
	var lines []string
	for _, l := range strings.Split(strings.TrimRight(string(data), "\n"), "\n") {
		if l != "" {
			lines = append(lines, l)
		}
	}
	return lines
}

func validEvent(id, ts string) []byte {
	ev := InferenceEvent{
		SchemaVersion: "1.0",
		RequestID:     id,
		Timestamp:     ts,
		TenantID:      "tenant-a",
		Route:         "normal",
		Model:         "model-32b",
		ModelVersion:  "2026-07-11-001",
		PromptHash:    "sha256:abc",
	}
	b, _ := json.Marshal(ev)
	return b
}

func TestPartitionPrefix(t *testing.T) {
	ts, _ := time.Parse(time.RFC3339, "2026-07-11T14:37:09Z")
	got := PartitionPrefix("raw-events", ts)
	want := "raw-events/dt=2026-07-11/hour=14"
	if got != want {
		t.Errorf("PartitionPrefix = %q, want %q", got, want)
	}
}

func TestPartitionPrefixNormalizesToUTC(t *testing.T) {
	// 01:30 at +05:30 is 20:00 UTC the previous day.
	ts, err := time.Parse(time.RFC3339, "2026-07-12T01:30:00+05:30")
	if err != nil {
		t.Fatal(err)
	}
	got := PartitionPrefix("raw-events", ts)
	want := "raw-events/dt=2026-07-11/hour=20"
	if got != want {
		t.Errorf("PartitionPrefix = %q, want %q", got, want)
	}
}

func TestFlushGzipRoundTrip(t *testing.T) {
	sink := newMemSink()
	ing := New(Config{Prefix: "raw-events"}, sink, nil)
	rec := validEvent("r1", "2026-07-11T14:00:00Z")
	if err := ing.Ingest(context.Background(), [][]byte{rec}); err != nil {
		t.Fatal(err)
	}
	if err := ing.Flush(context.Background()); err != nil {
		t.Fatal(err)
	}
	keys := sink.keys()
	if len(keys) != 1 {
		t.Fatalf("expected 1 object, got %d", len(keys))
	}
	if !strings.HasPrefix(keys[0], "raw-events/dt=2026-07-11/hour=14/") ||
		!strings.HasSuffix(keys[0], ".ndjson.gz") {
		t.Errorf("unexpected key %q", keys[0])
	}
	lines := sink.decode(t, keys[0])
	if len(lines) != 1 {
		t.Fatalf("expected 1 line, got %d", len(lines))
	}
	var back InferenceEvent
	if err := json.Unmarshal([]byte(lines[0]), &back); err != nil {
		t.Fatalf("round-trip unmarshal: %v", err)
	}
	if back.RequestID != "r1" {
		t.Errorf("RequestID = %q, want r1", back.RequestID)
	}
}

func TestBatchingCountThreshold(t *testing.T) {
	sink := newMemSink()
	ing := New(Config{MaxRecords: 3, MaxBytes: 1 << 30, FlushInterval: time.Hour}, sink, nil)
	ctx := context.Background()

	for i := 0; i < 2; i++ {
		_ = ing.Ingest(ctx, [][]byte{validEvent(fmt.Sprintf("r%d", i), "2026-07-11T14:00:00Z")})
	}
	if got := len(sink.keys()); got != 0 {
		t.Fatalf("no flush expected before threshold, got %d objects", got)
	}
	// Third record trips MaxRecords=3.
	_ = ing.Ingest(ctx, [][]byte{validEvent("r2", "2026-07-11T14:00:00Z")})
	if got := len(sink.keys()); got != 1 {
		t.Fatalf("expected flush at count threshold, got %d objects", got)
	}
	if m := ing.Snapshot(); m.Valid != 3 || m.Batches != 1 {
		t.Errorf("metrics = %+v, want Valid=3 Batches=1", m)
	}
}

func TestBatchingByteThreshold(t *testing.T) {
	sink := newMemSink()
	rec := validEvent("r0", "2026-07-11T14:00:00Z")
	// MaxBytes just above one record so the second record trips it.
	ing := New(Config{MaxRecords: 1000, MaxBytes: len(rec) + 5, FlushInterval: time.Hour}, sink, nil)
	ctx := context.Background()

	_ = ing.Ingest(ctx, [][]byte{rec})
	if len(sink.keys()) != 0 {
		t.Fatal("no flush expected after one record")
	}
	_ = ing.Ingest(ctx, [][]byte{validEvent("r1", "2026-07-11T14:00:00Z")})
	if len(sink.keys()) != 1 {
		t.Fatalf("expected flush at byte threshold, got %d", len(sink.keys()))
	}
}

func TestMalformedRecordsDroppedAndCounted(t *testing.T) {
	sink := newMemSink()
	ing := New(Config{MaxRecords: 1000, FlushInterval: time.Hour}, sink, nil)
	ctx := context.Background()

	records := [][]byte{
		validEvent("good1", "2026-07-11T14:00:00Z"),
		[]byte(`{"not":"an event"}`),                                          // missing request_id/tenant/timestamp
		[]byte(`{"broken json`),                                               // invalid JSON
		[]byte(`{"request_id":"x","tenant_id":"t","timestamp":"not-a-date"}`), // bad timestamp
		validEvent("good2", "2026-07-11T15:00:00Z"),
	}
	if err := ing.Ingest(ctx, records); err != nil {
		t.Fatal(err)
	}
	if err := ing.Flush(ctx); err != nil {
		t.Fatal(err)
	}
	m := ing.Snapshot()
	if m.Valid != 2 {
		t.Errorf("Valid = %d, want 2", m.Valid)
	}
	if m.Malformed != 3 {
		t.Errorf("Malformed = %d, want 3", m.Malformed)
	}
	// Two valid records fall in different hours -> two partitioned objects.
	if got := len(sink.keys()); got != 2 {
		t.Errorf("expected 2 partitioned objects, got %d (%v)", got, sink.keys())
	}
}

func TestFlushPartitionsMixedTimestamps(t *testing.T) {
	sink := newMemSink()
	ing := New(Config{MaxRecords: 1000, FlushInterval: time.Hour}, sink, nil)
	ctx := context.Background()
	_ = ing.Ingest(ctx, [][]byte{
		validEvent("a", "2026-07-11T14:10:00Z"),
		validEvent("b", "2026-07-11T14:50:00Z"),
		validEvent("c", "2026-07-12T09:00:00Z"),
	})
	_ = ing.Flush(ctx)

	keys := sink.keys()
	if len(keys) != 2 {
		t.Fatalf("expected 2 partitions, got %d (%v)", len(keys), keys)
	}
	var hour14, day12 int
	for _, k := range keys {
		if strings.Contains(k, "dt=2026-07-11/hour=14") {
			hour14 = len(sink.decode(t, k))
		}
		if strings.Contains(k, "dt=2026-07-12/hour=09") {
			day12 = len(sink.decode(t, k))
		}
	}
	if hour14 != 2 || day12 != 1 {
		t.Errorf("partition record counts: hour14=%d day12=%d, want 2 and 1", hour14, day12)
	}
}

func TestRunFlushesOnShutdown(t *testing.T) {
	sink := newMemSink()
	// High thresholds so only shutdown triggers the flush.
	ing := New(Config{MaxRecords: 1000, MaxBytes: 1 << 30, FlushInterval: time.Hour}, sink, nil)

	src := &sliceSource{
		batches: [][][]byte{
			{validEvent("r1", "2026-07-11T14:00:00Z"), validEvent("r2", "2026-07-11T14:00:00Z")},
		},
		drained: make(chan struct{}),
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- ing.Run(ctx, src) }()

	// Wait until the source has been drained, then cancel.
	src.waitDrained(t)
	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return after cancel")
	}

	if got := len(sink.keys()); got != 1 {
		t.Fatalf("expected buffered records flushed on shutdown, got %d objects", got)
	}
	if m := ing.Snapshot(); m.Valid != 2 {
		t.Errorf("Valid = %d, want 2", m.Valid)
	}
}

func TestRunReturnsOnEOF(t *testing.T) {
	sink := newMemSink()
	ing := New(Config{MaxRecords: 1000, FlushInterval: time.Hour}, sink, nil)
	src := &eofSource{batches: [][][]byte{
		{validEvent("r1", "2026-07-11T14:00:00Z")},
	}}
	if err := ing.Run(context.Background(), src); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if len(sink.keys()) != 1 {
		t.Fatalf("expected EOF to flush remaining, got %d objects", len(sink.keys()))
	}
}

// eofSource yields preset batches then returns io.EOF (source exhausted).
type eofSource struct {
	batches [][][]byte
	idx     int
}

func (s *eofSource) Next(_ context.Context) ([][]byte, error) {
	if s.idx >= len(s.batches) {
		return nil, io.EOF
	}
	b := s.batches[s.idx]
	s.idx++
	return b, nil
}

// sliceSource yields preset batches then blocks (until ctx cancel) so the
// shutdown-flush path can be exercised deterministically. drained must be
// created before Run starts.
type sliceSource struct {
	mu         sync.Mutex
	batches    [][][]byte
	idx        int
	drained    chan struct{}
	drainedYet bool
}

func (s *sliceSource) Next(ctx context.Context) ([][]byte, error) {
	s.mu.Lock()
	if s.idx < len(s.batches) {
		b := s.batches[s.idx]
		s.idx++
		s.mu.Unlock()
		return b, nil
	}
	if !s.drainedYet {
		s.drainedYet = true
		close(s.drained)
	}
	s.mu.Unlock()
	// No more preset data: block until the ingestor is cancelled.
	<-ctx.Done()
	return nil, ctx.Err()
}

func (s *sliceSource) waitDrained(t *testing.T) {
	t.Helper()
	select {
	case <-s.drained:
	case <-time.After(5 * time.Second):
		t.Fatal("source was not drained in time")
	}
}
