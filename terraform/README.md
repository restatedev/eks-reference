# Terraform path

The same stack as [the runbook](../docs/02-runbook.md), as Terraform. Works
with Terraform ≥ 1.5 or OpenTofu. It assumes the same starting point as the
runbook — an existing EKS cluster meeting the
[prerequisites](../docs/01-prerequisites.md) — and does **not** create the
cluster or VPC.

**`../resources/` stays the single source of truth.** These configs don't
duplicate the manifests: they `file()`-read the exact YAML/JSON from
`resources/`, substitute the same `REPLACE_ME_*` placeholders the runbook has
you fill by hand (from Terraform variables instead), and apply the result. An
edit to a file in `resources/` shows up in the next `terraform plan` of
whichever stage consumes it, so the kubectl path and the Terraform path cannot
drift apart. The explanatory comments also live in the YAML — read the
manifests, not just the HCL.

## Why two stages

`kubernetes_manifest` fetches a custom resource's schema from the **live
cluster at plan time**, and the RestateCluster / RestateDeployment CRDs are
installed by the operator helm chart. A single configuration containing both
the chart and the CRs cannot even be planned against a fresh cluster. Two
root modules, applied in order, solve this with official providers only:

| Stage | Replaces runbook | Contains |
|---|---|---|
| [`01-foundation`](01-foundation/) | steps 1–3 (+ the bucket prerequisite) | S3 snapshots bucket, IAM OIDC provider, IRSA policy + role, namespaces + the restate-apps ingress NetworkPolicy, gp3 StorageClass, operator helm release |
| [`02-restate`](02-restate/) | steps 4–5 | the RestateCluster CR (waits for the operator to provision it and the pods to turn Ready), the RestateDeployment CR (skipped while `service_image` is empty) |

The stages share no state: `02-restate` re-derives the IRSA role by its
`<cluster>-restate-snapshots` naming convention (with a plan-time lookup that
fails fast if stage 01 was never applied). Renaming that role means changing
both stages.

## Usage

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # fill in cluster/region/bucket

# stage 1 — AWS side + operator (installs the CRDs)
terraform -chdir=01-foundation init
terraform -chdir=01-foundation apply -var-file=../terraform.tfvars

# stage 2 — the Restate cluster itself (+ compute, once service_image is set)
terraform -chdir=02-restate init
terraform -chdir=02-restate apply -var-file=../terraform.tfvars
```

Auth: the AWS provider uses your ambient credentials; the kubernetes/helm
providers derive cluster access from them via `aws eks get-token` (exec
auth), so there is no kubeconfig to prepare — `aws sts get-caller-identity`
succeeding is the only precondition.

Stage 2's apply returns once the cluster reports the `Ready` condition —
i.e., provisioned, 48 partitions, all three pods up. The runbook's
[verification steps](../docs/02-runbook.md) (restatectl status, the snapshot
smoke test) apply unchanged afterwards.

## Destroy

Reverse order, and read [the reclaim-policy note](../resources/03-gp3-storageclass.yaml)
first:

```bash
terraform -chdir=02-restate destroy -var-file=../terraform.tfvars
terraform -chdir=01-foundation destroy -var-file=../terraform.tfvars
```

- Destroying the RestateDeployment **blocks until it has drained** (the
  operator's finalizer; see [deploying services](../docs/03-deploying-services.md)) —
  that's the graceful path, not a hang.
- Destroying the RestateCluster deletes the operator-created namespace and
  its PVCs, but the EBS volumes survive as `Released` PVs
  (`reclaimPolicy: Retain`) — clean them up explicitly when you mean it.
- The snapshots bucket refuses deletion while non-empty (`force_destroy`
  is false) — empty it deliberately first.

## State

Both stages default to local state files (git-ignored). For anything beyond a
scratch environment, configure a remote backend (e.g. S3) per stage — add a
`backend` block in each `versions.tf`. The `.terraform.lock.hcl` files are
also git-ignored, unusually: Terraform and OpenTofu record different provider
hashes, and this repo doesn't pick a tool for you — generate your own with
`init` (and commit it in your fork if you standardize on one).
