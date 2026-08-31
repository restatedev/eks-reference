# Architecture

How the pieces fit together, and the operator mechanics the manifests rely on.
Source of truth for operator behavior:
[restatedev/restate-operator](https://github.com/restatedev/restate-operator)
(claims below were verified against its source at chart v3.0.1).

## Topology

```
namespace: restate-operator     the operator Deployment (helm)
namespace: restate              created BY the operator from the RestateCluster CR
  ├─ StatefulSet restate        pods restate-0..2, one per node (hard anti-affinity)
  ├─ Service restate-cluster    headless; ports 8080 (ingress), 9070 (admin), 5122 (node)
  ├─ ServiceAccount restate     IRSA-annotated for S3 snapshot access
  └─ NetworkPolicies            deny-all default + carve-outs (see below)
namespace: restate-apps         ours; SDK services as RestateDeployments
```

## What the operator does with a RestateCluster

From `resources/04-restate-cluster.yaml` the operator materializes a namespace
**named after the CR** (`restate`), the StatefulSet, the headless Service, the
ServiceAccount, and the NetworkPolicies. Two behaviors the manifest depends on:

- **Env override-by-name**: the operator injects defaults (`POD_NAME` via the
  downward API, `RESTATE_ADVERTISED_ADDRESS=http://$(POD_NAME).restate-cluster:5122`,
  …); anything in `spec.compute.env` with the same name **replaces** the
  default. We override `RESTATE_ADVERTISED_ADDRESS` with the fully-qualified
  form and rely on the injected `POD_NAME`.
- **K8s `$(VAR)` expansion is order-sensitive**: `POD_NAMESPACE` is declared
  first in the env list because later values reference `$(POD_NAMESPACE)`.

## Replicated-metadata bootstrap

A replicated metadata cluster has a chicken-and-egg problem: everyone must
agree on addresses and node ids, and someone must provision — exactly once.

**Pods start and wait.** The container command in `04-restate-cluster.yaml`
(adapted from Restate Cloud's startup wrapper) computes the per-pod values a
StatefulSet's single pod template can't express as plain env:

- `RESTATE_METADATA_CLIENT__ADDRESSES` built from `REPLICAS` (all three pods'
  stable DNS names),
- a stable node id (`RESTATE_FORCE_NODE_ID = POD_INDEX + 1`) from the
  StatefulSet pod-index label.

`auto-provision = false` in the config TOML (the restate-server default is
`true`) means fresh nodes come up, form the metadata cluster, and wait.

**The operator provisions.** With `spec.cluster.autoProvision: true`, the
operator waits for the `restate-0` pod to be Running (pods only turn Ready
after provisioning, so it deliberately doesn't wait for Ready), then calls
the ProvisionCluster gRPC API on it through the headless service with no
explicit parameters — the contacted node's configured defaults apply
(`default-num-partitions = 48`, `default-replication = { node = 2 }` from the
TOML). "Already provisioned" counts as success, and the outcome is cached in
the CR's `status.provisioned`, so the call runs at most once per cluster.

The operator *requires* server self-provisioning to be off: it fails
validation unless the config TOML has `auto-provision = false` (or the env
sets `RESTATE_AUTO_PROVISION=false`). No node can ever race the operator to
initialize cluster state.

Manual fallback: `restatectl provision` against any node does the same thing
and is safe to re-run (an already-provisioned cluster is reported, never
re-initialized).

Restate Cloud's script instead lets only pod 0 auto-provision on first boot;
operator-managed provisioning was chosen here so bootstrap is driven by the
operator rather than by pod startup code.

## Cross-namespace networking

The operator denies all traffic to/from the `restate` namespace by default,
then opens: node↔node (5122), operator→admin (needed for RestateDeployment
registration), DNS, and public-internet egress (private ranges
10/8, 172.16/12, 192.168/16, 169.254/16 excluded — which is why IRSA/STS works
without extra rules).

Two directions to reason about:

- **Cluster → services (outbound invocation)**: automatic. The operator stamps
  every RestateDeployment pod with the label
  `allow.restate.dev/<cluster-name>: "true"` (here:
  `allow.restate.dev/restate`), and the cluster's egress policy matches that
  label **in any namespace**. Nothing to configure.
- **Services → cluster (inbound: invoke on 8080, admin on 9070)**: NOT
  automatic. `security.networkPeers.{ingress,admin}` in
  `04-restate-cluster.yaml` allowlists the `restate-apps` namespace.

All of this only takes effect if the CNI enforces NetworkPolicy
(see [prerequisites](01-prerequisites.md)).

One AWS-specific egress gotcha: the default egress rule allows **public IPs
only**. S3 through a *Gateway* VPC endpoint keeps working (it's routing-level;
the destination IPs stay public), but *Interface* endpoints (STS, Secrets
Manager, …) resolve to private in-VPC IPs that the deny-all egress blocks. If
your VPC has such endpoints, allowlist their IPs on the RestateCluster with
`networkEgressRules` — otherwise IRSA's STS calls silently start hitting a
blackholed endpoint. (Restate Cloud maintains exactly such an allowlist for
its STS interface endpoint.)

## RestateDeployment mechanics

`resources/05-restate-compute.yaml`. A Deployment-alike with Restate-aware
rollout semantics: each revision gets its **own ReplicaSet + Service**, is
**registered** with the cluster's admin API by the operator, and old
revisions **drain** — scaled down only once Restate reports nothing pinned
to them. The container port **must be named `restate`** — the operator
builds the registration URL from it. Full lifecycle (versioning, draining,
rollback, knobs): [deploying services](03-deploying-services.md).

## IAM for snapshots

Default here: **IRSA**. The operator creates ServiceAccount `restate`;
`security.serviceAccountAnnotations` adds `eks.amazonaws.com/role-arn`, and the
role's trust policy (created in [runbook step 2](02-runbook.md)) allows that SA.
STS endpoints are public IPs, allowed by the default egress policy.

Alternative (what Restate Cloud itself runs): **operator-managed EKS Pod
Identity**. Requires the [ACK EKS controller](https://github.com/aws-controllers-k8s/eks-controller)
in the cluster plus the operator helm value `awsPodIdentityAssociationCluster`
(commented in `resources/02-restate-operator.values.yaml`); then replace the
annotation with `security.awsPodIdentityAssociationRoleArn`. That field is also
what opens NetworkPolicy egress to the pod-identity agent at
`169.254.170.23:80` — IRSA doesn't need it.
