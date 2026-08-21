// Package logx provides a small structured JSON logger built on log/slog so all
// qctl and log_ingestor output is machine-parseable on stdout.
package logx

import (
	"io"
	"log/slog"
	"os"
)

// New returns a JSON slog.Logger writing to w. If w is nil it writes to stdout.
func New(w io.Writer) *slog.Logger {
	if w == nil {
		w = os.Stdout
	}
	return slog.New(slog.NewJSONHandler(w, &slog.HandlerOptions{Level: slog.LevelInfo}))
}
