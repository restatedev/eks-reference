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
- Optional but recommended: **VPC CNI network policy enforcement**
  (`enableNetworkPolicy: true` on the vpc-cni addon). The operator creates
  deny-all-by-default NetworkPolicies around the cluster; without an enforcing
  CNI they are inert — everything still works, just without isolation.

## AWS

- An **S3 bucket** for partition snapshots. Required for a replicated cluster:
  snapshots let trimmed-log nodes and replacement pods bootstrap from S3
  instead of replaying the whole log.
- Permissions to create an IAM policy and role, and to associate an OIDC
  provider with the cluster (for IRSA).

## Toolchain

`shell.nix` provides `aws`, `eksctl`, `kubectl`, `helm`, `jq` — enter with
`nix-shell`.

The `restate` CLI is *not* in the shell (the nixpkgs build fails locally).
When you want it: `npm install -g @restatedev/restate`. Everything in the
runbook works without it by curling the admin API (port 9070) directly.

## Placeholders

Grep for **`REPLACE_ME`** under `resources/` before applying anything:

| Placeholder | Where | Meaning |
|---|---|---|
| `REPLACE_ME_SNAPSHOTS_BUCKET` | `01-restate-snapshots-iam-policy.json`, `04-restate-cluster.yaml` | the snapshots S3 bucket name |
| `REPLACE_ME_ACCOUNT` | `04-restate-cluster.yaml` | AWS account id in the IRSA role ARN |
| `REPLACE_ME_SERVICE_IMAGE` | `05-restate-compute.yaml` | the SDK service container image |
| `REPLACE_ME_EKS_CLUSTER_NAME` | `02-restate-operator.values.yaml` (commented) | only for the Pod Identity alternative |
