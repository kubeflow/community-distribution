# End-to-end Testing

**Authors**: Dominik Fleischmann ([@domFleischmann](https://github.com/domFleischmann)), Kimonas
Sotirchos ([@kimwnasptd](https://github.com/kimwnasptd)), and Anna Jung ([@annajung](https://github.com/annajung))

## Background

Previously, the Kubeflow community leveraged prow optional-test-infra for e2e testing with credit from AWS. After the
optional test infrastructure deprecation notice, all WGs moved their test to GitHub Actions as a temporary solution. Due
to resource constraints of GitHub-hosted runners, the Kubeflow community stopped supporting e2e tests as part of the
migration. In partnership with Amazon, a new AWS account has been created with sponsored credits. With the new AWS
account, the Kubeflow community is no longer limited by resource constraints posed by GitHub Actions. To enable the e2e
test for the Manifest repo, this doc proposes a design to set up the infrastructure needed to run the necessary tests.

References

- [Optional Test Infra Deprecation Notice](https://github.com/kubeflow/testing/issues/993)
- [Alternative solution to removal of test on optional-test-infra](https://github.com/kubeflow/testing/issues/1006)

## Goal

Enable the e2e testing for the Manifest repo and leverage it to shorten the manifest testing phase of the Kubeflow
release cycle and to increase quality of the Kubeflow release by ensuring Kubeflow components and dependencies work
correctly together.

## Proposal

After some initial conversations, it has been agreed to create integration tests based on GitHub Actions, which will
spawn an EC2 instance with enough resources to deploy the complete Kubeflow solution and run some end-to-end testing.

## Implementation

Below lists steps the GitHub actions will perform to complete end-to-end testing

- [Create Credentials required by the AWS](#create-credentials-required-by-the-aws)
- [Create an EC2 instance](#create-an-ec2-instance)
- [Install a Kubernetes on the instance](#install-a-kubernetes-on-the-instance)
- [Deploy Kubeflow](#deploy-kubeflow)
- [Run tests](#run-tests)
- [Log and report errors](#log-and-report-errors)
- [Clean up](#clean-up)

### Create credentials required by the AWS

To leverage AWS, two credentials are required:

- `AWS_ACCESS_KEY_ID`: Specifies an AWS access key associated with an IAM user or role.
- `AWS_SECRET_ACCESS_KEY`: Specifies the secret key associated with the access key. This is essentially the "password"
  for the access key.

Both credentials needs to
be [stored as secrets on GitHub](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
and will be accessed in a workflow as environment variables.

```shell
env:
  AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
  AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

### Create an EC2 instance

Access the AWS credentials (stored as GH Secrets) and create an EC2 instance

Using [juju](https://juju.is/) as an orchestration, configure AWS credentials and deploy an EC2 instance with the
following configurations

- Image: Ubuntu Server (latest)
- Type: t3a.xlarge
- Root disk: 80G
- Region: us-east-1 (default)

#### Why juju?

Juju allows easy configuration to various cloud providers. In the future, if there comes a reason to shift to another
infrastructure provider, it would allow us to pivot quickly.

While juju provides more capability, the proposal is to use the tool as config management and a medium to deploy and
connect with EC2 instances.

**Note**: Using GitHub Secrets to store AWS credentials will not allow any forked repositories to access the secrets.

### Install a Kubernetes on the Instance

Install Kubernetes on the EC2 instance where Kubeflow will be deployed and tested

To install Kubernetes, we explored two options and propose to use **KinD**

- [Microk8s](#microk8s)
- [KinD](#kind)

#### KinD

Using KinD, install Kubernetes with the existing KinD configuration managed by the Manifest WG.

```shell
# Install dependencies - docker
sudo apt update
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common tar
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable"
apt-cache policy docker-ce
sudo apt install -y docker-ce
sudo systemctl status docker
sudo usermod -a -G docker ubuntu

# Install dependencies - kubectl
sudo curl -L "https://storage.googleapis.com/kubernetes-release/release/`curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt`/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl
sudo chmod +x /usr/local/bin/kubectl
kubectl version --short --client

# Install KinD
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.17.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# Deploy kubernetes using KinD
cd manifests
kind create cluster --config ./tests/gh-actions/kind-cluster.yaml
```

##### Why KinD?

While many tools can be leveraged to deploy Kubernetes, Manifest WG already leverages KinD to run both core and contrib
component tests. By reusing the tool, we can leverage the existing KinD configuration and keep the similarity between
component and e2e testing.

**Note**: KinD is a subproject of Kubernetes but does not automatically release with a new Kubernetes version and does
not follow the Kubernetes release cadence. More details can be found at
[kind/issue#197](https://github.com/kubernetes-sigs/kind/issues/197).

### Deploy Kubeflow

Deploy Kubeflow, in the same manner, the manifests WG documents.

Copy the manifest repo to the AWS instance and use Kustomize to run the Kubeflow installation. After Kustomize
installation is complete, verify all pods are running.

Manifest installation may result in an infinite while loop; therefore, a time limit of 45mins should be set to ensure
installation exits when a problem occurs with Kubeflow installation.

### Run Tests

Execute integration tests to verify the correct functioning of different features using python scripts and jupyter
notebooks.

As the first iteration, test the Kubeflow integration using the
existing [e2e mnist python script](https://github.com/kubeflow/community-distribution/tree/master/tests/e2e)
and [e2e mnist notebook](https://github.com/kubeflow/pipelines/blob/master/samples/experimental/kubeflow-e2e-mnist/kubeflow-e2e-mnist.ipynb)
.

- [Python script](#python-script)
- [Jupyter notebook](#jupyter-notebook)

Both python and notebook tests the following:

- Kfp and Katib SDK packages (compatibility with other python packages)
- Creation and execution of a pipeline from a user namespace
- Creation and execution of hyperparameter running with Katib from a user namespace
- Creation and execution of distributive training with TFJob from a user namespace
- Creation and execution of inference using KServe from a user namespace

**Note**: The mnist notebook does not test the Kubeflow Notebook resources. In the future, additional verification and
tests should be added to cover various Kubeflow components and features.

#### Python script

Step to run e2e python script from the workflow:

1. Convert e2e mnist notebook to a python script (
   reuse [mnist.py](https://github.com/kubeflow/community-distribution/blob/master/tests/e2e/mnist.py))
2. Run mnist python script outside of the cluster (
   reuse [runner.sh](https://github.com/kubeflow/community-distribution/blob/master/tests/e2e/runner.sh))

#### Jupyter notebook

Step to run e2e notebook from the workflow:

1. Get e2e mnist notebook
    1. To run the existing e2e mnist notebook, modification needs to be made in the last step to wait for the triggered
       run to finish running before executing. Changes proposed are defined below and a pull request will need to be
       made in the future to avoid copying mnist notebook into the manifest directory.

    ```shell
    import numpy as np
    import time
    from PIL import Image
    import requests

    # Pipeline Run should be succeeded.
    run_status = kfp_client.get_run(run_id=run_id).run.status

    if run_status == None:
        print("Waiting for the Run {} to start".format(run_id))
        time.sleep(60)
        run_status = kfp_client.get_run(run_id=run_id).run.status

    while run_status == "Running":
        print("Run {} is in progress".format(run_id))
        time.sleep(60)
        run_status = kfp_client.get_run(run_id=run_id).run.status

    if run_status == "Succeeded":
        print("Run {} has Succeeded\n".format(run_id))

        # Specify the image URL here.
        image_url = "https://raw.githubusercontent.com/kubeflow/katib/master/examples/v1beta1/kubeflow-pipelines/images/9.bmp"
        image = Image.open(requests.get(image_url, stream=True).raw)
        data = np.array(image.convert('L').resize((28, 28))).astype(float).reshape(-1, 28, 28, 1)
        data_formatted = np.array2string(data, separator=",", formatter={"float": lambda x: "%.1f" % x})
        json_request = '{{ "instances" : {} }}'.format(data_formatted)

        # Specify the prediction URL. If you are runing this notebook outside of Kubernetes cluster, you should set the Cluster IP.
        url = "http://{}-predictor-default.{}.svc.cluster.local/v1/models/{}:predict".format(name, namespace, name)

        time.sleep(60)
        response = requests.post(url, data=json_request)

        print("Prediction for the image")
        display(image)
        print(response.json())
    else:
        raise Exception("Run {} failed with status {}\n".format(run_id, kfp_client.get_run(run_id=run_id).run.status))
    ```
2. Move the mnist notebook into the cluster
    ```shell
    kubectl -n kubeflow-user-example-com create configmap <configmap name> --from-file kubeflow-e2e-mnist.ipynb
    ```
3. Create a PodDefault to allow access to Kubeflow pipelines
    ```shell
    apiVersion: kubeflow.org/v1alpha1
    kind: PodDefault
    metadata:
      name: access-ml-pipeline
      namespace: kubeflow-user-example-com
    spec:
      desc: Allow access to Kubeflow Pipelines
      selector:
        matchLabels:
          access-ml-pipeline: "true"
      env:
        - ## this environment variable is automatically read by `kfp.Client()`
          ## this is the default value, but we show it here for clarity
          name: KF_PIPELINES_SA_TOKEN_PATH
          value: /var/run/secrets/kubeflow/pipelines/token
      volumes:
        - name: volume-kf-pipeline-token
          projected:
            sources:
              - serviceAccountToken:
                  path: token
                  expirationSeconds: 7200
                  ## defined by the `TOKEN_REVIEW_AUDIENCE` environment variable on the `ml-pipeline` deployment
                  audience: pipelines.kubeflow.org
      volumeMounts:
        - mountPath: /var/run/secrets/kubeflow/pipelines
          name: volume-kf-pipeline-token
          readOnly: true
    ```
4. Run the notebook programmatically using a Kubernetes resource Job or Notebook
    ```shell
    apiVersion: batch/v1
    kind: Job
    metadata:
      name: test-notebook-job
      namespace: kubeflow-user-example-com
    spec:
      backoffLimit: 1
      activeDeadlineSeconds: 1200
      template:
        metadata:
          labels:
            access-ml-pipeline: "true"
        spec:
          restartPolicy: Never
          initContainers:
          - name: copy-notebook
            image: busybox
            command: ['sh', '-c', 'cp /scripts/* /etc/kubeflow-e2e/']
            volumeMounts:
              - name: e2e-test
                mountPath: /scripts
              - name: kubeflow-e2e
                mountPath: /etc/kubeflow-e2e
          containers:
            - image: kubeflownotebookswg/jupyter-scipy:v1.6.1
              imagePullPolicy: IfNotPresent
              name: execute-notebook
              command:
                - /bin/sh
                - -c
                - |
                  jupyter nbconvert --to notebook --execute /etc/kubeflow-e2e/kubeflow-e2e-mnist.ipynb;
                  x=$(echo $?); curl -fsI -X POST http://localhost:15020/quitquitquit && exit $x;
              volumeMounts:
                - name: kubeflow-e2e
                  mountPath: /etc/kubeflow-e2e
          serviceAccountName: default-editor
          volumes:
            - name: e2e-test
              configMap:
                name: e2e-test
            - name: kubeflow-e2e
              emptyDir: {}
    ```
5. Verify Job succeeded or failed
    ```shell
    kubectl -n kubeflow-user-example-com wait --for=condition=complete --timeout=1200s job/test-notebook-job
    ```

### Log and Report Errors

Report logs generated in the EC2 instance back to GitHub actions for users.

For failures in the workflow steps, generate inspect logs, pod logs, and describe logs. Copy the generated logs back to
the GitHub Actions system and use [actions/upload-artifact@v2](https://github.com/actions/upload-artifact)
to allow users to access the logs when necessary.

**Note**: As default, artifacts are retained for 90 days. The number of retention days is configurable.

### Clean Up

Regardless of the success or failure of the workflow, at the end of the workflow, the EC2 instance is deleted to ensure
there are no resources left behind.

## Debugging

To debug any failed step of the GitHub Actions
workflow, [debugging with ssh](https://github.com/marketplace/actions/debugging-with-ssh)
or other similar tools can be used to ssh into the GitHub system. In the GitHub system, juju can be used to connect to
an AWS EC2 instance.

**Notes**:

- GitHub secrets are limited to the Manifest repo and do not cascade to forked repositories. To debug, users must set up
  their own AWS secrets.
- To debug the AWS EC2 instance without ssh into the GitHub system, you must have access to AWS credentials. Access to
  AWS credentials is limited to [Manifest WG approvers](https://github.com/kubeflow/community-distribution/blob/master/OWNERS).

## Proof of Concept Workflow

The POC code
is [available](https://github.com/DomFleischmann/manifests/blob/aj-dev/.github/workflows/aws_e2e_tests.yaml)
with examples of both [successful](https://github.com/DomFleischmann/manifests/actions/runs/4118561167/jobs/7111228604)
and [failed](https://github.com/DomFleischmann/manifests/actions/runs/4119052861) runs.

The proposed end-to-end workflow has been tested with the following Kubernetes and Kubeflow versions

- 1.22 Kubernetes and [1.6.1 Kubeflow release](https://github.com/kubeflow/community-distribution/releases/tag/v1.6.1) (microk8s)
- 1.24 Kubernetes and main branch of the manifest
  repo ([last commit](https://github.com/DomFleischmann/manifests/commit/8e5714171f1fd5b00f59f436e9ab8cb45a0f30e3)) (
  microk8s)
- 1.25 Kuberentes and main branch of the manifest
  repo ([last commit](https://github.com/DomFleischmann/manifests/commit/8e5714171f1fd5b00f59f436e9ab8cb45a0f30e3)) (
  kind)

### Alternative solutions considered

#### Prow

While there are some existing tests with Prow, those tests were discarded due to them not having been updated in 2 years
and there being a high amount of complexity in these tests. After some investigation, the Manifests Working Group
decided that it would be more work adapting those tests to the current state of manifests than starting from scratch
with lower complexity.

#### Self-hosted runners

Self-hosted runners are not recommended with public repositories due to security concerns with how it behaves on a pull
request made by a forked repository.

#### MicroK8s

Instead of KinD, [microk8s](https://microk8s.io/) was considered as an alternative to install Kubernetes.

Below shows the steps required in the workflow to install microk8s and to install Kubernetes using microk8s. During
the Kubernetes installation, you must enable [dns](https://microk8s.io/docs/addon-dns),
[storage](https://microk8s.io/docs/addon-hostpath-storage), [ingress](https://microk8s.io/docs/addon-ingress),
[loadbalancer](https://microk8s.io/docs/addon-metallb), and [rbac](https://microk8s.io/docs/multi-user).

```shell
# Install microk8s
sudo snap install microk8s --classic --channel ${{ matrix.microk8s }}
sudo apt update
sudo usermod -a -G microk8s ubuntu

# Install dependencies - kubectl
sudo snap alias microk8s.kubectl kubectl

# Deploy kubernetes using microk8s
sudo snap install microk8s --classic --channel 1.24/stable
microk8s enable dns hostpath-storage ingress metallb:10.64.140.43-10.64.140.49 rbac
```

**Note**: microk8s requires IP address pool when enabling dns, address pool of 10.64.140.43-10.64.140.49 is an arbitrary
decision.
