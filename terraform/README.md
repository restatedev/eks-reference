# Terraform and OpenTofu deployment

This guide is for a cloud engineer installing Restate on an **existing EKS
cluster** with Terraform or OpenTofu. The two required stages create the AWS
and Kubernetes resources needed by the Restate operator and a three-node
Restate cluster. An optional third root demonstrates application delivery in
separate state. The modules do not create EKS infrastructure or public ingress.

If Restate itself is new to you, start with the
[top-level overview](../README.md) for the product and ownership model, then
return here.

The apply is split into two ordered stages because the operator must install
Restate's Kubernetes resource definitions before Terraform can plan a
`RestateCluster`. Stage 01 creates the foundation and operator. Stage 02 creates
the three-node Restate cluster. The independent stage 03 example deploys one
SDK service when an application team chooses Terraform for delivery. If the
prerequisites are already complete, go directly to [Quick start](#quick-start);
the intervening sections explain the plan and ownership boundaries.

The examples use Terraform 1.5+. OpenTofu is also supported; replace
`terraform` with `tofu` in the commands.

Before continuing, complete the repository's
[prerequisite checklist](../docs/01-prerequisites.md#deployment-checklist). These
modules do not create an EKS cluster, VPC, worker nodes, cluster access, or CNI
NetworkPolicy enforcement. They currently support IPv4 EKS clusters only and
fail planning with a clear error when the target reports another IP family.

## What Terraform manages

```text
01-foundation
  ├─ dedicated S3 snapshot bucket and security controls
  ├─ EKS IAM OIDC provider lookup (creation is opt-in)
  ├─ snapshot IAM policy, role, trust, and attachment
  ├─ restate-operator and restate-apps namespaces
  ├─ restate-apps NetworkPolicy
  ├─ restate-gp3 StorageClass
  └─ Restate operator Helm release and CRDs (CRDs are retained on uninstall)

02-restate
  ├─ RestateCluster/restate
  └─ Service-CIDR egress NetworkPolicy (opt-out)

03-services (optional, independent application state)
  └─ RestateDeployment/service and its readiness gate
```

The two cluster stages have separate state and must be applied in order. The
optional service root also has separate state and is applied only after the
cluster is healthy.

The chart installs and upgrades its CRDs, but annotates them with
`helm.sh/resource-policy: keep`. Destroying the Helm release therefore leaves
all three definitions in the cluster until the explicit, dependency-checked
cleanup in [Destroy](#destroy).

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

Keep the files under `resources/` as the canonical Kubernetes manifests rather
than maintaining a second copy in HCL. A change there appears in the next plan
of the stage that consumes it.

The cluster manifest intentionally uses nested `replace()` calls rather than
`templatefile()`. `file()` leaves Kubernetes expressions such as
`$(POD_NAMESPACE)` untouched; `templatefile()` would introduce a second
interpolation language and make manifest content vulnerable to accidental
Terraform template parsing.

Some AWS-specific resources have no canonical YAML equivalent and live in
stage 01 HCL: the bucket controls, OIDC lookup/creation, and IRSA trust role.

## Inputs

Stages 01 and 02 read the same `terraform.tfvars` and declare the same input
set.

| Variable | Required | Default | Meaning |
|---|:---:|---|---|
| `cluster_name` | ✓ | — | Existing EKS cluster; maximum 46 characters because it is embedded in the IAM role name |
| `region` | ✓ | — | EKS and snapshot-bucket AWS region |
| `snapshots_bucket` | ✓ | — | Globally unique bucket name dedicated to this Restate cluster |
| `create_oidc_provider` | — | `false` | Create the cluster IAM OIDC provider instead of looking it up |
| `create_service_cidr_egress_policy` | — | `true` | Apply the Service-CIDR egress policy; required where the CNI enforces NetworkPolicy |

Optional stage 03 also reads `cluster_name` and `region`. It accepts the shared
variable file, but its only additional required input is `service_image`, which
should be an immutable image digest or release tag supplied by the application
pipeline.

## Authentication and authorization

The AWS provider uses ambient credentials. The Kubernetes and Helm providers
call `aws eks get-token`, so no existing kubeconfig file is required by
Terraform. Stage 03's readiness script additionally requires `aws`, `kubectl`,
and `jq`; it creates a temporary kubeconfig with `aws eks update-kubeconfig
--dry-run` and removes it when the check finishes.

The identity still needs access on both planes:

- AWS: `eks:DescribeCluster` plus the required S3, IAM, and OIDC read/write
  operations;
- Kubernetes: API endpoint reachability and authorization to manage namespaces,
  cluster-scoped StorageClasses, CRDs and RBAC, NetworkPolicies, the Helm
  release, and Restate custom resources.

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

Enable creation after confirming the provider is absent. IAM rejects a second
provider for the same issuer.

## Operator chart registry access

Stage 01 fetches the operator as the OCI chart
`oci://ghcr.io/restatedev/restate-operator-helm:3.0.1`. The package is public
and pulls anonymously, so no registry credentials are needed. Note that the
Helm provider fetches the chart during **plan**, not only during apply, so a
registry problem surfaces before anything is created.

A `401` or `403` while locating the chart usually means Helm is presenting a
stale or insufficiently scoped `ghcr.io` credential. See
[Prerequisites: OCI chart registry access](../docs/01-prerequisites.md#oci-chart-registry-access)
for the logout-and-retry path and, for environments that genuinely block
anonymous pulls, the login path. If you do authenticate, keep the login and the
plan/apply in the same shell, and export `HELM_REGISTRY_CONFIG` before both
when using a temporary registry configuration.

## Service-CIDR egress policy

Stage 02 applies `resources/06-restate-service-cidr-egress.yaml` by default,
allowing the Restate pods TCP 9080 into the cluster's Service CIDR. It exists
because the operator opens egress to service **pod IPs** while registering each
revision by its **Service name**, and the EKS VPC CNI evaluates egress before
kube-proxy rewrites the ClusterIP. Without the policy, `RestateDeployment`
registration times out even though the service pods are Ready.

Nothing to configure: the CIDR comes from
`data.aws_eks_cluster.this.kubernetes_network_config[0].service_ipv4_cidr`, so
it always matches the cluster being applied to. On a CNI that evaluates after
DNAT (Calico, Cilium) the policy is unnecessary rather than harmful, and
`create_service_cidr_egress_policy = false` skips it.

This is also the reason IPv4 is an explicit support boundary. An IPv6 EKS
cluster reports `serviceIpv6Cidr` instead, and this reference has not validated
the operator policies, Pod Identity agent path, or VPC CNI IPv6 behavior as one
system. Both cluster stages reject a non-IPv4 target rather than partially
applying it.

The policy lives in the operator-owned namespace, so destroying the
`RestateCluster` removes it too. Its full rationale and the exact scope of the
allowance are in the manifest's header.

## Quick start

From the repository root:

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit the file and set `cluster_name`, `region`, and `snapshots_bucket`. Those
three are the complete required input set for the cluster stages.

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
kubectl get crd \
  restateclusters.restate.dev \
  restatedeployments.restate.dev \
  restatecloudenvironments.restate.dev
```

### 2. Initialize and plan stage 02

Before the first cluster plan, decide whether to keep the validated replicated
metadata store or configure the documented S3 metadata provider. This choice
affects the cluster's durability model and is best made before it stores data;
see [Data durability](../docs/00-architecture.md#data-durability-model). If you
choose S3, update the canonical cluster manifest and validate that configuration
before continuing.

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

The initial apply waits up to 15 minutes for `RestateCluster/restate` to report
`Ready=True`. The resource does not expose `observedGeneration`, so this
condition alone is not an update-rollout gate; use the generation-sensitive
procedure in [Operations](../docs/05-operations.md#upgrade-restate-or-the-operator)
for later pod-template changes.

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

## Optional stage 03: deploy the SDK service example

Stages 01 and 02 deliberately stop at a healthy Restate cluster. SDK services
change at an application's cadence, so keep them in an application-owned
workflow and state. Use `kubectl`, your existing delivery system, or the
independent `terraform/03-services` example.

To use the example, supply an immutable Restate SDK service image and review a
saved plan:

```bash
export TF_VAR_service_image='registry.example/service@sha256:<digest>'

terraform -chdir=terraform/03-services init
terraform -chdir=terraform/03-services validate
terraform -chdir=terraform/03-services plan \
  -var-file=../terraform.tfvars \
  -out=service.tfplan
terraform -chdir=terraform/03-services apply service.tfplan
```

The root substitutes the image into `resources/05-restate-compute.yaml`. After
each manifest change, its script waits until `status.observedGeneration` has
caught up with `metadata.generation` and the current `Ready` condition is
`True`. This prevents a previous revision's `Ready=True` from satisfying an
update. On a timeout, the last condition reason and message are printed; use
the delivery-health guide below to interpret them.

The operator gives each revision an immutable ReplicaSet and Service, registers
it with Restate, and drains superseded revisions after pinned invocations
finish. Keeping application state separate prevents an image release from
sharing the cluster infrastructure's state and blast radius.

Further application-delivery guidance:

- [Deploying SDK services](../docs/03-deploying-services.md) — the lifecycle
  contract, rollout, drain, rollback, and per-symptom troubleshooting;
- [Health signals for delivery tools](../docs/03-deploying-services.md#health-signals-for-delivery-tools)
  — how a rejected revision surfaces in Terraform, Argo CD, and Flux;
- [operator service examples](https://github.com/restatedev/restate-operator/tree/main/examples/services/greeter)
  — upstream `RestateDeployment` manifests, including a Knative variant;
- [Restate on Kubernetes](https://docs.restate.dev/deploy/services/kubernetes)
  — the product documentation for the same model.

Stage 02 provides the cluster side of registration, including the Service-CIDR
egress policy described above, so a service deployed by any supported workflow
can register.

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

Optional stage 03 exposes:

| Output | Meaning |
|---|---|
| `service_name` | Name of the example `RestateDeployment` |
| `ingress_port_forward_hint` | Command for local Restate ingress access; the service invocation path is application-specific |

Inspect them with `terraform -chdir=<stage> output`.

## State and reproducibility

Each root defaults to local state. That is suitable only for a scratch
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

Prefer importing existing resources or continuing with their current delivery
system. Deleting working resources to obtain a clean Terraform apply can put
the Restate cluster, PVs, snapshot bucket, or cluster OIDC provider at risk.

## Common failures

| Symptom | Likely cause |
|---|---|
| Helm reports `401`/`403` or `Error locating chart` for the operator chart | The chart is public—usually a stale or insufficiently scoped `ghcr.io` credential Helm is sending; see [Runbook: if the chart pull fails](../docs/02-runbook.md#if-the-chart-pull-fails-with-401-or-403) |
| OIDC data lookup fails | Cluster has no IAM OIDC provider; create it or set `create_oidc_provider=true` |
| OIDC create reports `EntityAlreadyExists` | Provider already exists; keep the default lookup mode |
| Kubernetes provider is unauthorized | AWS identity lacks EKS access entry/`aws-auth` mapping or Kubernetes RBAC |
| Stage 02 cannot resolve Restate kinds | Stage 01 did not install the operator CRDs in this cluster |
| `RestateDeployment` stays NotReady with Ready service pods | Registration cannot reach the revision's ClusterIP; the Service-CIDR egress policy is missing or was disabled ([architecture](../docs/00-architecture.md#sdk-service-isolation)) |
| Snapshot role lookup fails | Stage 01 was not applied with the same `cluster_name` |
| Restate pods stay Pending | Capacity, anti-affinity, taint, EBS CSI, or Availability Zone issue |
| Stage 02 times out waiting for Ready | Inspect the RestateCluster, pods, and operator logs; see the Operations guide |
| EKS lookup reports that `ipFamily` is not `ipv4` | This reference currently supports IPv4 EKS clusters only; use a validated IPv4 target rather than bypassing the guard |

## Destroy

Teardown has three separate decisions: drain applications through their owning
delivery system, destroy the Restate cluster, then decide which stage-01 AWS
resources transfer to another owner and which are actually deleted. Begin with
those ownership decisions and reviewed plans rather than an unconditional
stage-01 destroy.

Before planning a destroy:

- pause new traffic and create and verify a current snapshot;
- identify which delivery system owns each SDK service;
- record the PV/PVC/AZ/EBS volume mapping before deleting the cluster;
- capture the bucket name while the stage-01 output still exists.

```bash
kubectl -n restate get pvc -o wide
kubectl get pv \
  -o custom-columns='PV:.metadata.name,CLAIM-NS:.spec.claimRef.namespace,CLAIM:.spec.claimRef.name,VOLUME:.spec.csi.volumeHandle,ZONE:.metadata.labels.topology\.kubernetes\.io/zone'
BUCKET="$(terraform -chdir=terraform/01-foundation output -raw snapshots_bucket)"
```

### 1. Destroy optional stage 03, if used

If the example service is in stage-03 state, destroy it from that state first:

```bash
export TF_VAR_service_image='registry.example/service@sha256:<same-digest>'

terraform -chdir=terraform/03-services plan \
  -destroy -var-file=../terraform.tfvars \
  -out=service-destroy.tfplan
terraform -chdir=terraform/03-services apply service-destroy.tfplan
```

The operator's finalizer can keep this apply running while pinned invocations
drain. If another tool owns the services, remove them through that tool. For a
manual installation, use:

```bash
kubectl -n restate-apps delete restatedeployment --all \
  --wait=true --timeout=15m
```

If service deletion times out, inspect the pinned invocations and continue
waiting; allow the finalizer to complete before destroying the cluster.

Confirm that no application-owned `RestateDeployment` remains before
continuing. An empty result is expected:

```bash
kubectl get restatedeployments.restate.dev --all-namespaces
```

### 2. Destroy stage 02

Create and apply one saved, reviewed destroy plan:

```bash
terraform -chdir=terraform/02-restate plan \
  -destroy -var-file=../terraform.tfvars \
  -out=restate-destroy.tfplan
terraform -chdir=terraform/02-restate apply restate-destroy.tfplan
```

This deletes `RestateCluster/restate`, its namespace, and its PVCs. Confirm the
PVs are `Released` and record their EBS handles again before proceeding:

```bash
kubectl get pv \
  -o custom-columns='PV:.metadata.name,STATUS:.status.phase,VOLUME:.spec.csi.volumeHandle,SIZE:.spec.capacity.storage'
```

### 3. Decide stage-01 ownership before planning its destroy

Stage 01 may own a cluster-wide OIDC provider. If
`create_oidc_provider = true` and the EKS cluster is staying, transfer it out of
this state **before** the destroy plan. Otherwise Terraform will delete it and
break every IRSA role that trusts the issuer, including unrelated workloads:

```bash
terraform -chdir=terraform/01-foundation state list \
  | grep '^aws_iam_openid_connect_provider\.this'

terraform -chdir=terraform/01-foundation state rm \
  'aws_iam_openid_connect_provider.this[0]'
```

When `create_oidc_provider = false`, the provider is only a data source and
there is no managed OIDC resource to remove from state.

Choose one bucket outcome:

- **Keep the bucket and snapshots.** Transfer the bucket and both of its
  security controls together. Removing only the bucket from state would let the
  destroy remove the public-access block and HTTPS-only policy from the retained
  data.

  ```bash
  terraform -chdir=terraform/01-foundation state rm \
    aws_s3_bucket_policy.snapshots \
    aws_s3_bucket_public_access_block.snapshots \
    aws_s3_bucket.snapshots
  ```

- **Delete the bucket and snapshots.** This is irreversible. Empty it only
  after an explicit data-retention decision; `force_destroy` is false, so a
  non-empty bucket correctly makes the later apply fail.

  ```bash
  aws s3 rm "s3://$BUCKET" --recursive
  ```

The snapshot IAM role and policy are separate from the bucket decision. Stage
01 deletes them by default. To preserve them for an intentional reuse, transfer
all three state objects together. The policy remains scoped to this exact
bucket, so retain the bucket too or update the policy before reusing the role:

```bash
terraform -chdir=terraform/01-foundation state rm \
  aws_iam_role_policy_attachment.snapshots \
  aws_iam_role.snapshots \
  aws_iam_policy.snapshots
```

Removing an object from state transfers responsibility; it does not delete or
continue managing the AWS object. Record the new owner for every transfer.

### 4. Destroy stage 01

Only after those decisions, create and apply the saved stage-01 destroy plan:

```bash
terraform -chdir=terraform/01-foundation plan \
  -destroy -var-file=../terraform.tfvars \
  -out=foundation-destroy.tfplan
terraform -chdir=terraform/01-foundation apply foundation-destroy.tfplan
```

The Helm chart deliberately retains its three CRDs on uninstall. After proving
that no other operator installation or custom resource relies on them, remove
them explicitly:

```bash
kubectl get deployments --all-namespaces \
  -l app.kubernetes.io/name=restate-operator
kubectl get restateclusters.restate.dev
kubectl get restatedeployments.restate.dev --all-namespaces
kubectl get restatecloudenvironments.restate.dev --all-namespaces

kubectl delete crd \
  restateclusters.restate.dev \
  restatedeployments.restate.dev \
  restatecloudenvironments.restate.dev
```

A successful destroy always leaves the EKS cluster and the EBS volumes retained
by the former PVs. The bucket, snapshot IAM role/policy, and a Terraform-created
OIDC provider survive **only** when explicitly removed from state as above;
otherwise Terraform deletes them when possible. The CRDs survive until the
explicit post-destroy cleanup. See the
[full retained-resource inventory](../docs/05-operations.md#what-a-completed-teardown-leaves-behind)
and the broader
[data-safety checklist](../docs/05-operations.md#teardown-checklist).
