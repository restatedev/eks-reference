# Prerequisites

Complete this checklist before applying either deployment path. The repository
assumes an existing EKS cluster and does not create networking, worker nodes,
or cluster access for you.

## Deployment checklist

- [ ] The target EKS cluster and API endpoint are reachable from the machine
      running the deployment.
- [ ] At least three eligible nodes each have 24 vCPU and 50 GiB memory
      available for new pod requests after existing workload requests.
- [ ] The EBS CSI driver is installed and healthy.
- [ ] Restate data will use persistent EBS, not instance-store volumes.
- [ ] The EKS cluster uses the IPv4 IP family; this reference does not support
      IPv6 clusters.
- [ ] The NetworkPolicy enforcement choice and its security consequence are
      understood.
- [ ] Where NetworkPolicy is enforced, the cluster's Service IPv4 CIDR is
      recorded — `resources/06-restate-service-cidr-egress.yaml` needs it, and
      service registration fails without it.
- [ ] The AWS identity can manage the required S3 and IAM resources.
- [ ] The Kubernetes identity can create cluster-scoped and namespaced
      resources and install the operator.
- [ ] An IAM OIDC provider exists for the EKS cluster, or the chosen path will
      create it.
- [ ] For the manual path, a unique, dedicated snapshot bucket already exists
      in the target region with public access blocked and HTTPS-only access
      enforced; for Terraform, a globally unique name has been chosen.
- [ ] The EKS cluster name is at most 46 characters so the derived snapshot
      role name stays within IAM's 64-character limit.
- [ ] The required tools for one deployment path are installed.

## Set deployment context

The verification commands below use these variables:

```bash
export CLUSTER=...
export REGION=...
export ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export BUCKET=...   # globally unique; dedicated to this Restate cluster
```

Confirm that the identity and target cluster are the ones you intend to use:

```bash
aws sts get-caller-identity
aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
  --query 'cluster.{name:name,status:status,version:version,ipFamily:kubernetesNetworkConfig.ipFamily,endpoint:endpoint}'
```

Stop if `ipFamily` is not `ipv4`. Both deployment paths rely on the cluster's
`serviceIpv4Cidr` for the EKS VPC CNI egress policy.

## EKS capacity

The manifest requests three Restate pods at 24 vCPU and 50 GiB memory each and
uses required hostname anti-affinity. Kubernetes must find three different
eligible nodes.

| Requirement | Why |
|---|---|
| 3 eligible nodes | Hard anti-affinity allows one Restate pod per node |
| ≥24 vCPU available for new requests per node | Matches the pod request after existing pod requests |
| ≥50 GiB available for new requests per node | Matches the request and memory limit after existing pod requests |
| Prefer 3 Availability Zones | Reduces correlated node/AZ failure risk |
| Persistent EBS support | Restate data must survive node replacement |

`m7i.8xlarge` fits comfortably. `c7i.8xlarge` also fits, and has been measured:
on EKS 1.34 with AL2023, a `c7i.8xlarge` reports 31,850m CPU and 58.9 GiB
allocatable, and with the Restate pod plus system pods scheduled the node sits
at 76-79% of allocatable CPU and 85-87% of allocatable memory — roughly 7 GiB
of memory headroom. That works, and it leaves little room for anything else on
those nodes. Choose `m7i.8xlarge` if a log shipper, APM agent, service-mesh
sidecar, or any other per-node workload will share them.

Instance types with local NVMe (`*d`) must not be used as a substitute for the
persistent EBS volumes.

Inspect total allocatable capacity and placement labels:

```bash
kubectl get nodes -L topology.kubernetes.io/zone \
  -o custom-columns='NAME:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory,ZONE:.metadata.labels.topology\.kubernetes\.io/zone'
```

Allocatable is a ceiling, not free scheduler capacity. Existing pod requests,
including DaemonSets, are deducted before Restate can schedule. For each
candidate node, inspect the `Allocated resources` section and confirm at least
24 CPU and 50 GiB remain after the listed requests:

