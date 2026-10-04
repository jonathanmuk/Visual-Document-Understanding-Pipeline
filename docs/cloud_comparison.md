# Azure and Google Cloud, Side by Side

The system is the same on both clouds: the same images, the same queue, the same
autoscaling rules, the same network rules. Only the parts that touch the cloud
itself differ. This page lists every one of those differences, so you know what
changes if you move from one to the other.

The two folders `k8s/aks/` and `k8s/gke/` render the same 30 objects with the
same names; CI checks this on every push. Apart from the registry addresses,
they differ in exactly three places, all covered below: how the GPU pods find
their machines, the tolerations for the GPU machines' taints, and the internal
load balancer annotation.

## What is identical

- The API, the worker, the reaper, the MCP server, Redis, and vLLM, with the
  same settings (`kustomization.yml`'s `configMapGenerator` block is identical).
- KEDA scaling on the Redis queues, vLLM's waiting requests, business-hours warm
  starts, and the API's CPU.
- The network rules, the pod security settings, and every container running as
  an ordinary user on a read-only disk.
- Prometheus, the alert rules, and the Grafana dashboard (except its GPU panel
  on Google Cloud; see below).

## What differs

| Topic | Azure (AKS) | Google Cloud (GKE) | Why it matters |
| :--- | :--- | :--- | :--- |
| Command line | `az` | `gcloud` | Different tools, same steps. |
| Image registry | Azure Container Registry, `<name>.azurecr.io` | Artifact Registry, `<region>-docker.pkg.dev/<project>/<repo>` | Set once in each `kustomization.yml`. |
| Building images | `az acr build` builds inside Azure; no local Docker needed | `docker build` and `docker push` from your computer | The worker image is about 8.7 GB, so pushing it from a slow connection takes a long time on Google Cloud. |
| Cluster shape | One cluster, pools placed by Azure | One zonal cluster in the zone that has both GPU types | On GKE, a regional cluster copies each pool into three zones and counts nodes per zone. The guide uses a zonal cluster so counts are literal. |
| Network rules engine | Azure CNI powered by Cilium (`--network-dataplane cilium`) | Dataplane V2 (`--enable-dataplane-v2`, only at creation) | Without one, the network rules are ignored. |
| GPU drivers | `--gpu-driver none` on the pools, then the NVIDIA GPU Operator from Helm (`k8s/aks/infra/gpu-operator-values.yaml`) | `gpu-driver-version=default` on the pools; GKE installs the driver and device plugin | One more install step on Azure. |
| A100 machine | `Standard_NC24ads_A100_v4`: 24 vCPU, 220 GiB, one A100 80 GB | `a2-ultragpu-1g`: 12 vCPU, 170 GB, one A100 80 GB | |
| T4 machine | `Standard_NC16as_T4_v3`: 16 vCPU, 110 GiB, one T4 16 GB | `n1-standard-4` (4 vCPU, 15 GB) with one T4 attached | Azure's T4 size is much bigger; GKE attaches the GPU to a general machine. |
| How GPU pods find their pool | label `kubernetes.azure.com/agentpool` | label `cloud.google.com/gke-nodepool` | Both are set by the cloud on every node. |
| GPU taint the pods tolerate | our own: `sku=gpunpa100`, `sku=gpunpt4` | GKE's own: `nvidia.com/gpu=present` | GKE taints GPU machines itself. |
| Shared disk for model weights | Azure Blob storage (`azureblob-fuse-premium`), 300 GiB | Filestore (`standard-rwx`), 1 TiB minimum | Filestore needs its API turned on and is billed for the full 1 TiB. |
| GPU metrics | The GPU Operator's exporter feeds the cluster's Prometheus; the dashboard shows GPU use | GKE sends them to Google Cloud Monitoring | The dashboard's GPU panel is empty on GKE. |
| Internal load balancer | `service.beta.kubernetes.io/azure-load-balancer-internal: "true"` | `networking.gke.io/load-balancer-type: "Internal"` | Both give a private address only. |
| Front door with keys and a rate limit | Azure API Management in internal mode, with `k8s/aks/networking/apim-policy.xml` | Not chosen yet; the API stays private | See the Google guide, section 12. |

## Where each difference lives

```text
k8s/
  aks/                               Azure
    kustomization.yml                registry addresses, settings (identical to GKE)
    apps/
      deployment-worker.yml          GPU pool selector and taint (agentpool, sku=gpunpt4)
      deployment-vlm.yml             GPU pool selector and taint (agentpool, sku=gpunpa100)
      deployment-mcp.yml             internal load balancer annotation
      deployment-api.yml, deployment-reaper.yml, redis-deployment.yml, keda-scaler.yml
    networking/
      service.yml                    internal load balancer annotation
      network-policies.yml           identical to GKE
      apim-policy.xml                Azure only
    observability/                   identical to GKE
    infra/
      gpu-operator-values.yaml       Azure only
      provisioning/pvc.yaml          Blob storage, 300 GiB
      provisioning/ingest-job.yaml   identical to GKE
  gke/                               Google Cloud, the same layout
    apps/deployment-worker.yml       gke-nodepool selector, nvidia.com/gpu toleration
    apps/deployment-vlm.yml          the same
    infra/provisioning/pvc.yaml      Filestore, 1 TiB
    (no gpu-operator-values.yaml, no apim-policy.xml)
```

## The deployment guides

- [Deploying on Azure (AKS)](aks_deployment.md)
- [Deploying on Google Cloud (GKE)](gke_deployment.md)
