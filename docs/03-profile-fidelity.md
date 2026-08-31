# Fidelity to the `3-node.xlarge` profile

`resources/04-restate-cluster.yaml` is a translation of the Restate Cloud
profile `3-node.xlarge` (`restate-cloud/config/profiles.json`, rendered
by `restate-clusters.ts`). This doc records what was kept, moved, and dropped —
read it before "fixing" anything in the cluster manifest that looks unusual.

## Kept 1:1

- **Image pin** `docker.restate.dev/restatedev/restate:1.7.4` — the profile's
  `restateImageOverride`. The `RESTATE_EXPERIMENTAL_*` flags are validated
  against exactly this version; revisit them on any upgrade.
- **Sizing**: 3 replicas × requests 24 CPU / 50 Gi. Limits are **memory-only on
  purpose** (the profile expresses "no CPU limit"): Restate may burst above 24
  cores when the node has headroom. Don't add a CPU limit.
- **All tuning env vars**: rocksdb memory/log/perf, bifrost record cache and
  read path, invoker limits, query engine, journal retention, snapshot cadence
  (100k records / 5m / 2 retained). Memory budget inside the 50 Gi limit:
  10 GiB rocksdb + 3 GiB bifrost cache + 6 GiB invoker + 4 GiB query engine =
  23 GiB accounted, rest is unaccounted-overhead headroom.
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
- `NODE_IP` env and the vqueues env vars (this profile is the non-vqueues
  variant)

## Adapted

- Bootstrap: cloud's `startup.sh` lets pod 0 auto-provision on first boot;
  here the startup script keeps only the address-list / node-id derivation
  and provisioning is an explicit one-time `restatectl provision`
  (`auto-provision = false` in the TOML) — see
  [architecture](02-architecture.md#replicated-metadata-bootstrap).
- IAM: cloud uses operator-managed EKS Pod Identity (needs the ACK EKS
  controller); this repo defaults to IRSA, with the Pod Identity path
  documented as the alternative.
- Provenance label on the CR: `based-on-profile: 3-node.xlarge`.
