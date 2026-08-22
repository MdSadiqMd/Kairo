package command

import (
	"context"
	"strings"
	"sync"
)

// Call is a single recorded invocation.
type Call struct {
	Name string
	Args []string
}

func (c Call) String() string {
	if len(c.Args) == 0 {
		return c.Name
	}
	return c.Name + " " + strings.Join(c.Args, " ")
}

// FakeRunner is a test double for Runner: it records every call and returns
// canned output instead of executing anything, so orchestration logic is
// unit-testable offline (no AWS, cluster, binaries, or network). It lives in a
// normal .go file rather than a _test.go one because tests in several packages
// (orchestrator, preflight) import it. Safe for concurrent use. Handler, when
// set, computes the response for a call; otherwise Run returns empty output and
// no error.
type FakeRunner struct {
	mu      sync.Mutex
	Calls   []Call
	Handler func(name string, args []string) (string, error)
}

func (f *FakeRunner) Run(_ context.Context, name string, args ...string) (string, error) {
	f.mu.Lock()
	f.Calls = append(f.Calls, Call{Name: name, Args: append([]string(nil), args...)})
	f.mu.Unlock()
	if f.Handler != nil {
		return f.Handler(name, args)
	}
	return "", nil
}

// Names returns the ordered list of command names that were invoked.
func (f *FakeRunner) Names() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	names := make([]string, len(f.Calls))
	for i, c := range f.Calls {
		names[i] = c.Name
	}
	return names
}

// Commands returns each recorded call rendered as "name arg0 arg1 ...".
func (f *FakeRunner) Commands() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]string, len(f.Calls))
	for i, c := range f.Calls {
		out[i] = c.String()
	}
	return out
}

// IndexOf returns the index of the first recorded call whose rendered command
// contains sub, or -1 if none match. Used by tests to assert ordering.
func (f *FakeRunner) IndexOf(sub string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	for i, c := range f.Calls {
		if strings.Contains(c.String(), sub) {
			return i
		}
	}
	return -1
}
