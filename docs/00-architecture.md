# Architecture

This document explains what the deployment creates, which component owns each
resource, how traffic is allowed, and how a fresh three-node Restate cluster
becomes usable.

You do not need to read this document end to end to perform a standard
installation. Use it when reviewing security and ownership, diagnosing a
cross-component problem, or changing the supplied defaults.

The operator behavior described here was verified against the
[Restate operator](https://github.com/restatedev/restate-operator) at Helm chart
version `3.0.1`.

## Design summary

- A `RestateCluster` named `restate` produces an operator-owned namespace of
  the same name.
- Three Restate pods run as one StatefulSet with one pod per Kubernetes node.
- Each pod has a 1 TiB EBS volume; partition snapshots are written to a
  cluster-dedicated S3 bucket.
- The operator, not an individual Restate node, provisions the cluster exactly
  once.
- SDK services run as `RestateDeployment` resources in `restate-apps`, outside
  the operator-owned namespace.
- Port 8080 is the client ingress API. Port 9070 is an unauthenticated admin API
  and is intentionally restricted to the operator and local port-forward use.
- NetworkPolicies provide the isolation boundary only when the cluster CNI
  enforces them.

## Logical topology

```text
namespace: restate-operator
  └─ Deployment/restate-operator
       │ watches RestateCluster and RestateDeployment resources
       │ provisions the cluster and registers service revisions
       ▼

namespace: restate                         operator-owned lifecycle
  ├─ StatefulSet/restate
  │    ├─ restate-0 ── PVC ── EBS
  │    ├─ restate-1 ── PVC ── EBS
  │    └─ restate-2 ── PVC ── EBS
  ├─ Service/restate                       ClusterIP
  │    ├─ :8080 ingress
  │    ├─ :9070 admin
  │    └─ :5122 metrics
  ├─ Service/restate-cluster               headless, node traffic :5122
  ├─ ServiceAccount/restate                IRSA role annotation
  └─ NetworkPolicies                       default deny + explicit allowances

namespace: restate-apps                    repository/user-owned lifecycle
  ├─ RestateDeployment/service
  ├─ ReplicaSet + Service per revision
  └─ NetworkPolicy                         ingress from namespace restate only

Restate pods ── IRSA ──► dedicated S3 snapshot bucket
```

## Ownership and deletion boundaries

Understanding ownership matters because deleting a parent resource can remove
an entire layer below it.

| Resource | Owner | Lifecycle consequence |
|---|---|---|
| Existing EKS cluster, VPC, nodes | Outside this repository | Left unchanged by this repository |
| IAM OIDC provider | Existing cluster by default; optionally Terraform stage 01 | Shared by IRSA workloads; retain unless a dependency review confirms it is unused |
| Snapshot bucket and Restate IAM role | Operator/platform team or Terraform stage 01 | Bucket is dedicated to one Restate cluster |
| `restate-operator` namespace | This repository / Terraform stage 01 | Contains the operator Helm release |
| `restate-apps` namespace | This repository / Terraform stage 01 | Contains user SDK service revisions |
| Restate CRDs | Operator Helm release / Terraform stage 01 | Annotated to survive Helm uninstall; delete only after a cluster-wide dependency check |
| `restate` namespace | Restate operator | Created and deleted with `RestateCluster/restate` |
| StatefulSet, Services, ServiceAccount, cluster policies | Restate operator | Reconciled from the `RestateCluster` spec |
| PVCs | Restate operator through the StatefulSet | Deleted with the operator-owned namespace |
| EBS PVs | `restate-gp3` StorageClass / EBS CSI driver | Retained after PVC deletion; recovery is manual |

Leave the `restate` namespace for the operator to create and manage throughout
its lifecycle.

## Traffic and trust boundaries

The operator starts from deny-all ingress and egress in the `restate`
namespace. It then opens node-to-node traffic on 5122, operator-to-admin
traffic needed for provisioning and registration, DNS, public-internet egress,
and egress to labeled `RestateDeployment` pods. Private ranges remain excluded
from the general egress allowance.

| Source | Destination | Port | Allowed by | Purpose |
|---|---|---:|---|---|
| Clients | `Service/restate` | 8080 | How you expose ingress | Invoke Restate handlers |
| Human operator | `Service/restate` | 9070 | `kubectl port-forward` | Admin and diagnostics |
| Restate operator | Restate admin API | 9070 | Operator-specific policy carve-out | Provision cluster; register revisions |
| Restate pods | Restate pods | 5122 | Operator-generated policy | Metadata and node traffic |
| Restate pods | SDK service revisions | 9080 | Operator-applied labels and egress policy | Execute invocations |
| SDK service namespace | Restate ingress | 8080 | `security.networkPeers.ingress` | Optional in-cluster calls into Restate |
| Restate pods | AWS STS and S3 | HTTPS | Public egress policy and IRSA | Credentials and snapshots |

The cross-namespace model is easiest to reason about as three distinct
directions:

1. **Restate cluster → SDK services:** automatic for `RestateDeployment` pods.
   The operator adds `allow.restate.dev/<cluster-name>: "true"`, and the
   cluster egress policy selects that label in any namespace.
2. **SDK services → Restate cluster:** not automatic. The manifest explicitly
   allows the `restate-apps` namespace to reach ingress on port 8080. It does
   not allow that namespace to reach admin on port 9070.
3. **Other workloads → SDK services:** denied by the repository-owned policy
   selecting every pod in `restate-apps` and allowing only the `restate`
   namespace. This prevents direct calls that bypass Restate.

These boundaries govern network reachability, not authorization between
services. Any service registered with the cluster can invoke any other through
Restate, so one `RestateCluster` is one trust domain; see
[Team isolation](03-deploying-services.md#team-isolation).

### Admin API

The admin API on port 9070 has no authentication and grants full cluster
control, including deployment registration/deletion and SQL access to state.
The manifests therefore do **not** add `restate-apps` as an admin peer.

The operator receives its own built-in admin carve-out through
`allowOperatorAccessToAdmin` (enabled by default). Humans use
`kubectl port-forward` or `kubectl exec`; these paths tunnel through the
kubelet and do not require opening the admin port to workloads. Restate Cloud
similarly exposes admin only through its own authenticating gateway.

### SDK service isolation

The operator adds `allow.restate.dev/restate: "true"` to pods belonging to a
`RestateDeployment` registered with this cluster. The Restate namespace egress
policy selects that label in any namespace, allowing invocation traffic to
port 9080.

The reverse boundary is owned here: `resources/00-namespaces.yaml` selects all
pods in `restate-apps` and admits ingress only from the `restate` namespace.
That stops unrelated cluster workloads calling an SDK endpoint directly and
bypassing Restate.

That label-based egress rule covers service **pod IPs**, and the operator
registers each revision by its **Service name**, which resolves to a ClusterIP.
Where the CNI evaluates policy before kube-proxy's DNAT — the EKS VPC CNI does,
because its agent hooks the pod's veth — the ClusterIP matches neither the
label-expanded pod IPs nor the internet-egress rule, which excludes private
ranges. Registration then times out with healthy service pods, and the gap is
not expressible in the `RestateCluster` CRD, which has no egress peer field. So
this reference owns a third policy for it,
`resources/06-restate-service-cidr-egress.yaml`, which allows the Restate pods
TCP 9080 into the Service CIDR. Calico and Cilium evaluate after DNAT and do not
need it. Because NetworkPolicy rules are additive, that stable CIDR allowance
can also reach any other ClusterIP backend on port 9080 unless the destination
pod has its own ingress policy; the repository-owned `restate-apps` policy is
the destination-side restriction for the example SDK namespace.

### CNI enforcement

Kubernetes accepts NetworkPolicy objects even when no network-policy engine is
enforcing them. EKS VPC CNI enforcement is disabled by default. With it off,
the policy objects are visible but inert: every pod can reach ports 9070 and
9080.

The deployment can function without enforcement only when the EKS cluster is
single-tenant and every workload is trusted with Restate administration and
direct SDK access. See [Prerequisites](01-prerequisites.md#network-isolation).

Enforcement is not free of consequences either: with it on, service
registration additionally requires
`resources/06-restate-service-cidr-egress.yaml`, for the pre-DNAT reason
described under [SDK service isolation](#sdk-service-isolation).

### Private AWS endpoints

The operator-generated default egress policy allows public destinations while
excluding private ranges (`10/8`, `172.16/12`, `192.168/16`, and
`169.254/16`). This has two AWS-specific consequences:

- an S3 **Gateway** endpoint works because routing changes while the S3
  destination addresses remain public;
- an STS or S3 **Interface** endpoint resolves to private VPC addresses and is
  blocked unless those addresses are explicitly allowed with
  `networkEgressRules` on the `RestateCluster`.

If IRSA works on the node but snapshot credentials time out inside the Restate
pod, inspect private DNS and interface endpoints before changing IAM policy.

## Cluster bootstrap sequence

A fresh replicated cluster needs stable peer addresses and node IDs before it
can be provisioned. The manifest and operator divide that work deliberately:

```text
1. StatefulSet starts restate-0..2
2. each pod derives the same metadata peer list from stable StatefulSet DNS
3. each pod derives a stable node ID from its pod index
4. Restate nodes form the metadata cluster but do not self-provision
5. operator sees restate-0 Running
6. operator calls ProvisionCluster once
7. configured defaults create 48 partitions with node replication 2
8. pods become Ready and RestateCluster reports provisioned/Ready
```

The key settings are:

- `auto-provision = false` in the Restate config, so no node races to initialize
  state;
- `spec.cluster.autoProvision: true`, so the operator performs the one-time
  provisioning call;
- `default-num-partitions = 48` and
  `default-replication = { node = 2 }`, used by that call.

The operator waits for `restate-0` to be **Running**, deliberately not Ready
because Restate pods become Ready only after provisioning. It calls the
`ProvisionCluster` gRPC API through the headless Service with no explicit
parameters, so the contacted node's configured partition and replication
defaults apply.

The operator validates that server self-provisioning is disabled and rejects
the configuration unless the TOML contains `auto-provision = false` or the
equivalent `RESTATE_AUTO_PROVISION=false` environment setting. No node can race
the operator to initialize cluster state.

The operator treats “already provisioned” as success and caches the outcome in
`status.provisioned`. Keep provisioning operator-managed while
`spec.cluster.autoProvision` is enabled: a manual `restatectl provision` call
can race the operator, and operator 3.0.1 explicitly warns that concurrent
provisioning methods can split the cluster. Diagnose the controller call before
changing the provisioning method.

Restate Cloud's startup wrapper instead lets only pod 0 self-provision on first
boot. Operator-managed provisioning was chosen here so initialization is
driven by the custom-resource controller rather than by pod startup code.

### Pod identity details

The StatefulSet template cannot express a different static peer list or node ID
for each ordinal. The container startup command builds:

- `RESTATE_METADATA_CLIENT__ADDRESSES` from the three stable
  `restate-<ordinal>.restate-cluster.restate.svc.cluster.local:5122` names;
- `RESTATE_FORCE_NODE_ID` from the StatefulSet pod-index label.

The operator injects `POD_NAME` and a default advertised address. The manifest
adds `POD_NAMESPACE` and `POD_INDEX`, then overrides
`RESTATE_ADVERTISED_ADDRESS` with the fully qualified StatefulSet DNS form.
Kubernetes `$(VAR)` expansion in environment values is order-sensitive, so
`POD_NAMESPACE` must appear before values that reference it. Environment
entries supplied in `spec.compute.env` override operator defaults with the
same name.

## Data durability model

Each Restate pod's volume holds three kinds of data under `/restate-data`, and
they are not equally replaceable:

| Data | Role that writes it | If lost beyond the replication factor |
|---|---|---|
| Replicated log segments | `log-server` | **Data loss.** The log is the record of every invocation; nothing else reconstructs it |
| Cluster metadata (node, log, and partition configuration; service schemas) | `metadata-server`, Raft, majority of nodes | **Cluster loss.** Nodes cannot agree on cluster membership or log configuration without it |
| Partition stores (RocksDB state per partition) | `worker` | **Recoverable.** Rebuilt from the latest snapshot in the bucket plus replay of the log after it |

With node replication `2` on three nodes, losing one node's volume loses
nothing; losing two volumes at once loses log records that had not yet been
covered by a snapshot, and can lose the metadata Raft majority. Partition
snapshots in S3 exist to speed up that rebuild and to let the log be trimmed;
they are not a backup of the cluster. There is no supported backup and restore
procedure for a Restate cluster today. Protecting the EBS volumes is therefore
the operator's first duty: the `Retain` reclaim policy, encryption, and a
deliberate teardown order are what this repository provides toward it.

### Recommendation: keep metadata out of the volumes

Restate can store cluster metadata in Amazon S3 instead of the built-in Raft
`metadata-server` role, and also supports DynamoDB (Restate 1.5.4 and later)
and etcd; see the
[metadata storage documentation](https://docs.restate.dev/server/metadata).
For a deployment whose data matters, we strongly recommend the object-store
provider on AWS:

- it removes the one piece of irreplaceable state that would otherwise share a
  volume with the log, and the object store's durability replaces the Raft
  majority as the thing that has to survive;
- it makes the object store a day-one dependency instead of something that can
  be deferred. A cluster with the replicated metadata store starts and serves
  traffic with no object store and no snapshots configured at all, but its log
  is then never trimmed, and the volumes fill up later with no warning that
  anything was missing;
- the provider is chosen at initial deployment. Migrating from replicated to
  an external store later is supported, but it stops invocation processing for
  the duration of the migration.

The configuration change in `resources/04-restate-cluster.yaml` is to remove
`metadata-server` from `roles` and add, next to the snapshot destination:

```toml
[metadata-client]
type = "object-store"
path = "s3://<snapshots-bucket>/restate/metadata"
aws-region = "<region>"
```

The IAM policy in `resources/01-restate-snapshots-iam-policy.json` grants
bucket-wide object read, write, and delete, which is what the provider uses.
This repository's validation covers the replicated store only; test the
object-store configuration before adopting it. Only Amazon S3 is
supported for metadata; S3-compatible stores such as MinIO are supported for
snapshots but not for metadata, and the bucket must be in the same region as
the cluster because metadata latency affects cluster operations directly.
Outside AWS, the equivalent is etcd; GCS and Azure Blob are snapshot
destinations only.

This repository still ships the replicated metadata store because it is what
the source profile runs and what was validated end to end here. Treat the
switch as a decision to make before the first `RestateCluster` apply, not a
later tuning step.

## Storage and snapshots

Each Restate pod receives a 1 TiB PVC using the repository-owned
`restate-gp3` StorageClass:

- EBS CSI provisioner;
- encrypted XFS;
- 6000 IOPS and 500 MiB/s;
- `WaitForFirstConsumer`, so the volume is provisioned in the pod's zone;
- `Retain`, so deleting the PVC does not delete the EBS PV.

`Retain` is a safety net, not an automatic restore process. A Released PV keeps
its former claim reference and must be handled explicitly during recovery.

Partition snapshots are written to:

```text
s3://<dedicated-bucket>/restate/snapshots/
```

The prefix is the same in every installation because the namespace is
`restate`. A snapshot repository belongs to exactly one Restate cluster, so the
bucket must be dedicated to this deployment unless the prefix is deliberately
made cluster-specific in both IAM and Restate configuration.

## IAM for snapshots

The default credential path is IRSA:

1. the EKS cluster's IAM OIDC provider establishes the issuer;
2. a cluster-qualified IAM role trusts only
   `system:serviceaccount:restate:restate`;
3. the role receives the least-privilege S3 policy from
   `resources/01-restate-snapshots-iam-policy.json`;
4. the operator-created ServiceAccount receives the role ARN annotation;
5. the AWS SDK in Restate exchanges its projected token through STS.

The operator can also create an EKS Pod Identity association, matching Restate
Cloud, but this repository does not automate that IAM path. Adapting the
reference requires all of the following:

1. the EKS Pod Identity Agent running on every eligible node;
2. the
   [ACK EKS controller](https://github.com/aws-controllers-k8s/eks-controller)
   and its CRDs;
3. an IAM role whose trust grants `sts:AssumeRole` and `sts:TagSession` to the
   `pods.eks.amazonaws.com` service principal;
4. the operator Helm value `awsPodIdentityAssociationCluster`;
5. `security.awsPodIdentityAssociationRoleArn` instead of the IRSA ServiceAccount
   annotation.

Adapting the repository's IRSA-only role for Pod Identity requires changing its
trust policy: `sts:AssumeRoleWithWebIdentity` against the cluster OIDC issuer is
not a Pod Identity trust. The Pod Identity field also causes the operator to
allow egress to the agent at `169.254.170.23:80`.

## SDK service revision lifecycle

A `RestateDeployment` is not a thin wrapper around a Kubernetes Deployment.
For every distinct pod template, the operator creates a versioned ReplicaSet
and Service, registers that endpoint with Restate, and keeps the old revision
alive while any invocation remains pinned to it.

This is why the container port must be named `restate`, and why old ReplicaSets
need time to drain rather than being treated as ordinary rollout debris. The
complete update, drain, and rollback workflow is in
[Deploying services](03-deploying-services.md).

## Invariants to preserve

When changing the manifests, preserve these relationships or update every
consumer together:

- `RestateCluster` name, generated namespace, service DNS, network-peer labels,
  and IAM subject all assume the name `restate`.
- The replica count, `REPLICAS` environment value, generated peer list, and
  scheduling capacity must agree.
- The IAM policy bucket and snapshot destination bucket must be identical.
- The StorageClass name in `resources/03-gp3-storageclass.yaml` and
  `spec.storage.storageClassName` must match.
- Keep port 9070 private unless a suitable authentication and authorization
  boundary protects it.
- Experimental runtime settings are pinned to Restate `1.7.7` and must be
  revalidated during an upgrade.

The rationale for values copied or adapted from Restate Cloud is recorded in
[Profile fidelity](04-profile-fidelity.md).
