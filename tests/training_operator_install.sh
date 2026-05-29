#!/bin/bash
set -euo pipefail

cd applications/training-operator/upstream
kustomize build overlays/kubeflow | kubectl apply --server-side --force-conflicts -f -
cd -

PYTORCH_INIT_TEMPLATE_ARG="--pytorch-init-container-template-file=/etc/restricted-pytorch-init-container/initContainer.yaml"

kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: restricted-pytorch-init-container
  namespace: kubeflow
data:
  initContainer.yaml: |
    - name: init-pytorch
      image: {{.InitContainerImage}}
      imagePullPolicy: IfNotPresent
      resources:
        limits:
          cpu: 100m
          memory: 20Mi
        requests:
          cpu: 50m
          memory: 10Mi
      command: ['sh', '-c', 'err=1;for i in $(seq {{.MaxTries}}); do if nslookup {{.MasterAddr}}; then err=0 && break; fi;echo waiting for master; sleep 2; done; exit $err']
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop:
          - ALL
        runAsNonRoot: true
        runAsUser: 1000
        seccompProfile:
          type: RuntimeDefault
EOF

kubectl patch deployment training-operator -n kubeflow --type=strategic -p='
spec:
  template:
    spec:
      containers:
      - name: training-operator
        volumeMounts:
        - name: restricted-pytorch-init-container
          mountPath: /etc/restricted-pytorch-init-container
          readOnly: true
      volumes:
      - name: restricted-pytorch-init-container
        configMap:
          name: restricted-pytorch-init-container
'

TRAINING_OPERATOR_CONTAINER_INDEX=$(
  kubectl get deployment training-operator -n kubeflow -o json | \
    jq -r '.spec.template.spec.containers | to_entries[] | select(.value.name == "training-operator") | .key'
)
if [ -z "$TRAINING_OPERATOR_CONTAINER_INDEX" ]; then
  echo "ERROR: training-operator container not found"
  exit 1
fi

if ! kubectl get deployment training-operator -n kubeflow -o json | \
  jq -e --argjson index "$TRAINING_OPERATOR_CONTAINER_INDEX" --arg arg "$PYTORCH_INIT_TEMPLATE_ARG" \
    '(.spec.template.spec.containers[$index].args // []) | index($arg)' >/dev/null; then
  if kubectl get deployment training-operator -n kubeflow -o json | \
    jq -e --argjson index "$TRAINING_OPERATOR_CONTAINER_INDEX" \
      '.spec.template.spec.containers[$index] | has("args")' >/dev/null; then
    ARGS_PATCH=$(
      jq -n \
        --arg path "/spec/template/spec/containers/${TRAINING_OPERATOR_CONTAINER_INDEX}/args/-" \
        --arg arg "$PYTORCH_INIT_TEMPLATE_ARG" \
        '[{"op": "add", "path": $path, "value": $arg}]'
    )
  else
    ARGS_PATCH=$(
      jq -n \
        --arg path "/spec/template/spec/containers/${TRAINING_OPERATOR_CONTAINER_INDEX}/args" \
        --arg arg "$PYTORCH_INIT_TEMPLATE_ARG" \
        '[{"op": "add", "path": $path, "value": [$arg]}]'
    )
  fi

  kubectl patch deployment training-operator -n kubeflow --type=json -p "$ARGS_PATCH"
fi

kubectl wait --for=condition=Available deployment/training-operator -n kubeflow --timeout=180s
kubectl get deployment -n kubeflow training-operator
kubectl get pods -n kubeflow -l app=training-operator
kubectl get crd | grep -E 'tfjobs.kubeflow.org|pytorchjobs.kubeflow.org'
