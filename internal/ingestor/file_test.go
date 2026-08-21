package ingestor

import (
	"bytes"
	"compress/gzip"
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestFileSourceBatches(t *testing.T) {
	var buf bytes.Buffer
	buf.Write(validEvent("a", "2026-07-11T14:00:00Z"))
	buf.WriteByte('\n')
	buf.WriteByte('\n') // blank line should be skipped
	buf.Write(validEvent("b", "2026-07-11T14:00:00Z"))
	buf.WriteByte('\n')
	buf.Write(validEvent("c", "2026-07-11T14:00:00Z"))

	src := NewFileSource(&buf, 2)
	ctx := context.Background()

	b1, err := src.Next(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(b1) != 2 {
		t.Fatalf("batch 1 size = %d, want 2", len(b1))
	}
	b2, err := src.Next(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(b2) != 1 {
		t.Fatalf("batch 2 size = %d, want 1", len(b2))
	}
	if _, err := src.Next(ctx); err != io.EOF {
		t.Fatalf("expected io.EOF, got %v", err)
	}
}

func TestFileSourceToFileSinkEndToEnd(t *testing.T) {
	dir := t.TempDir()
	inputPath := filepath.Join(dir, "events.ndjson")
	var in bytes.Buffer
	in.Write(validEvent("r1", "2026-07-11T14:00:00Z"))
	in.WriteByte('\n')
	in.Write(validEvent("r2", "2026-07-11T14:30:00Z"))
	in.WriteByte('\n')
	if err := os.WriteFile(inputPath, in.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}

	src, err := OpenFileSource(inputPath, 10)
	if err != nil {
		t.Fatal(err)
	}
	defer src.Close()

	outDir := filepath.Join(dir, "lake")
	sink := NewFileSink(outDir)
	ing := New(Config{MaxRecords: 1000, FlushInterval: time.Hour}, sink, nil)

	if err := ing.Run(context.Background(), src); err != nil {
		t.Fatalf("Run: %v", err)
	}

	var found []string
	_ = filepath.Walk(outDir, func(path string, info os.FileInfo, _ error) error {
		if info != nil && !info.IsDir() && strings.HasSuffix(path, ".ndjson.gz") {
			found = append(found, path)
		}
		return nil
	})
	if len(found) != 1 {
		t.Fatalf("expected 1 object on disk, got %d (%v)", len(found), found)
	}
	if !strings.Contains(found[0], filepath.FromSlash("raw-events/dt=2026-07-11/hour=14")) {
		t.Errorf("unexpected partition path %q", found[0])
	}

	raw, err := os.ReadFile(found[0])
	if err != nil {
		t.Fatal(err)
	}
	gr, err := gzip.NewReader(bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	data, _ := io.ReadAll(gr)
	if lines := strings.Count(strings.TrimRight(string(data), "\n"), "\n") + 1; lines != 2 {
		t.Errorf("expected 2 NDJSON lines, got %d", lines)
	}
}
