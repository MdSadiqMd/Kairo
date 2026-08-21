// Package ingestor implements the high-throughput log ingestor: it reads
// InferenceEvent records from a source, batches them,
// gzips time-partitioned NDJSON, and writes to the raw-events lake. The core is
// stdlib-only and testable; AWS adapters live in //go:build aws files.
package ingestor

import (
	"encoding/json"
	"fmt"
	"time"
)

// InferenceEvent mirrors libs/kairo_common/src/kairo_common/events.py. It is the
// contract shared by the router (producer) and this ingestor (consumer).
// Optional fields are pointers so they round-trip as absent rather than zero.
type InferenceEvent struct {
	SchemaVersion   string   `json:"schema_version"`
	RequestID       string   `json:"request_id"`
	Timestamp       string   `json:"timestamp"`
	TenantID        string   `json:"tenant_id"`
	Route           string   `json:"route"`
	Model           string   `json:"model"`
	ModelVersion    string   `json:"model_version"`
	PromptHash      string   `json:"prompt_hash"`
	InputTokens     int      `json:"input_tokens"`
	OutputTokens    int      `json:"output_tokens"`
	LatencyMs       int      `json:"latency_ms"`
	TTFTMs          *int     `json:"ttft_ms,omitempty"`
	TPOTMs          *float64 `json:"tpot_ms,omitempty"`
	FinishReason    *string  `json:"finish_reason,omitempty"`
	SafetyDecision  string   `json:"safety_decision"`
	ToolCallsCount  int      `json:"tool_calls_count"`
	VerifierScore   *float64 `json:"verifier_score,omitempty"`
	UserFeedback    *string  `json:"user_feedback,omitempty"`
	TrainingConsent bool     `json:"training_consent"`
	PolicyVersion   int      `json:"policy_version"`
	PromptRaw       *string  `json:"prompt_raw,omitempty"`
	OutputRaw       *string  `json:"output_raw,omitempty"`
}

// parseEvent validates that raw is a well-formed InferenceEvent and returns the
// event plus its parsed timestamp (used for partitioning). Malformed records
// are rejected here and dropped+counted by the Ingestor — never blocking the
// pipeline.
func parseEvent(raw []byte) (InferenceEvent, time.Time, error) {
	var ev InferenceEvent
	if err := json.Unmarshal(raw, &ev); err != nil {
		return ev, time.Time{}, fmt.Errorf("invalid json: %w", err)
	}
	if ev.RequestID == "" {
		return ev, time.Time{}, fmt.Errorf("missing request_id")
	}
	if ev.TenantID == "" {
		return ev, time.Time{}, fmt.Errorf("missing tenant_id")
	}
	ts, err := parseTimestamp(ev.Timestamp)
	if err != nil {
		return ev, time.Time{}, err
	}
	return ev, ts, nil
}

// parseTimestamp accepts RFC3339 / ISO-8601 timestamps, with or without a
// fractional second, and normalizes to UTC for partition derivation.
func parseTimestamp(s string) (time.Time, error) {
	if s == "" {
		return time.Time{}, fmt.Errorf("missing timestamp")
	}
	if t, err := time.Parse(time.RFC3339Nano, s); err == nil {
		return t.UTC(), nil
	}
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid timestamp %q: %w", s, err)
	}
	return t.UTC(), nil
}