```bash
kubectl describe node <candidate-node>
```

Do not substitute `kubectl top`: current usage is not what the scheduler uses
for placement.

With Karpenter, prevent instance-store-backed Restate nodes by requiring:

```yaml
- key: karpenter.k8s.aws/instance-local-nvme
  operator: DoesNotExist
```

## EBS CSI driver

The `restate-gp3` StorageClass provisions volumes through
`ebs.csi.aws.com`. Confirm the add-on and controller are healthy:

```bash
aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
  --addon-name aws-ebs-csi-driver \
  --query 'addon.{status:status,version:addonVersion}'
kubectl -n kube-system get deployment ebs-csi-controller
```

If the add-on uses IRSA, the cluster already has an IAM OIDC provider in most
installations. The Terraform path looks that provider up by default.

## Network isolation

The manifests create NetworkPolicies around both the Restate cluster and SDK
services. EKS VPC CNI NetworkPolicy enforcement is **off by default**.

Running without enforcement is formally supported, but it changes the trust
model completely: the policies are inert, every pod in the EKS cluster can
reach the unauthenticated Restate admin API on port 9070, and every pod can call
SDK endpoints on port 9080 directly. Only accept that on a single-tenant
cluster where every workload is trusted with those capabilities.

Inspect the add-on configuration and API support:

```bash
aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
  --addon-name vpc-cni --query addon.configurationValues
kubectl api-resources | grep policyendpoints
```

The add-on setting is `enableNetworkPolicy: true` (represented as
`ENABLE_NETWORK_POLICY=true` in the `aws-node` DaemonSet). Seeing
NetworkPolicy objects alone does not prove enforcement.

### Enforcement requires one extra policy

Turning enforcement on has a consequence the operator cannot handle for you.
The VPC CNI evaluates egress at the pod's veth, before kube-proxy rewrites a
Service ClusterIP to a pod IP, so the operator's pod-label egress rule — which
expands to pod IPs — does not cover the ClusterIP it registers each service
revision under. Registration then times out and the RestateDeployment never
becomes Ready, while the service pods look healthy. The fix is
`resources/06-restate-service-cidr-egress.yaml`, applied at the end of runbook
step 4 and automatic on the Terraform path. Read its header for the full
mechanism and for the exact scope of the allowance it grants.

Record the Service CIDR it needs:

```bash
aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
  --query 'cluster.kubernetesNetworkConfig.serviceIpv4Cidr' --output text
```

Do not assume a value. `eksctl` defaults to `10.100.0.0/16`, while clusters
created without an explicit setting are often `172.20.0.0/16`.

## AWS resources and permissions

### Snapshot bucket

The bucket must be dedicated to this Restate cluster. The configured snapshot
path is always:

```text
s3://<bucket>/restate/snapshots/
```

A snapshot repository belongs to one Restate cluster. Do not point two
clusters at the same bucket/prefix.

The manual path expects the bucket to exist already with:

- all public access blocked;
- HTTPS-only access enforced;
- default SSE-S3 encryption (AWS enables this for new objects);
- no bucket lifecycle rule deleting live snapshot objects.

Verify the pre-existing manual-path bucket rather than assuming its controls:

```bash
aws s3api head-bucket --bucket "$BUCKET"
aws s3api get-bucket-location --bucket "$BUCKET"
aws s3api get-public-access-block --bucket "$BUCKET"
aws s3api get-bucket-policy --bucket "$BUCKET" \
  --query Policy --output text | jq
aws s3api get-bucket-encryption --bucket "$BUCKET"
```

The policy must contain an explicit `Deny` for requests where
`aws:SecureTransport` is `false`; a `null` location means `us-east-1`, otherwise
the returned location must match `$REGION`. Do not point the deployment at an
existing general-purpose bucket merely because it is reachable.

The Terraform path creates those bucket controls and leaves `force_destroy`
disabled.

### IAM and IRSA

The deploying identity needs enough AWS permission to:

