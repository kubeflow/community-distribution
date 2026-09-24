#!/usr/bin/env bash
# Prove direct PingSource delivery without adding a Broker or channel provider.
set -euo pipefail
fixture=knative-helm-events
namespace=knative-eventing
cleanup() {
    if [[ "${KNATIVE_HELM_KEEP_FIXTURE:-false}" != true ]]; then
        kubectl delete pingsource,service,deployment "$fixture" -n "$namespace" --ignore-not-found
    fi
}
trap cleanup EXIT
kubectl apply -n "$namespace" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $fixture
spec:
  replicas: 1
  selector:
    matchLabels: {helm-test: $fixture}
  template:
    metadata:
      labels: {helm-test: $fixture}
      annotations:
        sidecar.istio.io/inject: "false"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        seccompProfile: {type: RuntimeDefault}
      containers:
      - name: receiver
        image: python:3.12-alpine
        command: [python3, -u, -c]
        args:
        - |
          import http.server, json
          class Receiver(http.server.BaseHTTPRequestHandler):
              def do_POST(self):
                  body = self.rfile.read(int(self.headers['Content-Length']))
                  print(json.dumps({'type': self.headers.get('Ce-Type'), 'data': body.decode()}), flush=True)
                  self.send_response(204)
                  self.end_headers()
          http.server.HTTPServer(('0.0.0.0', 8080), Receiver).serve_forever()
        ports:
        - containerPort: 8080
        resources:
          requests: {cpu: 50m, memory: 32Mi}
          limits: {cpu: 200m, memory: 128Mi}
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop: [ALL]
---
apiVersion: v1
kind: Service
metadata:
  name: $fixture
spec:
  selector: {helm-test: $fixture}
  ports:
  - port: 80
    targetPort: 8080
---
apiVersion: sources.knative.dev/v1
kind: PingSource
metadata:
  name: $fixture
spec:
  schedule: "* * * * *"
  contentType: application/json
  data: '{"message":"knative-helm-event-ok"}'
  sink:
    ref:
      apiVersion: v1
      kind: Service
      name: $fixture
EOF
kubectl rollout status "deployment/$fixture" -n "$namespace" --timeout=120s
kubectl wait --for=condition=Ready "pingsource/$fixture" -n "$namespace" --timeout=180s
# Use only logs since this invocation, so replay cannot pass on old delivery.
started=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)
delivered=false
for ((attempt=0; attempt<75; attempt++)); do
    if kubectl logs "deployment/$fixture" -n "$namespace" --since-time="$started" | \
        python3 -c 'import json,sys
count=0
for line in sys.stdin:
    try:
        event=json.loads(line)
        count += event.get("type")=="dev.knative.sources.ping" and json.loads(event.get("data", "null"))=={"message":"knative-helm-event-ok"}
    except (ValueError, TypeError, AttributeError):
        pass
print("Matching newly delivered CloudEvents:", count)
sys.exit(count < 1)'; then
        delivered=true
        break
    fi
    sleep 2
done
if [[ "$delivered" != true ]]; then
    echo "No matching fresh PingSource CloudEvent arrived within 150 seconds" >&2
    exit 1
fi
echo "Eventing delivered the exact PingSource CloudEvent payload."
