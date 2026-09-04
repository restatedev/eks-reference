# Restate on EKS: replicated reference deployment

This repository is an installation reference for a cloud or platform engineer
who has been asked to deploy Restate into an existing Amazon EKS cluster. It
assumes working knowledge of AWS, EKS, IAM, Kubernetes, and either Terraform or
the AWS/Kubernetes command-line tools. It does not assume prior Restate
operational experience.

[Restate](https://docs.restate.dev/foundations/key-concepts) is a durable
execution runtime. It sits in front of application services, records invocation
progress, and lets work resume after failures without repeating completed
steps. This repository installs the runtime as a **three-node replicated
cluster** and installs the Kubernetes
[Restate operator](https://github.com/restatedev/restate-operator) that manages
it.

Keep these three layers separate while reading the guide:

| Term | Meaning in this repository |
|---|---|
| EKS cluster | Existing AWS/Kubernetes infrastructure; this repository leaves it unchanged |
| Restate cluster | Three stateful Restate server pods installed into EKS |
| SDK service | Customer application code that uses a Restate SDK; deployed through an independent application workflow |

The cluster shape and runtime tuning are derived from Restate Cloud's
`3-node.xlarge-vqueues` profile. This standalone reference adapts selected
infrastructure settings, including its initial storage capacity; the
[profile-fidelity record](docs/04-profile-fidelity.md) explains each difference.

| Setting | Value |
|---|---|
| Restate nodes | 3, with hard host anti-affinity |
| Per-node request | 24 vCPU, 50 GiB memory |
| Data volume | 256 GiB encrypted `restate-gp3` EBS volume; monitor utilization and expand with headroom |
| Partitions | 48 |
| Node replication | 2 |
| Restate image | `docker.restate.dev/restatedev/restate:1.7.7` |
| Operator chart | `3.0.1` |

> [!IMPORTANT]
> This repository does **not** create an EKS cluster, VPC, worker nodes,
> ingress, DNS, or an observability stack. It is a reference deployment for an
> existing cluster, not a turnkey production platform.

## What you get

- A Kubernetes operator that creates, initializes, and monitors the replicated
  Restate cluster.
- Persistent EBS storage with `Retain` reclamation to reduce accidental data
  loss during cluster deletion.
- Partition snapshots in a dedicated S3 bucket through IAM Roles for Service
  Accounts (IRSA).
- Default-deny networking around Restate, plus isolation for SDK services.
- An optional `RestateDeployment` example showing how an application team can
  roll out and drain SDK service revisions safely.
- Two deployment paths that consume the same manifests:
  - a transparent, command-by-command `kubectl`/Helm runbook;
  - a two-stage Terraform or OpenTofu cluster workflow, with an optional third
    application stage kept in separate state.

Completing the cluster portion of either deployment path gives you a healthy
Restate cluster, its operator, persistent storage, and snapshot access. It does
**not** expose a public endpoint. A customer application is a separate handoff
to its application owner; the Terraform path includes an optional, separately
state-managed example for teams that want it.

## Before you deploy

Please confirm these readiness checks before deploying. The prerequisite guide
provides the commands that verify each one.

1. **Capacity:** you need at least three eligible nodes, each with 24 vCPU and
   50 GiB memory still available for new pod requests after existing system and
   DaemonSet requests. One Restate pod is scheduled per node.
2. **Network isolation:** EKS VPC CNI NetworkPolicy enforcement is disabled by
   default. Without it, every pod in the cluster can reach Restate's
   unauthenticated admin API on port 9070 and SDK endpoints on port 9080.
3. **IP family:** this reference currently supports IPv4 EKS clusters only. Its
   Service-CIDR egress policy is derived from `serviceIpv4Cidr`.
4. **Snapshots:** use an S3 bucket dedicated to this Restate cluster. The
   snapshot prefix is not unique across installations.
5. **Metadata durability:** choose the replicated metadata store shipped in the
   example or an S3 metadata store before the first cluster apply. The S3
   option removes metadata quorum from the Restate volumes, while adding an
   external dependency and latency consideration. See
   [Data durability](docs/00-architecture.md#data-durability-model).
6. **Persistent data:** deleting the `RestateCluster` removes its namespace and
   PVCs. The StorageClass retains the underlying PVs, but recovery is a manual
   operation; retained volumes do not reattach automatically.
7. **Existing infrastructure:** the EBS CSI driver, sufficient EKS access, and
   an IAM OIDC provider for IRSA must already exist unless the Terraform path
   is explicitly told to create the OIDC provider.

The complete checklist and verification commands are in
[Prerequisites](docs/01-prerequisites.md).

## Choose a deployment path

| Path | Best for | Entry point |
|---|---|---|
| AWS CLI + eksctl + Helm + kubectl | A guided install, reviewing each component, or integrating the manifests into another delivery system | [Manual runbook](docs/02-runbook.md) |
| Terraform / OpenTofu | State-managed environments with repeatable, reviewable plans | [Terraform guide](terraform/README.md) |

Please use one path per installation. If you move an existing installation to
Terraform, first import its AWS and Kubernetes resources into Terraform state.

Both paths finish with the Restate cluster installed. Deploy SDK services from
an application-owned workflow: use `kubectl`, your existing delivery system,
or the optional `terraform/03-services` example in separate state. The operator
then reconciles each `RestateDeployment`, handling revisioning, registration,
and draining. See [Deploying services](docs/03-deploying-services.md).

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

  each Restate pod ──► 256 GiB EBS PV     cluster ──IRSA──► dedicated S3 bucket
```

The operator owns the `restate` namespace and materializes the StatefulSet,
Services, ServiceAccount, and NetworkPolicies from the `RestateCluster` custom
resource. This repository owns the `restate-operator` and `restate-apps`
namespaces. See [Architecture](docs/00-architecture.md) for bootstrap,
networking, IAM, and ownership details.

## Documentation

| Task | Read | When |
|---|---|---|
| Confirm the EKS cluster is suitable and your identities are authorized | [Prerequisites](docs/01-prerequisites.md) | Required before installation |
| Install with CLI tools | [Manual runbook](docs/02-runbook.md) | Choose this or Terraform |
| Carry a printable installation and handoff reference | [Manual deployment PDF](output/pdf/restate-eks-manual-deployment-reference.pdf) | Optional companion to the manual runbook |
| Install with Terraform or OpenTofu | [Terraform guide](terraform/README.md) | Choose this or the manual runbook |
| Verify, operate, troubleshoot, or remove the deployment | [Operations and troubleshooting](docs/05-operations.md) | Required for handoff and day-two work |
| Understand topology, security, and ownership | [Architecture](docs/00-architecture.md) | Reference during design or review |
| Deploy or roll back customer SDK services | [Deploying services](docs/03-deploying-services.md) | Application/platform-team handoff |
| Maintain the profile-derived tuning | [Profile fidelity](docs/04-profile-fidelity.md) | Maintainer reference; not needed to install |

For a first installation, follow the three required tasks in order:
prerequisites, one deployment path, then the operations handoff checks. Use the
other guides only when their ownership or design topic applies.

## Repository layout

```text
resources/             canonical Kubernetes YAML, Helm values, and IAM policy
terraform/01-foundation
                       S3, IAM/IRSA, namespaces, StorageClass, operator
terraform/02-restate   RestateCluster and its Service-CIDR egress policy
terraform/03-services  optional SDK service example in independent state
docs/                  architecture, deployment, operations, and design notes
misc/pdf/              source and LLM-oriented build guide for the PDF companion
output/pdf/            committed customer-facing PDF artifacts
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
skipped. The Terraform path performs substitutions in memory from its variables
and the EKS cluster. Stages 01 and 02 install the cluster; optional stage 03
substitutes `service_image` into the SDK service example.

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
| Two ordered Terraform cluster stages | Restate CRDs must exist in the live cluster before custom resources can be planned |
| Separate optional service state | Application releases keep their cadence and blast radius separate from cluster infrastructure |

## Known boundaries

- NetworkPolicy is only effective when the cluster CNI enforces it.
- The admin API is intentionally reached through `kubectl port-forward`; do
  not expose port 9070 through an unauthenticated LoadBalancer or Ingress.
- S3 snapshots and retained EBS volumes reduce recovery risk, but this
  repository does not define a complete disaster-recovery procedure.
- The validated cluster manifest uses replicated metadata. Decide whether to
  adopt the documented S3 metadata option before the first cluster apply.
- Runtime upgrades require re-validating the experimental vqueues settings and
  should not be performed by changing the image alone.
- The example SDK service has placeholder image and sizing values; treat it as
  a skeleton, not a production application template.

Start with [Prerequisites](docs/01-prerequisites.md), then choose the
[Terraform](terraform/README.md) or [manual](docs/02-runbook.md) deployment
path.