- read the EKS cluster and its OIDC issuer;
- inspect the manual-path bucket controls and list its snapshot objects;
- create or read the IAM OIDC provider;
- create the cluster-qualified snapshot policy and role;
- attach the policy to the role;
- create and configure the S3 bucket on the Terraform path.

The snapshot role trusts only:

```text
system:serviceaccount:restate:restate
```

The derived role name is `<cluster>-restate-snapshots`. The suffix consumes 18
of IAM's 64 allowed characters, so this repository limits `cluster_name` to 46
characters.

## Kubernetes and Helm access

Valid AWS credentials do not automatically grant Kubernetes authorization.
The identity used by `kubectl`, Helm, and the Terraform Kubernetes provider
must have an EKS access entry or `aws-auth` mapping with permission to manage:

- namespaces;
- cluster-scoped StorageClasses;
- CustomResourceDefinitions, ClusterRoles, and ClusterRoleBindings installed by
  the operator chart;
- NetworkPolicies;
- Helm releases, Deployments, and related namespaced resources;
- `RestateCluster` and `RestateDeployment` custom resources after the CRDs are
  installed.

Basic checks:

```bash
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"
kubectl cluster-info
kubectl auth can-i create namespaces
kubectl auth can-i create storageclasses.storage.k8s.io
kubectl auth can-i create networkpolicies.networking.k8s.io --all-namespaces
kubectl auth can-i create customresourcedefinitions.apiextensions.k8s.io
kubectl auth can-i create clusterroles.rbac.authorization.k8s.io
kubectl auth can-i create clusterrolebindings.rbac.authorization.k8s.io
```

All six authorization checks should return `yes` for the manual path. The
Terraform path uses `aws eks get-token` directly, but needs equivalent access.

## OCI chart registry access

The Restate operator chart is an OCI artifact in GitHub Container Registry:
`oci://ghcr.io/restatedev/restate-operator-helm`. The package is public and
pulls anonymously, so registry credentials are **not** a prerequisite of this
reference.

Two situations still produce `401` or `403` while fetching the chart, in
decreasing order of likelihood:

1. **A credential you already have.** GHCR rejects a stale or insufficiently
   scoped credential instead of falling back to anonymous access, so a
   `ghcr.io` entry in `~/.docker/config.json` or an earlier
   `helm registry login` can make a public pull fail. GitHub tokens without the
   `read:packages` scope fail exactly this way. Clear the credential and retry:

   ```bash
   helm registry logout ghcr.io || true
   docker logout ghcr.io || true
   ```

2. **An environment that blocks anonymous registry access**, such as an egress
   proxy or an authenticated mirror. Log in with a GitHub token that carries
   `read:packages`:

   ```bash
   export GHCR_USERNAME=...       # GitHub username
   export GHCR_TOKEN=...          # token with read:packages; do not commit it
   printf '%s' "$GHCR_TOKEN" | helm registry login ghcr.io \
     --username "$GHCR_USERNAME" --password-stdin
   ```

   A token from `gh auth token` works when its scopes include `read:packages`.
   Run the login in the same shell as Terraform/OpenTofu: the Helm provider
   fetches the chart during `plan`, not only during apply. If you point Helm at
   a temporary registry configuration, set `HELM_REGISTRY_CONFIG` before both
   the login and the plan/apply so the provider reuses the credential.

Verify either way with an explicit pull before installing the operator:

```bash
helm pull oci://ghcr.io/restatedev/restate-operator-helm \
  --version 3.0.1 --destination /tmp
```

## Tooling

Choose one path; you do not need every tool in both columns.

| Tool | Manual path | Terraform path | Purpose |
|---|:---:|:---:|---|
| AWS CLI v2 | ✓ | ✓ | Identity, EKS lookup, IAM, S3, exec auth |
| `kubectl` | ✓ | recommended | Apply and diagnose Kubernetes resources |
| `eksctl` | ✓ | — | OIDC provider and IRSA role plumbing |
| Helm | ✓ | optional* | Install the operator manually; verify or authenticate the OCI chart pull |
| Terraform ≥1.5 or OpenTofu | — | ✓ | Apply the two Terraform stages |
| `jq` | ✓ | recommended | Format API responses |
| `restatectl` | via pod | via pod | Cluster status and snapshots; provisioning remains operator-managed |
| `restate` CLI | optional | optional | Service/deployment administration |

