KUBERAY_RELEASE_VERSION ?= 1.6.2
KUBERAY_HELM_CHART_REPO ?= https://ray-project.github.io/kuberay-helm/

.PHONY: kuberay-operator/base
kuberay-operator/base:
	KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true ../../scripts/synchronize-ray-manifests.sh

.PHONY: test
test:
	./test.sh ${KF_PROFILE}
