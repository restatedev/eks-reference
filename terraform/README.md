# Terraform and OpenTofu deployment

This directory installs the reference stack on an **existing EKS cluster** in
two ordered stages. It supports Terraform 1.5+ or OpenTofu; replace `terraform`
with `tofu` in the examples when using OpenTofu.

Before continuing, complete the repository's
[prerequisite checklist](../docs/01-prerequisites.md#deployment-checklist). These
modules do not create an EKS cluster, VPC, worker nodes, cluster access, or CNI
NetworkPolicy enforcement.

## What Terraform manages

```text
01-foundation
  ├─ dedicated S3 snapshot bucket and security controls
  ├─ EKS IAM OIDC provider lookup (creation is opt-in)
  ├─ snapshot IAM policy, role, trust, and attachment
  ├─ restate-operator and restate-apps namespaces
  ├─ restate-apps NetworkPolicy
  ├─ restate-gp3 StorageClass
  └─ Restate operator Helm release and CRDs

02-restate
  ├─ RestateCluster/restate
  └─ optional RestateDeployment/service
```

The two stages have separate state and must be applied in order.

## Why there are two stages

The Kubernetes provider resolves a `kubernetes_manifest` custom resource
against the live cluster schema during **plan**. The Restate custom-resource
definitions are installed by the operator Helm chart in stage 01. A single
root module could not plan the custom resources on a fresh cluster because
their schemas would not exist yet.

Stage 02 therefore starts only after stage 01 has installed the CRDs:

```text
stage 01 apply ──► CRDs exist in EKS ──► stage 02 plan/apply
```

## Canonical manifests

The Terraform modules consume the files under `../resources/` directly:

- YAML is loaded with `file()` and `yamldecode()`;
- `REPLACE_ME_*` values are replaced in memory from Terraform variables;
- the IAM policy JSON is loaded and its bucket placeholder replaced;
- the operator receives the same Helm values file as the manual runbook.

Do not maintain a second copy of a Kubernetes manifest in HCL. A change under
`resources/` appears in the next plan of the stage that consumes it.

The cluster manifest intentionally uses nested `replace()` calls rather than
`templatefile()`. `file()` leaves Kubernetes expressions such as
`$(POD_NAMESPACE)` untouched; `templatefile()` would introduce a second
interpolation language and make manifest content vulnerable to accidental
Terraform template parsing.

Some AWS-specific resources have no canonical YAML equivalent and live in
stage 01 HCL: the bucket controls, OIDC lookup/creation, and IRSA trust role.

## Inputs

Both stages read the same `terraform.tfvars` and declare the same input set.

| Variable | Required | Default | Meaning |
|---|:---:|---|---|
| `cluster_name` | ✓ | — | Existing EKS cluster; maximum 46 characters because it is embedded in the IAM role name |
| `region` | ✓ | — | EKS and snapshot-bucket AWS region |
| `snapshots_bucket` | ✓ | — | Globally unique bucket name dedicated to this Restate cluster |
| `service_image` | — | `""` | SDK service image; empty skips `RestateDeployment/service` |
| `create_oidc_provider` | — | `false` | Create the cluster IAM OIDC provider instead of looking it up |

## Authentication and authorization

The AWS provider uses ambient credentials. The Kubernetes and Helm providers
call `aws eks get-token`, so no kubeconfig file is required by Terraform.

The identity still needs access on both planes:

- AWS: `eks:DescribeCluster` plus the required S3, IAM, and OIDC read/write
  operations;
- Kubernetes: API endpoint reachability and authorization to manage namespaces,
  a cluster-scoped StorageClass, NetworkPolicies, the Helm release, and Restate
  custom resources.

Passing `aws sts get-caller-identity` proves authentication only. It does not
prove EKS access or Kubernetes RBAC.

## OIDC provider behavior

IRSA uses one IAM OIDC provider per EKS cluster. Stage 01 looks up the existing
provider by default because many clusters already created it for the EBS CSI
driver or another workload.

For a genuinely fresh cluster without a provider:

```hcl
create_oidc_provider = true
```

Only enable creation after confirming the provider is absent. IAM refuses a
second provider for the same issuer.

## Quick start

From the repository root:

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit the file and set `cluster_name`, `region`, and `snapshots_bucket`. Leave
`service_image` empty for the first cluster-only deployment.

### 1. Initialize and plan stage 01

```bash
terraform -chdir=terraform/01-foundation init
terraform -chdir=terraform/01-foundation validate
terraform -chdir=terraform/01-foundation plan \
  -var-file=../terraform.tfvars \
  -out=foundation.tfplan
```

Review the plan carefully. It contains cluster-scoped and AWS resources.
Confirm in particular:

- the EKS cluster and region;
- whether the OIDC provider is read or created;
- the bucket name;
- the IAM role and policy names;
- the `restate-gp3` StorageClass;
- the operator namespace and Helm release.

Apply the reviewed plan:

```bash
terraform -chdir=terraform/01-foundation apply foundation.tfplan
```

Confirm the operator and CRDs before proceeding:

```bash
kubectl -n restate-operator get deployment,pods
kubectl get crd restateclusters.restate.dev restatedeployments.restate.dev
```

### 2. Initialize and plan stage 02

```bash
terraform -chdir=terraform/02-restate init
terraform -chdir=terraform/02-restate validate
terraform -chdir=terraform/02-restate plan \
  -var-file=../terraform.tfvars \
  -out=restate.tfplan
```

Stage 02 re-derives the snapshot role as
`<cluster_name>-restate-snapshots`. The lookup fails during planning when stage
01 did not create that role.

Apply the reviewed plan:

```bash
terraform -chdir=terraform/02-restate apply restate.tfplan
```

The apply waits up to 15 minutes for `RestateCluster/restate` to report
`Ready=True`.

### 3. Verify the deployment

Terraform returning successfully is not the end-to-end snapshot test:

```bash
kubectl -n restate get pods,pvc -o wide
kubectl -n restate exec restate-0 -- restatectl status
kubectl -n restate exec restate-0 -- \
  restatectl snapshots create-snapshot
aws s3 ls "s3://<snapshots_bucket>/restate/snapshots/" --recursive | head
```

Use the [manual runbook completion checklist](../docs/02-runbook.md#completion-checklist)
and [Operations guide](../docs/05-operations.md) for the rest of the health
checks.

## Deploy the example SDK service

Set an immutable SDK service image in `terraform.tfvars`:

```hcl
service_image = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/service:v1"
```

Plan and apply stage 02 again. Terraform creates
`RestateDeployment/service` only while `service_image` is non-empty.

```bash
terraform -chdir=terraform/02-restate plan \
  -var-file=../terraform.tfvars
terraform -chdir=terraform/02-restate apply \
  -var-file=../terraform.tfvars
```

Read [Deploying SDK services](../docs/03-deploying-services.md) before using the
skeleton for a production application or rolling out a second version.

## Outputs

Stage 01 exposes:

| Output | Meaning |
|---|---|
| `snapshots_bucket` | Created snapshot bucket |
| `snapshots_role_arn` | IRSA role annotated onto the Restate ServiceAccount |
| `oidc_provider_arn` | Looked-up or created cluster OIDC provider |

Stage 02 exposes:

| Output | Meaning |
|---|---|
| `restate_cluster_name` | Restate custom-resource and generated namespace name |
| `port_forward_hint` | Command for local ingress and admin access |

Inspect them with `terraform -chdir=<stage> output`.

## State and reproducibility

Both roots default to local state. That is suitable only for a scratch
environment. For shared or durable environments, configure an encrypted,
locking remote backend separately in each `versions.tf` before the first apply.

The `.terraform.lock.hcl` files are git-ignored in this reference repository
because Terraform and OpenTofu resolve different provider registries and
builds. After standardizing on one tool in a fork, generate and commit the lock
file for each root.

The last validated provider set is:

| Provider | Version |
|---|---:|
| AWS | 6.62.0 |
| Kubernetes | 2.38.0 |
| Helm | 3.2.0 |
| TLS | 4.3.0 |

Review plans after any provider selection change.

## Existing resources and migration

Terraform does not automatically adopt resources created by the manual
runbook. A first apply fails when a managed object—such as a namespace,
`restate-gp3` StorageClass, Helm release, bucket, policy, or role—already exists
outside the stage state.

Choose one approach:

1. use Terraform for a clean installation;
2. import every existing resource into the correct stage and review the first
   plan carefully;
3. continue managing an existing manual installation through its original
   delivery system.

Do not delete working resources just to get a clean Terraform apply, especially
the Restate cluster, PVs, snapshot bucket, or cluster OIDC provider.

## Common failures

| Symptom | Likely cause |
|---|---|
| OIDC data lookup fails | Cluster has no IAM OIDC provider; create it or set `create_oidc_provider=true` |
| OIDC create reports `EntityAlreadyExists` | Provider already exists; keep the default lookup mode |
| Kubernetes provider is unauthorized | AWS identity lacks EKS access entry/`aws-auth` mapping or Kubernetes RBAC |
| Stage 02 cannot resolve Restate kinds | Stage 01 did not install the operator CRDs in this cluster |
| Snapshot role lookup fails | Stage 01 was not applied with the same `cluster_name` |
| Restate pods stay Pending | Capacity, anti-affinity, taint, EBS CSI, or Availability Zone issue |
| Stage 02 times out waiting for Ready | Inspect the RestateCluster, pods, and operator logs; see the Operations guide |

## Destroy

Destroy in reverse stage order:

```bash
terraform -chdir=terraform/02-restate plan \
  -destroy -var-file=../terraform.tfvars
terraform -chdir=terraform/02-restate destroy \
  -var-file=../terraform.tfvars

terraform -chdir=terraform/01-foundation plan \
  -destroy -var-file=../terraform.tfvars
terraform -chdir=terraform/01-foundation destroy \
  -var-file=../terraform.tfvars
```

Before confirming either destroy:

- stop new traffic and verify a current snapshot;
- allow `RestateDeployment` revisions to drain—their finalizer can make destroy
  appear paused;
- understand that deleting `RestateCluster/restate` deletes the operator-owned
  namespace and PVCs;
- record the PV-to-EBS volume mapping; the `Retain` policy preserves the PVs but
  does not reattach them automatically;
- expect the non-empty S3 bucket to refuse deletion because `force_destroy` is
  false.

If stage 01 created the IAM OIDC provider, destroying it breaks every IRSA role
that trusts that cluster issuer, including unrelated workloads. When the EKS
cluster is staying, preserve the provider before stage-01 destroy:

```bash
terraform -chdir=terraform/01-foundation state rm \
  'aws_iam_openid_connect_provider.this[0]'
```

Removing a resource from state transfers responsibility; it does not delete
the AWS provider. Record that ownership decision. The broader teardown and data
safety checklist is in
[Operations and troubleshooting](../docs/05-operations.md#teardown-checklist).