`*` The Terraform Helm provider installs the release itself, so the Terraform
path does not need the Helm CLI. It is useful for the `helm pull` check above,
and required only if your environment forces a `helm registry login`.

An optional Nix development shell is provided:

```bash
nix-shell
```

`restatectl` is already present in the Restate image, so the guides run it with
`kubectl exec`. Local installations are optional:

```bash
npm install -g @restatedev/restatectl
npm install -g @restatedev/restate
```

## Manual-path placeholders

Before using the manual runbook, replace every `REPLACE_ME_*` value under
`resources/`:

```bash
grep -RIn 'REPLACE_ME' resources
```

| Placeholder | Files | Value |
|---|---|---|
| `REPLACE_ME_SNAPSHOTS_BUCKET` | `01-restate-snapshots-iam-policy.json`, `04-restate-cluster.yaml` | Dedicated snapshot bucket name |
| `REPLACE_ME_AWS_REGION` | `04-restate-cluster.yaml` | Region used by the Restate AWS SDK |
| `REPLACE_ME_SNAPSHOTS_ROLE_ARN` | `04-restate-cluster.yaml` | `arn:aws:iam::<account>:role/<cluster>-restate-snapshots` |
| `REPLACE_ME_SERVICE_IMAGE` | `05-restate-compute.yaml` | SDK service image; apply compute only after setting it |
| `REPLACE_ME_SERVICE_CIDR` | `06-restate-service-cidr-egress.yaml` | Cluster Service IPv4 CIDR; needed where the CNI enforces NetworkPolicy |
| `REPLACE_ME_EKS_CLUSTER_NAME` | `02-restate-operator.values.yaml` (commented) | Only when adapting the repository for EKS Pod Identity; the supplied IAM paths implement IRSA only |

The Terraform path does not modify the files. It replaces the required values
in memory from `terraform.tfvars`.

## Appendix: an example cluster, for illustration only

This reference does not own cluster creation, and nothing below is part of what
it manages, supports, or keeps current. It is recorded because the requirements
above are easier to act on next to a configuration that satisfied them. Treat
it as a worked example to adapt, not a recommended baseline — in particular,
review `privateNetworking`, the root volume size, and the AMI family against
your own standards.

The configuration below was used to create the cluster this repository was last
validated end to end against, on EKS 1.34 in `eu-central-1`:

```yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: YOUR_CLUSTER
  region: YOUR_REGION

availabilityZones:
  - YOUR_REGIONa
  - YOUR_REGIONb
  - YOUR_REGIONc

iam:
  withOIDC: true

addons:
  - name: vpc-cni
    configurationValues: |
      enableNetworkPolicy: "true"
  - name: coredns
  - name: kube-proxy
  - name: aws-ebs-csi-driver
    wellKnownPolicies:
      ebsCSIController: true

managedNodeGroups:
  - name: restate-nodes
    instanceType: c7i.8xlarge
    desiredCapacity: 3
    minSize: 3
    maxSize: 3
    amiFamily: AmazonLinux2023
    volumeSize: 100
    privateNetworking: true
```

Three details in it matter to this reference rather than to eksctl. `withOIDC`
creates the IAM OIDC provider that IRSA needs, which is why the Terraform path
defaults to looking a provider up rather than creating one. The `vpc-cni`
`enableNetworkPolicy` value is what makes the NetworkPolicies in `resources/`
actually enforced, and therefore what makes
`resources/06-restate-service-cidr-egress.yaml` necessary. The EBS CSI driver
is required by the `restate-gp3` StorageClass, not optional.

## Next step

- For Terraform or OpenTofu, continue to the [Terraform guide](../terraform/README.md).
- For CLI-driven installation, continue to the [manual runbook](02-runbook.md).
