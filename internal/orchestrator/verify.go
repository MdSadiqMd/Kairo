package orchestrator

import (
	"context"
	"fmt"
	"strings"
)

const routerSmokeScript = `
import json
import urllib.request

assert urllib.request.urlopen('http://localhost:8080/healthz', timeout=10).status == 200
assert urllib.request.urlopen('http://localhost:8080/readyz', timeout=10).status == 200

with open('/etc/kairo/secrets/api_keys.json') as f:
    api_key = next(iter(json.load(f)))

body = json.dumps({
    'model': 'reasoner',
    'messages': [{'role': 'user', 'content': 'Reply with ok.'}],
    'max_tokens': 4,
    'temperature': 0,
}).encode()
req = urllib.request.Request(
    'http://localhost:8080/v1/chat/completions',
    data=body,
    headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + api_key,
    },
)
resp = urllib.request.urlopen(req, timeout=120)
payload = json.loads(resp.read().decode())
assert payload['choices'][0]['message']['content']
print(payload['choices'][0]['message']['content'])
`

// Verify runs Phase 5: GPU nodes Ready, vLLM /health
// green (weights loaded), and the smoke eval suite passes. A failed check
// returns a non-nil error so `qctl up`/`qctl verify` exit non-zero.
func (o *Orchestrator) Verify(ctx context.Context) error {
	o.info("phase.verify.start")

	if _, err := o.kubectl(ctx, "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=10m"); err != nil {
		return fmt.Errorf("nodes not Ready: %w", err)
	}

	// vLLM is a private ClusterIP; probe /health from inside the router pod.
	health, err := o.kubectl(ctx, "-n", o.Cfg.Namespace, "exec", "deploy/router", "--",
		"python", "-c", "import urllib.request; print(urllib.request.urlopen('http://vllm-reasoner:8000/health', timeout=10).read().decode())")
	if err != nil {
		return fmt.Errorf("vLLM /health not green: %w", err)
	}
	o.info("phase.verify.health", "response", strings.TrimSpace(health))

	if out, err := o.kubectl(ctx, "-n", o.Cfg.Namespace, "exec", "deploy/router", "--",
		"python", "-c", routerSmokeScript); err != nil {
		return fmt.Errorf("router smoke request failed: %w", err)
	} else {
		o.info("phase.verify.smoke", "response", strings.TrimSpace(out))
	}

	o.info("phase.verify.ok")
	o.printf("✅ verify [%s]: nodes Ready, vLLM healthy, router smoke request passed\n", o.Cfg.Env)
	return nil
}
