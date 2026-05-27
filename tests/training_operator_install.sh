#!/bin/bash
set -euo pipefail

cd applications/training-operator/upstream
kustomize build overlays/kubeflow | kubectl apply --server-side --force-conflicts -f -
cd -

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

if ! kubectl get deployment training-operator -n kubeflow -o yaml | grep -q -- "--pytorch-init-container-template-file=/etc/restricted-pytorch-init-container/initContainer.yaml"; then
  kubectl patch deployment training-operator -n kubeflow --type=json -p='[
    {
      "op": "add",
      "path": "/spec/template/spec/containers/0/args",
      "value": [
        "--pytorch-init-container-template-file=/etc/restricted-pytorch-init-container/initContainer.yaml"
      ]
    },
    {
      "op": "add",
      "path": "/spec/template/spec/containers/0/volumeMounts/-",
      "value": {
        "name": "restricted-pytorch-init-container",
        "mountPath": "/etc/restricted-pytorch-init-container",
        "readOnly": true
      }
    },
    {
      "op": "add",
      "path": "/spec/template/spec/volumes/-",
      "value": {
        "name": "restricted-pytorch-init-container",
        "configMap": {
          "name": "restricted-pytorch-init-container"
        }
      }
    }
  ]'
fi

kubectl wait --for=condition=Available deployment/training-operator -n kubeflow --timeout=180s
kubectl get deployment -n kubeflow training-operator
kubectl get pods -n kubeflow -l app=training-operator
kubectl get crd | grep -E 'tfjobs.kubeflow.org|pytorchjobs.kubeflow.org'
