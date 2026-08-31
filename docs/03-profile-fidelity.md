# Fidelity to the `3-node.xlarge-vqueues` profile

`resources/04-restate-cluster.yaml` is a translation of the Restate Cloud
profile `3-node.xlarge-vqueues` (`restate-cloud/config/profiles.json`, rendered
by `restate-clusters.ts`). This doc records what was kept, moved, and dropped —
read it before "fixing" anything in the cluster manifest that looks unusual.

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
  TOML) — see [architecture](02-architecture.md#replicated-metadata-bootstrap).
- IAM: cloud uses operator-managed EKS Pod Identity (needs the ACK EKS
  controller); this repo defaults to IRSA, with the Pod Identity path
  documented as the alternative.
- StorageClass: cloud's gp3 class is `encrypted` + `xfs` at baseline gp3
  performance (3000 IOPS / 125 MiB/s); this repo keeps encryption and xfs but
  provisions 6000 IOPS / 500 MiB/s up front.
- `AWS_REGION` is set explicitly here; cloud leaves region resolution to the
  node's IMDS (its nodes allow pod IMDS access, hop limit 2 — yours might
  not).
- Provenance label on the CR: `based-on-profile: 3-node.xlarge-vqueues`.
