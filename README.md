# Restate on EKS: replicated reference deployment

This repository is a production-shaped reference for running a **three-node,
replicated Restate cluster** on an existing Amazon EKS cluster with the
[Restate operator](https://github.com/restatedev/restate-operator). It also
shows how to run Restate SDK services in a separate Kubernetes namespace and
let the operator register, version, and drain them safely.

The sizing and runtime tuning come from Restate Cloud's
`3-node.xlarge-vqueues` profile:

| Setting | Value |
|---|---|
| Restate nodes | 3, with hard host anti-affinity |
| Per-node request | 24 vCPU, 50 GiB memory |
| Data volume | 1 TiB encrypted `restate-gp3` EBS volume |
| Partitions | 48 |
| Node replication | 2 |
| Restate image | `docker.restate.dev/restatedev/restate:1.7.7` |
| Operator chart | `3.0.1` |

> [!IMPORTANT]
> This repository does **not** create an EKS cluster, VPC, worker nodes,
> ingress, DNS, or an observability stack. It is a reference deployment for an
> existing cluster, not a turnkey production platform.

## What you get

- Operator-managed bootstrap of a replicated Restate cluster.
- Persistent EBS storage with `Retain` reclamation to reduce accidental data
  loss during cluster deletion.
- Partition snapshots in a dedicated S3 bucket through IRSA.
- Default-deny networking around Restate, plus isolation for SDK services.
- A `RestateDeployment` example with immutable revisions, automatic
  registration, graceful draining, and rollback support.
- Two deployment paths that consume the same manifests:
  - a transparent, command-by-command `kubectl`/Helm runbook;
  - a two-stage Terraform or OpenTofu workflow.

## Before you deploy

Read these constraints first; they are not optional sizing trivia.

1. **Capacity:** you need at least three eligible nodes, each with 24 vCPU and
   50 GiB memory still available for new pod requests after existing system and
   DaemonSet requests. One Restate pod is scheduled per node.
2. **Network isolation:** EKS VPC CNI NetworkPolicy enforcement is disabled by
   default. Without it, every pod in the cluster can reach Restate's
   unauthenticated admin API on port 9070 and SDK endpoints on port 9080.
3. **IP family:** this reference currently supports IPv4 EKS clusters only. Its
   Service-CIDR egress policy is derived from `serviceIpv4Cidr`.
4. **Snapshots:** the S3 bucket must be dedicated to this Restate cluster. The
   snapshot prefix is not unique across installations.
5. **Persistent data:** deleting the `RestateCluster` removes its namespace and
   PVCs. The StorageClass retains the underlying PVs, but recovery is a manual
   operation; retained volumes do not reattach automatically.
6. **Existing infrastructure:** the EBS CSI driver, sufficient EKS access, and
   an IAM OIDC provider for IRSA must already exist unless the Terraform path
   is explicitly told to create the OIDC provider.

The complete checklist and verification commands are in
[Prerequisites](docs/01-prerequisites.md).

## Choose a deployment path

| Path | Best for | Entry point |
|---|---|---|
| AWS CLI + eksctl + Helm + kubectl (**default**) | Understanding every component, one-off installs, or integrating the manifests into another delivery system | [Manual runbook](docs/02-runbook.md) |
| Terraform / OpenTofu | Repeatable environments with managed state and reviewable plans | [Terraform guide](terraform/README.md) |

Do not mix the paths in the same installation without importing the existing
AWS and Kubernetes resources into Terraform state.

Both paths deploy the cluster and stop there. Your SDK services are deployed
separately, with `kubectl` or your existing application pipeline — but they are
still operator-managed: the operator reconciles them as `RestateDeployment`
resources, handling revisioning, registration, and draining. See
[Deploying services](docs/03-deploying-services.md).

## Architecture at a glance

```text
                                  existing EKS cluster

  operators ── port-forward ──►  svc/restate :9070 (admin, unauthenticated)
  clients   ──────────────────►  svc/restate :8080 (ingress)
                                      │
                           namespace: restate
                           StatefulSet restate-0..2
                            │        │         │
                            └────────┼─────────┘  node traffic :5122
                                     │
                    invocation :9080 │
                                     ▼
                          namespace: restate-apps
                          RestateDeployment revisions

  each Restate pod ──► 1 TiB EBS PV       cluster ──IRSA──► dedicated S3 bucket
```

The operator owns the `restate` namespace and materializes the StatefulSet,
Services, ServiceAccount, and NetworkPolicies from the `RestateCluster` custom
resource. This repository owns the `restate-operator` and `restate-apps`
namespaces. See [Architecture](docs/00-architecture.md) for bootstrap,
networking, IAM, and ownership details.

## Documentation

| If you need to… | Read |
|---|---|
| Understand the topology and security boundaries | [Architecture](docs/00-architecture.md) |
| Check capacity, AWS, access, and tooling | [Prerequisites](docs/01-prerequisites.md) |
| Install with CLI tools | [Manual runbook](docs/02-runbook.md) |
| Install with Terraform or OpenTofu | [Terraform guide](terraform/README.md) |
| Deploy or roll back SDK services | [Deploying services](docs/03-deploying-services.md) |
| Operate, diagnose, or remove the deployment | [Operations and troubleshooting](docs/05-operations.md) |
| Understand deviations from Restate Cloud | [Profile fidelity](docs/04-profile-fidelity.md) |

Recommended order for a first deployment:

1. [Architecture](docs/00-architecture.md)
2. [Prerequisites](docs/01-prerequisites.md)
3. [Manual runbook](docs/02-runbook.md), or the alternative [Terraform guide](terraform/README.md)
4. [Operations and troubleshooting](docs/05-operations.md)
5. [Deploying services](docs/03-deploying-services.md)

## Repository layout

```text
resources/             canonical Kubernetes YAML, Helm values, and IAM policy
terraform/01-foundation
                       S3, IAM/IRSA, namespaces, StorageClass, operator
terraform/02-restate   RestateCluster and its Service-CIDR egress policy
docs/                  architecture, deployment, operations, and design notes
scripts/               repository validation checks
shell.nix              optional development shell with the required CLI tools
```

The numbered files under `resources/` are the source of truth for both
deployment paths:

| File | Purpose |
|---|---|
| [`00-namespaces.yaml`](resources/00-namespaces.yaml) | Operator and compute namespaces; compute ingress isolation |
| [`01-restate-snapshots-iam-policy.json`](resources/01-restate-snapshots-iam-policy.json) | Least-privilege S3 snapshot policy |
| [`02-restate-operator.values.yaml`](resources/02-restate-operator.values.yaml) | Restate operator Helm values |
| [`03-gp3-storageclass.yaml`](resources/03-gp3-storageclass.yaml) | Encrypted `restate-gp3` StorageClass with retained PVs |
| [`04-restate-cluster.yaml`](resources/04-restate-cluster.yaml) | Three-node `RestateCluster` and runtime configuration |
| [`05-restate-compute.yaml`](resources/05-restate-compute.yaml) | Example `RestateDeployment` for an SDK service |
| [`06-restate-service-cidr-egress.yaml`](resources/06-restate-service-cidr-egress.yaml) | Lets Restate reach service ClusterIPs where the CNI enforces NetworkPolicy |

The manual path requires every active `REPLACE_ME_*` value in a file being
applied to be replaced first. The commented, non-automated Pod Identity
adaptation may stay unset, and the compute image may stay unset while compute is
skipped. The Terraform path performs the substitutions it needs in memory, from
its variables and from the EKS cluster itself; the service image is not among
them, because Terraform does not deploy services.

## Validation

Run the same formatting, Terraform, YAML/JSON, and local documentation-link
checks used by CI:

```bash
nix-shell --run ./scripts/validate.sh
```

The Terraform checks initialize provider plugins but do not contact an EKS
cluster or AWS account.

## Important design decisions

| Decision | Reason |
|---|---|
| Operator-managed provisioning | Prevents multiple Restate nodes racing to initialize cluster state |
| Separate compute namespace | Keeps SDK services outside the operator-owned Restate namespace |
| Admin API excluded from workload peers | Port 9070 is unauthenticated and grants full cluster control |
| Dedicated snapshot bucket | A snapshot repository belongs to one Restate cluster |
| `Retain` EBS reclaim policy | Preserves volumes after accidental CR/namespace deletion |
| Restate-specific StorageClass name | Avoids colliding with a shared cluster's generic `gp3` class |
| Two Terraform stages | Restate CRDs must exist in the live cluster before custom resources can be planned |

## Known boundaries

- NetworkPolicy is only effective when the cluster CNI enforces it.
- The admin API is intentionally reached through `kubectl port-forward`; do
  not expose port 9070 through an unauthenticated LoadBalancer or Ingress.
- S3 snapshots and retained EBS volumes reduce recovery risk, but this
  repository does not define a complete disaster-recovery procedure.
- Runtime upgrades require re-validating the experimental vqueues settings and
  should not be performed by changing the image alone.
- The example SDK service has placeholder image and sizing values; treat it as
  a skeleton, not a production application template.

Start with [Prerequisites](docs/01-prerequisites.md), then choose the
[Terraform](terraform/README.md) or [manual](docs/02-runbook.md) deployment
path.
