# Deploying on Google Cloud (GKE)

This guide builds the whole system on Google Kubernetes Engine, from an empty
project to documents being read on GPUs. It mirrors the Azure guide
([aks_deployment.md](aks_deployment.md)) step for step; where Google Cloud works
differently, it says so.

**What it costs.** From the moment the GPU machines exist you are paying for
them: an A100 machine costs several US dollars an hour, and the shared disk for
the model weights is billed for its full 1 TiB. Read
[next-steps.md](../next-steps.md) section 11 (cost safety) first, set a budget
alert, and keep the teardown steps in section 14 at hand.

**How it was checked.** The Google-specific commands were checked against
Google's current documentation; they need a real project to run. Everything
from section 7 onwards that is plain Kubernetes was rehearsed end to end on a
local test cluster on 30 September 2026, using the Azure folder. It differs
from `k8s/gke/` only in how the GPU pods find their machines, the load balancer
annotations, and the registry addresses. The outputs shown come from that
rehearsal. Only the two GPU components could
not run there.

## Contents

0. [Before you start](#0-before-you-start)
1. [Sign in and turn on the services](#1-sign-in-and-turn-on-the-services)
2. [Create the registry and the cluster](#2-create-the-registry-and-the-cluster)
3. [Add the four node pools](#3-add-the-four-node-pools)
4. [Check the GPU drivers](#4-check-the-gpu-drivers)
5. [Download the model weights into the cluster](#5-download-the-model-weights-into-the-cluster)
6. [Build and push the container images](#6-build-and-push-the-container-images)
7. [Configure the deployment](#7-configure-the-deployment)
8. [Create the secrets and turn on pod security](#8-create-the-secrets-and-turn-on-pod-security)
9. [Install KEDA and Prometheus, then deploy](#9-install-keda-and-prometheus-then-deploy)
10. [Check that everything works](#10-check-that-everything-works)
11. [Send documents and connect assistants](#11-send-documents-and-connect-assistants)
12. [The front door on Google Cloud](#12-the-front-door-on-google-cloud)
13. [Optional features](#13-optional-features)
14. [Running it day to day](#14-running-it-day-to-day)
15. [When something goes wrong](#15-when-something-goes-wrong)
16. [References](#16-references)

---

## 0. Before you start

**Accounts and quota.** You need a Google Cloud project with a paid (not trial)
billing account and approved GPU quota for both A100 80 GB and T4. If you do not
have that yet, work through [gcp_onboarding.md](gcp_onboarding.md) and
[gcp_gpu_prereqs.md](gcp_gpu_prereqs.md) first. Section 6 of the prerequisites
has you pick **one zone that offers both GPU types**; you need that zone here.
The small test cluster at the end of the prerequisites is unrelated to this one;
delete it if you still have it.

**Tools:** the gcloud CLI (`gcloud version`), kubectl, Helm 3 or 4, openssl, and
Docker Desktop (for building images in section 6).

**Which terminal.** Every command here is written for a Unix shell (bash). On
Windows, use Git Bash or WSL, not PowerShell. Run everything from the
repository folder.

**Set these once per terminal:**

```bash
export PROJECT_ID="<your project ID>"
export REGION="europe-west4"         # the region of your chosen zone
export ZONE="europe-west4-a"         # the zone that has both A100 80 GB and T4
export GKE_CLUSTER_NAME="vdu-gke"
export AR_REPO_NAME="ocr-repository"
export AR_REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO_NAME}"
```

`export NAME="value"` stores a value for this terminal, and `$NAME` reads it
back. Open a new terminal, set them again.

---

## 1. Sign in and turn on the services

```bash
gcloud auth login
gcloud config set project "$PROJECT_ID"
gcloud services enable container.googleapis.com compute.googleapis.com \
  artifactregistry.googleapis.com file.googleapis.com
```

| Line | What it does |
| :--- | :--- |
| `gcloud auth login` | Opens a browser to sign you in. |
| `gcloud config set project ...` | Makes every later command use your project. |
| `gcloud services enable ...` | Turns on the four Google services this uses: Kubernetes Engine, Compute Engine, Artifact Registry (for images), and Filestore (for the shared model disk). The prerequisites turn on the first three; Filestore is the new one. Running it again is harmless. |

---

## 2. Create the registry and the cluster

```bash
# 1. The container registry: where your built images are stored
gcloud artifacts repositories create $AR_REPO_NAME \
  --repository-format=docker \
  --location=$REGION \
  --description="Visual Document Understanding Pipeline images"

# 2. Let Docker push to it
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# 3. The cluster
gcloud container clusters create $GKE_CLUSTER_NAME \
  --zone $ZONE \
  --num-nodes 1 \
  --enable-ip-alias \
  --workload-pool="${PROJECT_ID}.svc.id.goog" \
  --addons=GcpFilestoreCsiDriver \
  --enable-dataplane-v2

# 4. Let kubectl talk to the new cluster
gcloud container clusters get-credentials $GKE_CLUSTER_NAME --zone $ZONE
```

What the cluster options mean:

| Option | Why it is there |
| :--- | :--- |
| `--zone $ZONE` | A zonal cluster, in the one zone that has both GPU types. Every count in this guide then means what it says. |
| `--num-nodes 1` | One small machine for Kubernetes' own system pods. |
| `--addons=GcpFilestoreCsiDriver` | Lets the cluster use Filestore as a shared disk for the model weights (section 5). |
| `--enable-dataplane-v2` | GKE Dataplane V2, which enforces the network rules in `k8s/gke/networking/network-policies.yml`. It can only be chosen when the cluster is created. Without it, the rules are accepted and silently ignored. |
| `--workload-pool=...` | Workload Identity, Google's way for pods to use Google Cloud permissions. Not used by the system today, and cheap to have. |

**Why zonal and not regional.** A regional cluster keeps three copies of the
control plane, which survives a zone outage. But in a regional cluster each node
pool is copied into three zones by default, and node counts are per zone: a pool
asking for one A100 would get three, in zones that may have none. If you want a
regional cluster anyway, create it with `--region $REGION --node-locations $ZONE`,
and add `--region $REGION --node-locations $ZONE` (in place of `--zone $ZONE`) to
every command in section 3.

---

## 3. Add the four node pools

| Pool | Machine | What runs there | Label or taint |
| :--- | :--- | :--- | :--- |
| `gpunpa100` | `a2-ultragpu-1g`, one A100 80 GB | vLLM, the model server | GKE adds the taint `nvidia.com/gpu=present` itself |
| `gpunpt4` | `n1-standard-4` with one T4 | the worker (layout detection) | the same |
| `redisnp` | `n2-highmem-4`, high memory | Redis | label `app=redis-store`, taint `sku=redis` |
| `apinp` | `n2-standard-2` | the API, the reaper, the MCP server | label `app=api-gateway`, taint `sku=api` |

```bash
# A100 pool for vLLM
gcloud container node-pools create gpunpa100 \
  --cluster $GKE_CLUSTER_NAME --zone $ZONE \
  --machine-type a2-ultragpu-1g \
  --accelerator type=nvidia-a100-80gb,count=1,gpu-driver-version=default \
  --num-nodes 1 \
  --enable-autoscaling --min-nodes 0 --max-nodes 4

# T4 pool for the worker
gcloud container node-pools create gpunpt4 \
  --cluster $GKE_CLUSTER_NAME --zone $ZONE \
  --machine-type n1-standard-4 \
  --accelerator type=nvidia-tesla-t4,count=1,gpu-driver-version=default \
  --num-nodes 1 \
  --enable-autoscaling --min-nodes 0 --max-nodes 4

# High-memory pool for Redis
gcloud container node-pools create redisnp \
  --cluster $GKE_CLUSTER_NAME --zone $ZONE \
  --machine-type n2-highmem-4 \
  --num-nodes 1 \
  --enable-autoscaling --min-nodes 1 --max-nodes 3 \
  --node-taints=sku=redis:NoSchedule \
  --node-labels=app=redis-store

# Small CPU pool for the API, the reaper, and the MCP server
gcloud container node-pools create apinp \
  --cluster $GKE_CLUSTER_NAME --zone $ZONE \
  --machine-type n2-standard-2 \
  --num-nodes 1 \
  --enable-autoscaling --min-nodes 1 --max-nodes 5 \
  --node-taints=sku=api:NoSchedule \
  --node-labels=app=api-gateway
```

The options that matter:

| Option | Meaning |
| :--- | :--- |
| `gpu-driver-version=default` | GKE installs and maintains the NVIDIA driver, and the plugin that tells Kubernetes the machine has a GPU. Nothing else to install. |
| `--num-nodes 1` | Start with one machine, so you can check the GPUs in section 4. |
| `--min-nodes 0 --max-nodes 4` | The cluster autoscaler adds GPU machines when pods need them and removes idle ones, down to zero. KEDA (section 9) decides when pods are needed. |
| `--node-taints`, `--node-labels` | Keep everything else off the CPU pools, and let the system's pods find them. |

The manifests find the GPU pools by the label GKE puts on every node,
`cloud.google.com/gke-nodepool=<pool name>`, and tolerate the taint GKE adds to
GPU machines, so the GPU pools need neither option. (There is no need to set
that label by hand: GKE sets it automatically, and the `cloud.google.com/`
prefix is GKE's own.)

Each pool starts with one machine, which you are paying for from now on.

---

## 4. Check the GPU drivers

GKE installs the drivers when a GPU machine starts. Check they are ready:

```bash
kubectl get nodes "-o=custom-columns=NAME:.metadata.name,POOL:.metadata.labels.cloud\.google\.com/gke-nodepool,GPU:.status.allocatable.nvidia\.com/gpu"
```

The `gpunpa100` and `gpunpt4` machines should show `1` in the `GPU` column (it
can take a few minutes after the machine appears). `<none>` for longer than ten
minutes means the driver did not install: `kubectl get pods -n kube-system | grep nvidia`
shows its installer pods and their state.

---

## 5. Download the model weights into the cluster

The two models (PP-DocLayoutV3 for layout, Qwen3.5-4B for reading) are
downloaded once, inside Google Cloud, onto a shared disk that every GPU pod
reads.

**1. Create the shared disk:**

```bash
kubectl apply -f k8s/gke/infra/provisioning/pvc.yaml
kubectl get pvc model-weights-pvc
```

The claim asks for a Filestore share (`standard-rwx`) that many pods can read at
once. Filestore's smallest share is 1 TiB, billed in full whether you fill it or
not. Creating it takes a few minutes; `STATUS` should become `Bound`:

```
NAME                STATUS   VOLUME          CAPACITY   ACCESS MODES   STORAGECLASS   AGE
model-weights-pvc   Bound    pvc-8192a3b1... 1Ti        RWX            standard-rwx   35s
```

If it stays `Pending`, `kubectl describe pvc model-weights-pvc` says why; the
usual cause is the Filestore service not being turned on (section 1).

**2. Only if a model you use is gated or private**, store your Hugging Face
token first. The two default models are public and need none.

```bash
kubectl create secret generic hf-token-secret --from-literal=token="<your Hugging Face token>"
```

**3. Run the download job, follow it, and remove it when done:**

```bash
kubectl apply -f k8s/gke/infra/provisioning/ingest-job.yaml
kubectl logs -f job/model-weight-ingest
kubectl delete job model-weight-ingest
```

Stop following with Ctrl+C once it prints `Ingestion complete` for both models,
then run the `delete` line. The job checks TLS certificates on every download,
and it is the one container that runs as root: Filestore shares are owned by
root, so an ordinary user could not write the weights. It is deleted once done.

---

## 6. Build and push the container images

```bash
docker build -t ${AR_REGISTRY}/ocr-api-rust:latest ./realtime_producer
docker push ${AR_REGISTRY}/ocr-api-rust:latest

docker build -t ${AR_REGISTRY}/ocr-worker-rt:latest ./realtime_consumer
docker push ${AR_REGISTRY}/ocr-worker-rt:latest

docker build -t ${AR_REGISTRY}/ocr-reaper:latest -f realtime_consumer/Dockerfile.reaper ./realtime_consumer
docker push ${AR_REGISTRY}/ocr-reaper:latest

docker build -t ${AR_REGISTRY}/ocr-mcp:latest ./mcp_server
docker push ${AR_REGISTRY}/ocr-mcp:latest

docker build -t ${AR_REGISTRY}/ocr-vlm-qwen:latest ./server
docker push ${AR_REGISTRY}/ocr-vlm-qwen:latest
```

`docker build -t <name> <folder>` builds an image from the folder's Dockerfile
and names it; `docker push` uploads it to your registry.

**Mind the sizes.** The worker image is about 8.7 GB and the vLLM image is also
large. Pushing them from a slow home connection can take hours. If that is your
situation, build them inside Google Cloud instead with Cloud Build (see
[Google's Cloud Build documentation](https://cloud.google.com/build/docs/building/build-containers));
this guide does not walk through it.

Every image runs as an ordinary user (uid 10001; Redis as its own uid 999), and
the manifests mount each container's disk read-only. The worker and vLLM had not
yet run this way on real GPUs when this guide was written. If either fails to
start, its log names the path it could not write to; give it an `emptyDir`
volume at that path (as the manifests already do for `/tmp`) rather than removing
the restrictions.

---

## 7. Configure the deployment

Everything you would change lives in `k8s/gke/kustomization.yml`.

**Your registry (required).** In the `images:` block, each image points at
`us-central1-docker.pkg.dev/<YOUR_PROJECT_ID>/ocr-repository/...`. Replace
`<YOUR_PROJECT_ID>` with your project ID, and `us-central1` with your `$REGION`
if it differs. If you skip this, every pod fails with `ImagePullBackOff`.

**The settings (optional)** are the same as on Azure; the table in
[aks_deployment.md section 7](aks_deployment.md#7-configure-the-deployment)
explains each one. The file lists them in the `configMapGenerator` block.

---

## 8. Create the secrets and turn on pod security

Exactly as on Azure (the reasons are explained in
[aks_deployment.md section 8](aks_deployment.md#8-create-the-secrets-and-turn-on-pod-security)):

```bash
kubectl create secret generic ocr-redis-secret \
  --from-literal=password="$(openssl rand -base64 24)"
kubectl create secret generic ocr-mcp-secret \
  --from-literal=tokens="$(openssl rand -base64 32)"
kubectl create secret generic ocr-webhook-secret \
  --from-literal=secret="$(openssl rand -base64 32)"

kubectl label --overwrite ns default \
  pod-security.kubernetes.io/enforce=baseline \
  pod-security.kubernetes.io/warn=restricted
```

---

## 9. Install KEDA and Prometheus, then deploy

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm upgrade --install keda kedacore/keda --namespace keda --create-namespace

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set grafana.enabled=true \
  --timeout 15m

kubectl apply -k k8s/gke/
```

The Azure guide's section 9 explains each part, including why `--timeout 15m`
is there. `apply` lists the 30 objects it created.

---

## 10. Check that everything works

Every check in [aks_deployment.md section 10](aks_deployment.md#10-check-that-everything-works)
applies here unchanged, with the same expected output: the pods, the
autoscalers, Prometheus collecting from `ocr-api-service` and
`ocr-reaper-metrics`, the five alert rules, the network check printing
`blocked`, Redis's `appendonly yes`, the reaper's queue depths, the Grafana
dashboard, and the "a worker dies" test.

One difference: **GPU metrics.** On Azure, the GPU Operator's exporter feeds
GPU use into the cluster's own Prometheus, and the dashboard shows it. On GKE,
the NVIDIA DCGM metrics go to Google Cloud Monitoring instead (turned on by
default for clusters created on GKE 1.32.1-gke.1357000 or later), where you can
view them in the Google Cloud console. The dashboard's GPU utilisation panel
therefore stays empty on GKE, and the `DCGM_FI_DEV_GPU_UTIL` query returns
nothing. Everything else in the dashboard works.

---

## 11. Send documents and connect assistants

Exactly as on Azure
([aks_deployment.md section 11](aks_deployment.md#11-send-documents-and-connect-assistants)):
`kubectl port-forward svc/ocr-api-service 15000:80` for testing from your
computer (the testing guide's scenario C; stop its compose stack first, since it
uses the same port), the internal load balancers for your
team (`kubectl get svc ocr-api-service ocr-mcp-service`; on GKE they are internal
passthrough load balancers with private addresses in your VPC), and
[mcp_setup.md](mcp_setup.md) for AI assistants.

---

## 12. The front door on Google Cloud

The API and the MCP server have internal load balancers only: private addresses
inside your VPC, never reachable from the internet. People on a VPN or on
machines inside the VPC can use them, and the MCP server still requires its
token. For a team on a private network, that may be all you need.

What the Google setup does not yet have is Azure's equivalent of API Management:
a key per caller and a rate limit in front of the API. Until you add one,
anyone who can reach the private address can send documents, and every document
can start a GPU machine. So:

- keep the API private (the manifests already do), and give access only to
  people you trust with that;
- if you need callers from outside, put a gateway in front that can reach a
  private address, with authentication and a rate limit, and let only its
  address range reach the API's load balancer (uncomment
  `loadBalancerSourceRanges` in `k8s/gke/networking/service.yml`). The MCP
  server's load balancer has the same setting in
  `k8s/gke/apps/deployment-mcp.yml`: set it to the ranges your team connects
  from, unless your gateway publishes the MCP server too.

Google's API Gateway product looks like the natural choice, but its
documentation describes routing requests to backend addresses and does not
document reaching a private address inside a VPC, so this guide does not rely on
it. Choosing the gateway is left to you.

---

## 13. Optional features

Callbacks, reading profiles, multi-token prediction, and keeping source
documents work exactly as on Azure
([aks_deployment.md section 13](aks_deployment.md#13-optional-features)), with
`k8s/gke/kustomization.yml` in place of the Azure one.

---

## 14. Running it day to day

**Costs.** The GPU pools scale down to zero when idle: KEDA removes the worker
and vLLM pods when there is no work outside the warm hours, and the cluster
autoscaler then releases the machines. The warm hours keep one of each running
on weekdays, 8am to 6pm New York time. Change them to your own time zone in
`k8s/gke/apps/keda-scaler.yml` (`timezone`, `start`, `end` in both `cron`
triggers), or delete the two `cron` triggers for no warm hours at all.

If a GPU pool's minimum was ever raised, set it back:

```bash
gcloud container node-pools update gpunpa100 --cluster $GKE_CLUSTER_NAME --zone $ZONE \
  --enable-autoscaling --min-nodes 0 --max-nodes 4
gcloud container node-pools update gpunpt4 --cluster $GKE_CLUSTER_NAME --zone $ZONE \
  --enable-autoscaling --min-nodes 0 --max-nodes 4
```

**Updating the code and reading logs** work as on Azure (rebuild and push the
changed image, then `kubectl rollout restart deploy/<name>`; logs with
`kubectl logs -l app=<name>`).

**Tearing everything down.** Delete the disk claims first: that deletes the
Filestore share and Redis's disk with them. Then the cluster, then the images.

```bash
kubectl delete -k k8s/gke/
kubectl delete pvc --all
gcloud container clusters delete $GKE_CLUSTER_NAME --zone $ZONE --quiet
gcloud artifacts repositories delete $AR_REPO_NAME --location=$REGION --quiet
```

Afterwards, check nothing billable was left behind:

```bash
gcloud filestore instances list
gcloud compute disks list
```

Both should list nothing from this deployment. If the project exists only for
this system, deleting the whole project (`gcloud projects delete $PROJECT_ID`) is
the most thorough option.

---

## 15. When something goes wrong

Most problems are the same as on Azure; see
[aks_deployment.md section 15](aks_deployment.md#15-when-something-goes-wrong).
Specific to Google Cloud:

| What you see | Likely cause | What to do |
| :--- | :--- | :--- |
| `model-weights-pvc` stays `Pending` | The Filestore service is off | `gcloud services enable file.googleapis.com` (section 1). |
| Creating a GPU pool fails with a capacity or quota message | The zone has no free machines of that type right now, or your quota is lower than asked | Try again later, pick another zone that has both GPU types (the prerequisites show how), or request more quota. |
| A GPU pod stays `Pending` although a GPU machine exists | The driver is still installing | Wait up to ten minutes; section 4 shows how to check. |
| The dashboard's GPU panel is empty | Expected on GKE | Section 10. |

---

## 16. References

- [Run GPUs in GKE Standard node pools](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/gpus), including `gpu-driver-version` and the automatic GPU taint
- [About node pools](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/node-pools), including the automatic `cloud.google.com/gke-nodepool` label
- [Regional clusters](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/regional-clusters), including node counts per zone
- [GKE Dataplane V2](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/dataplane-v2)
- [Filestore CSI driver](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/persistent-volumes/filestore-csi-driver)
- [Collect and view DCGM metrics](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/dcgm-metrics)
- [KEDA scalers](https://keda.sh/docs/latest/scalers/) and [vLLM](https://docs.vllm.ai/)
