"""Check that the Kubernetes objects point at each other correctly.

Schema validation (kubeconform) proves each object is well formed on its own. It
cannot tell that a ServiceMonitor selects a Service that does not exist, or that
a NetworkPolicy protects no pod. Those mistakes are silent in a cluster: nothing
errors, the feature just never works. This script renders a Kustomize folder and
checks every reference between objects.

    kubectl kustomize k8s/aks | python tests/manifests/check_references.py
    kubectl kustomize k8s/gke | python tests/manifests/check_references.py

Exit code 0 means every reference resolves.
"""
import sys

import yaml

# Created by hand before deploying (see the deployment guides), so they are not
# in the rendered output. Optional ones may be absent in a working cluster.
HAND_MADE_SECRETS = {
    "ocr-redis-secret": {"password"},
    "ocr-mcp-secret": {"tokens"},
    "ocr-webhook-secret": {"secret"},
    "hf-token-secret": {"token"},
}
# Applied separately, before the stack (docs: model ingestion step).
SEPARATE_PVCS = {"model-weights-pvc"}


def matches(selector, labels):
    return all(labels.get(k) == v for k, v in (selector or {}).items())


def main(stream):
    docs = [d for d in yaml.safe_load_all(stream) if d]
    by_kind = {}
    for d in docs:
        by_kind.setdefault(d["kind"], []).append(d)
    deployments = by_kind.get("Deployment", [])
    services = by_kind.get("Service", [])
    pod_labels = {d["metadata"]["name"]: d["spec"]["template"]["metadata"].get("labels", {}) for d in deployments}
    configmaps = {d["metadata"]["name"] for d in by_kind.get("ConfigMap", [])}
    pvcs = {d["metadata"]["name"] for d in by_kind.get("PersistentVolumeClaim", [])} | SEPARATE_PVCS
    problems, checked = [], 0

    for s in services:
        checked += 1
        name, sel = s["metadata"]["name"], s["spec"].get("selector")
        if sel and not any(matches(sel, labels) for labels in pod_labels.values()):
            problems.append(f"Service {name} selects {sel}, which no Deployment's pods carry")

    for m in by_kind.get("ServiceMonitor", []):
        checked += 1
        name, sel = m["metadata"]["name"], m["spec"]["selector"].get("matchLabels", {})
        found = [s for s in services if matches(sel, s["metadata"].get("labels", {}))]
        if not found:
            problems.append(f"ServiceMonitor {name} selects Services labelled {sel}; no Service has those labels")
        for ep in m["spec"].get("endpoints", []):
            for s in found:
                if ep.get("port") not in [p.get("name") for p in s["spec"].get("ports", [])]:
                    problems.append(f"ServiceMonitor {name} scrapes port '{ep.get('port')}', which Service "
                                    f"{s['metadata']['name']} does not name")

    for so in by_kind.get("ScaledObject", []):
        checked += 1
        target = so["spec"]["scaleTargetRef"]["name"]
        if target not in pod_labels:
            problems.append(f"ScaledObject {so['metadata']['name']} scales {target}, which is not a Deployment")
        for t in so["spec"].get("triggers", []):
            ref = (t.get("authenticationRef") or {}).get("name")
            if ref and ref not in {a["metadata"]["name"] for a in by_kind.get("TriggerAuthentication", [])}:
                problems.append(f"ScaledObject {so['metadata']['name']} uses TriggerAuthentication {ref}, which does not exist")

    for np in by_kind.get("NetworkPolicy", []):
        checked += 1
        name, sel = np["metadata"]["name"], np["spec"].get("podSelector", {}).get("matchLabels")
        if sel and not any(matches(sel, labels) for labels in pod_labels.values()):
            problems.append(f"NetworkPolicy {name} protects pods labelled {sel}; none exist")
        for rule in np["spec"].get("ingress", []) + np["spec"].get("egress", []):
            for peer in rule.get("from", []) + rule.get("to", []):
                psel = (peer.get("podSelector") or {}).get("matchLabels")
                if psel and "namespaceSelector" not in peer and not any(matches(psel, l) for l in pod_labels.values()):
                    problems.append(f"NetworkPolicy {name} names peer pods {psel}; none exist")

    for d in deployments + by_kind.get("Job", []):
        spec = d["spec"]["template"]["spec"]
        name = d["metadata"]["name"]
        for vol in spec.get("volumes", []):
            claim = (vol.get("persistentVolumeClaim") or {}).get("claimName")
            if claim and claim not in pvcs:
                problems.append(f"{name} mounts PVC {claim}, which does not exist")
        for c in spec.get("containers", []):
            checked += 1
            for ef in c.get("envFrom", []):
                cm = (ef.get("configMapRef") or {}).get("name")
                if cm and cm not in configmaps:
                    problems.append(f"{name} reads ConfigMap {cm}, which does not exist")
            for env in c.get("env", []):
                ref = (env.get("valueFrom") or {}).get("secretKeyRef")
                if ref:
                    keys = HAND_MADE_SECRETS.get(ref["name"])
                    if keys is None:
                        problems.append(f"{name} reads Secret {ref['name']}, which no guide tells you to create")
                    elif ref["key"] not in keys:
                        problems.append(f"{name} reads key '{ref['key']}' of Secret {ref['name']}; "
                                        f"the guides create it with {sorted(keys)}")

    for p in problems:
        print("FAIL", p)
    print(f"{checked} objects checked, {len(problems)} broken reference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin))
