# Prerequisites

What must exist before running the [runbook](01-runbook.md).

## EKS cluster

- **aws-ebs-csi-driver** addon installed — the gp3 StorageClass
  ([`resources/03-gp3-storageclass.yaml`](../resources/03-gp3-storageclass.yaml))
  provisions through it.
- **3 nodes** with ≥24 allocatable vCPU and ≥50 Gi allocatable memory each,
  ideally spread across 3 AZs. `m7i.8xlarge` fits comfortably; `c7i.8xlarge`
  (64 GiB) fits but leaves little memory headroom. Hard pod anti-affinity in
  the cluster spec puts exactly one restate pod per node, so fewer than 3
  eligible nodes means pods stay Pending.
- Restate's data must live on **persistent EBS volumes** that survive node
  replacement — don't be tempted by instance-store (`*d`) instance types for
  the restate nodes. With Karpenter, enforce it with a requirement
  `karpenter.k8s.aws/instance-local-nvme: DoesNotExist` (this is what Restate
  Cloud does).
- Optional but recommended: **VPC CNI network policy enforcement**
  (`enableNetworkPolicy: true` on the vpc-cni addon). The operator creates
  deny-all-by-default NetworkPolicies around the cluster; without an enforcing
  CNI they are inert — everything still works, just without isolation.

## AWS

- An **S3 bucket** for partition snapshots. Required for a replicated cluster:
  snapshots let trimmed-log nodes and replacement pods bootstrap from S3
  instead of replaying the whole log. Create it with public access blocked and
  SSL enforced; default SSE-S3 encryption is fine, and no lifecycle rules are
  needed — Restate keeps a bounded number of snapshots per partition
  (`NUM_RETAINED`).
- Permissions to create an IAM policy and role, and to associate an OIDC
  provider with the cluster (for IRSA).

## Toolchain

- `aws` — AWS CLI v2 (auth, IAM, S3; kubeconfig uses `aws eks get-token` as an
  exec plugin, no separate authenticator binary needed)
- `eksctl` — OIDC provider / IRSA role plumbing
- `kubectl`
- `helm` — installs the operator chart
- `jq`
- `restatectl` — cluster administration (status, logs; manual provisioning
  fallback). Ships inside the restate image, so the runbook runs it via
  `kubectl exec` and no local install is required; for a local copy:

  ```bash
  npm install -g @restatedev/restatectl
  ```

- `restate` (optional) — the service-level CLI. Every runbook step works
  without it by curling the admin API (port 9070) directly; install it with:

  ```bash
  npm install -g @restatedev/restate
  ```

## Placeholders

Grep for **`REPLACE_ME`** under `resources/` before applying anything:

| Placeholder | Where | Meaning |
|---|---|---|
| `REPLACE_ME_SNAPSHOTS_BUCKET` | `01-restate-snapshots-iam-policy.json`, `04-restate-cluster.yaml` | the snapshots S3 bucket name |
| `REPLACE_ME_AWS_REGION` | `04-restate-cluster.yaml` | region for the AWS SDK (S3 snapshots) — explicit so pods don't depend on IMDS reachability |
| `REPLACE_ME_ACCOUNT` | `04-restate-cluster.yaml` | AWS account id in the IRSA role ARN |
| `REPLACE_ME_SERVICE_IMAGE` | `05-restate-compute.yaml` | the SDK service container image |
| `REPLACE_ME_EKS_CLUSTER_NAME` | `02-restate-operator.values.yaml` (commented) | only for the Pod Identity alternative |
