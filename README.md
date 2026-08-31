# Replicated Restate on EKS via the restate-operator

Configuration for running a **3-node replicated Restate cluster** on EKS with the
[restate-operator](https://github.com/restatedev/restate-operator), with the SDK
services (compute) in a **separate namespace**. Sizing/tuning is translated from
the Restate Cloud profile **`3-node.xlarge-vqueues`** (3 × 24 CPU / 50 GiB, 48
partitions, 1 TiB gp3 per node, high-throughput cell tuning with vqueues
enabled).

**Start here → [`docs/00-architecture.md`](docs/00-architecture.md)** for what
you're deploying, then the [runbook](docs/02-runbook.md) to deploy it.

## Docs

| Doc | What's in it |
|---|---|
| [`docs/00-architecture.md`](docs/00-architecture.md) | what the operator materializes, cross-namespace networking, metadata bootstrap, IAM options |
| [`docs/01-prerequisites.md`](docs/01-prerequisites.md) | what the EKS cluster and AWS account need; toolchain; the `REPLACE_ME` placeholder table |
| [`docs/02-runbook.md`](docs/02-runbook.md) | step-by-step: apply `resources/` in numeric order, verify each step |
| [`docs/03-deploying-services.md`](docs/03-deploying-services.md) | deploying SDK services: per-revision versioning, draining, rollback, the knobs |
| [`docs/04-profile-fidelity.md`](docs/04-profile-fidelity.md) | what was kept / moved / dropped relative to the cloud profile — read before changing the cluster manifest |

## Resources (apply in order)

| Resource | Kind | Applied with |
|---|---|---|
| [`resources/00-namespaces.yaml`](resources/00-namespaces.yaml) | Namespaces `restate-operator`, `restate-apps` | `kubectl apply` |
| [`resources/01-restate-snapshots-iam-policy.json`](resources/01-restate-snapshots-iam-policy.json) | IAM policy for the snapshots bucket | `aws iam create-policy` + `eksctl` (runbook step 2) |
| [`resources/02-restate-operator.values.yaml`](resources/02-restate-operator.values.yaml) | Helm values for the operator chart | `helm upgrade --install … -f` |
| [`resources/03-gp3-storageclass.yaml`](resources/03-gp3-storageclass.yaml) | gp3 StorageClass (EKS only ships gp2) | `kubectl apply` |
| [`resources/04-restate-cluster.yaml`](resources/04-restate-cluster.yaml) | the `RestateCluster` — the operator turns it into namespace `restate`, StatefulSet `restate-0..2`, Service `restate-cluster`, NetworkPolicies | `kubectl apply` |
| [`resources/05-restate-compute.yaml`](resources/05-restate-compute.yaml) | `RestateDeployment` skeleton in `restate-apps` (versioned ReplicaSets, auto-registration, drain-before-scale-down) | `kubectl apply` |

Grep for **`REPLACE_ME`** under `resources/` before applying: snapshots bucket
(×2), AWS region, IAM account/role ARN, service image.

## Toolchain

- `aws` — AWS CLI v2 (auth, IAM, S3; kubeconfig uses `aws eks get-token`)
- `eksctl` — OIDC provider / IRSA role plumbing
- `kubectl`
- `helm` — installs the operator chart
- `jq`
- `restatectl` — cluster administration (status, logs; manual provisioning
  fallback). Ships inside the restate image, so the runbook runs it via
  `kubectl exec`; for a local copy: `npm install -g @restatedev/restatectl`
- `restate` (optional) — service-level CLI; the runbook curls the admin API
  instead. Install: `npm install -g @restatedev/restate`
