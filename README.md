# Replicated Restate on EKS via the restate-operator

Configuration for running a **3-node replicated Restate cluster** on EKS with the
[restate-operator](https://github.com/restatedev/restate-operator), with the SDK
services (compute) in a **separate namespace**. Sizing/tuning is translated from
the Restate Cloud profile **`3-node.xlarge`** (3 × 24 CPU / 50 GiB, 48
partitions, 1 TiB gp3 per node, high-throughput cell tuning).

## Layout

- **`k8s/operator/restate-cluster.yaml`** — the `RestateCluster` (the operator
  materializes it into namespace `restate`: StatefulSet `restate-0..2`, headless
  Service `restate-cluster`, NetworkPolicies). Header comment lists what was
  kept from / dropped relative to the cloud profile.
- **`k8s/operator/restate-compute.yaml`** — namespace `restate-apps` + a
  `RestateDeployment` skeleton (versioned ReplicaSets, auto-registration,
  drain-before-scale-down).
- **`k8s/gp3-storageclass.yaml`** — gp3 StorageClass (EKS only ships gp2).
- **`aws/restate-snapshots-policy.json`** — IAM policy for the snapshots bucket.
- **`shell.nix`** — toolchain: `aws`, `eksctl`, `kubectl`, `helm`, `jq`.
  (The `restate` CLI isn't in the shell — the nixpkgs build fails locally; get it
  with `npm install -g @restatedev/restate`, or curl the admin API directly.)

Search for **`REPLACE_ME`** across `k8s/` and `aws/` before applying: snapshots
bucket (×2), IAM account/role ARN, service image.

## Prerequisites

- An EKS cluster with:
  - **aws-ebs-csi-driver** addon (for gp3 volumes),
  - 3 nodes with ≥24 allocatable vCPU and ≥50 Gi allocatable memory each, in 3
    AZs ideally (e.g. `m7i.8xlarge`; hard anti-affinity puts one restate pod per
    node). `c7i.8xlarge` (64 GiB) fits but leaves little memory headroom.
  - Optional but recommended: **VPC CNI network policy enforcement** enabled
    (`enableNetworkPolicy: true` on the vpc-cni addon). The operator creates
    deny-all-by-default NetworkPolicies; without an enforcing CNI they are inert
    (everything still works, just without isolation).
- An S3 bucket for partition snapshots (required for replicated clusters — lets
  nodes bootstrap from S3 instead of replaying the whole log).
- `nix-shell` for the tools.

## Runbook

### 0. Auth + kubeconfig

```bash
aws sts get-caller-identity            # sanity
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"
```

### 1. IAM for snapshots (IRSA)

The operator creates ServiceAccount `restate` in namespace `restate`;
`security.serviceAccountAnnotations` in the manifest binds it to a role:

```bash
# once per cluster
eksctl utils associate-iam-oidc-provider --cluster "$CLUSTER" --region "$REGION" --approve

sed "s/REPLACE_ME_SNAPSHOTS_BUCKET/$BUCKET/" aws/restate-snapshots-policy.json > /tmp/policy.json
aws iam create-policy --policy-name restate-snapshots --policy-document file:///tmp/policy.json

# --role-only: the operator owns the ServiceAccount, we only need the role + trust policy
eksctl create iamserviceaccount --cluster "$CLUSTER" --region "$REGION" \
  --namespace restate --name restate \
  --role-name restate-snapshots \
  --attach-policy-arn "arn:aws:iam::$ACCOUNT:policy/restate-snapshots" \
  --role-only --approve
```

Then fill the role ARN into `restate-cluster.yaml` → `serviceAccountAnnotations`.

*Alternative (what Restate Cloud itself runs):* EKS Pod Identity managed by the
operator — install the [ACK EKS controller](https://github.com/aws-controllers-k8s/eks-controller),
set the operator helm value `awsPodIdentityAssociationCluster=$CLUSTER`, and use
`security.awsPodIdentityAssociationRoleArn` instead of the annotation (see the
comment in the manifest).

### 2. Install the operator

```bash
helm upgrade --install restate-operator \
  oci://ghcr.io/restatedev/restate-operator-helm \
  --version 3.0.1 \
  --namespace restate-operator --create-namespace
```

CRDs ship with the chart and upgrade with it (v3+). Nothing else to install —
no cert-manager.

### 3. Storage class + cluster

```bash
kubectl apply -f k8s/gp3-storageclass.yaml
kubectl apply -f k8s/operator/restate-cluster.yaml

kubectl -n restate get pods -w          # restate-0..2 -> Running/Ready
kubectl -n restate exec restate-0 -- restatectl status   # nodes, logs, partitions
```

Pod 0 auto-provisions the cluster on first boot (48 partitions, `{node: 2}`
replication); pods 1–2 join via the replicated metadata store.

### 4. Compute

Set the image in `k8s/operator/restate-compute.yaml`, then:

```bash
kubectl apply -f k8s/operator/restate-compute.yaml
kubectl -n restate-apps get restatedeployments   # READY + registered
```

The operator registers each revision with the cluster's admin API itself and
labels the pods `allow.restate.dev/restate: "true"`, which the cluster's egress
NetworkPolicy matches — cross-namespace invocation needs no extra config. The
manifest also opens ingress `:8080` and admin `:9070` **into** the cluster from
`restate-apps`.

### 5. Poke it

```bash
kubectl -n restate port-forward svc/restate-cluster 8080:8080 9070:9070 &
curl localhost:9070/services | jq       # admin API (or: restate services list)
curl localhost:8080/MyService/myHandler --json '{}'
```

## Notes on fidelity to `3-node.xlarge`

- Env-var tuning (rocksdb, bifrost, invoker, snapshots cadence, experimental
  flags) is copied 1:1; the image is the profile's pin, `1.7.4`. The
  experimental flags are validated against that image — revisit them on upgrade.
- `default-num-partitions = 48` and `default-replication = { node = 2 }` are set
  in the config TOML instead of env vars (cloud computes them; same effect).
- Dropped: the node-state-control readiness sidecar, request-signing keys via
  Secrets Store CSI, restate-cloud ingress peering, storage accounting. All are
  cloud-control-plane machinery.
- The `cloud.restate.dev/interruptible` toleration from the profile is kept; it
  is inert unless you taint nodes with it.
