# Fidelity to the `3-node.xlarge-vqueues` profile

`resources/04-restate-cluster.yaml` is a translation of the Restate Cloud
profile `3-node.xlarge-vqueues` (`restate-cloud/config/profiles.json`, rendered
by `restate-clusters.ts`). This doc records what was kept, moved, and dropped —
read it before "fixing" anything in the cluster manifest that looks unusual.

This is a maintenance record, not an installation guide. The
[Architecture](00-architecture.md) explains the resulting system; this file
preserves the relationship to the source profile so later changes remain
intentional. A customer performing a standard installation can skip it.

## Kept 1:1

- **Image pin** `docker.restate.dev/restatedev/restate:1.7.7` — the profile's
  `restateImageOverride`. The `RESTATE_EXPERIMENTAL_*` flags are validated
  against exactly this version; revisit them on any upgrade.
- **Sizing**: 3 replicas × requests 24 CPU / 50 Gi. Limits are **memory-only on
  purpose** (the profile expresses "no CPU limit"): Restate may burst above 24
  cores when the node has headroom. Don't add a CPU limit.
- **All tuning env vars**: rocksdb memory/log/perf/write-rate-cap,
  deletion-triggered partition-store compaction, bifrost record cache and read
  path, node-to-node stream window, ingress stream limit, invoker fan-out
  (20k concurrent invocations × 1 MiB initial buffer), query engine, journal
  retention, snapshot cadence (100k records / 5m / 2 retained). Memory budget
  inside the 50 Gi limit: 20 GiB rocksdb (≤60% of it memtables) + 3 GiB
  bifrost cache + 6 GiB invoker + 4 GiB query engine = 33 GiB accounted, rest
  is unaccounted-overhead headroom.
- **vqueues + scoped virtual objects** (`RESTATE_EXPERIMENTAL_ENABLE_VQUEUES`
  / `…_SCOPED_VIRTUAL_OBJECTS`): enabled together — scoped VOs build on
  vqueues and share their storage format.
- **Scheduling**: required hostname anti-affinity + preferred zone spread; the
  `cloud.restate.dev/interruptible` toleration (inert unless you taint nodes
  with it).
- **Storage**: 1 TiB gp3 per node.

## Moved, same effect

- `default-num-partitions = 48` and `default-replication = { node = 2 }` are
  set in the config TOML instead of env vars — cloud computes them at render
  time; folding them into the TOML reads better. Same effective config.

## Dropped (cloud-control-plane machinery)

- node-state-control readiness-gate sidecar (`nodeStateManagement`)
- request-signing private key via the AWS Secrets Store CSI provider
- restate-cloud-ingress network peers, `AWS_EXTERNAL_ID`, storage accounting
- `NODE_IP` env (part of cloud's shared rendering; nothing in this manifest
  consumes it)

## Adapted

- Bootstrap: cloud's startup wrapper lets pod 0 self-provision on first boot;
  here the container command keeps only the address-list / node-id derivation
  and the **operator** provisions the cluster
  (`spec.cluster.autoProvision: true` + `auto-provision = false` in the
  TOML) — see [Architecture](00-architecture.md#cluster-bootstrap-sequence).
- IAM: cloud uses operator-managed EKS Pod Identity; this repo implements IRSA.
  The adaptation requirements for Pod Identity are documented, but the supplied
  IAM and Terraform paths do not automate them.
- StorageClass: cloud's gp3 class is `encrypted` + `xfs` at baseline gp3
  performance (3000 IOPS / 125 MiB/s) with `reclaimPolicy: Delete`; this repo
  keeps encryption and xfs but provisions 6000 IOPS / 500 MiB/s up front and
  uses `reclaimPolicy: Retain` — deleting the RestateCluster deletes its
  namespace and PVCs, and without Retain the EBS data volumes would go with
  them (cloud accepts Delete because its control plane owns cluster
  decommissioning end to end). The class is also named `restate-gp3` rather
  than cloud's `gp3`: on a shared cluster a generic `gp3` class often already
  exists, StorageClass parameters are immutable (applying over it fails), and
  a scoped name keeps other workloads off a class this stack owns.
- NetworkPolicy: cloud exposes ingress **and admin** only to its own
  authenticating gateway namespace; this repo opens ingress to `restate-apps`
  and keeps the unauthenticated admin API closed to workloads entirely
  (port-forward is the ops path). Cloud has no equivalent of our
  `restate-apps` inbound lockdown — its SDK services live outside the cell.
- Service-CIDR egress (`resources/06-restate-service-cidr-egress.yaml`) has no
  counterpart in the profile: it is an EKS artifact, not a Restate setting.
  Where the VPC CNI enforces NetworkPolicy it evaluates egress before Service
  DNAT, so the operator's pod-label rule does not cover the ClusterIP it
  registers each service revision under. Cloud does not hit this because its
  SDK services live outside the cell entirely.
- `AWS_REGION` is set explicitly here; cloud leaves region resolution to the
  node's IMDS (its nodes allow pod IMDS access, hop limit 2 — yours might
  not).
- Provenance label on the CR: `based-on-profile: 3-node.xlarge-vqueues`.

The profile's RocksDB write-rate cap remains `1200 MiB/s`. It is an upper bound
on RocksDB's internal pacing, not a cap below the configured EBS throughput;
the 500 MiB/s volume is the effective ceiling in this reference deployment.

## Coupled settings

Review these values together rather than editing one in isolation:

| Change | Also review |
|---|---|
| Restate image | Every `RESTATE_EXPERIMENTAL_*` flag, config-key compatibility, and `restatectl` commands |
| Replica count | `REPLICAS`, generated peer list, scheduling capacity, and failure tolerance |
| Memory limit | RocksDB, Bifrost, invoker, query-engine budgets, and runtime overhead |
| Storage performance | RocksDB pacing, compaction behavior, EBS limits, and cost |
| Cluster name/namespace | Stable DNS, IAM trust subject, network-peer label, and snapshot prefix |
| Snapshot bucket/prefix | Restate destination, IAM resources, and one-cluster repository invariant |

## Change procedure

For a profile-derived change:

1. classify it as kept, moved, dropped, or adapted;
2. verify it against the intended source profile and target Restate version;
3. update the canonical file under `resources/` without stripping its comments;
4. update this record when the relationship to the source profile changes;
5. validate both deployment paths;
6. test the change outside production and verify snapshots and cluster health.

For a live version change, also follow the
[upgrade checklist](05-operations.md#upgrade-restate-or-the-operator).
