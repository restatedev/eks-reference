# Deploying services

How SDK services (the code Restate invokes) get deployed, versioned, and
drained with the operator's `RestateDeployment` resource —
`resources/05-restate-compute.yaml` is the skeleton. Operator behavior below
was verified against the restate-operator source (chart v3.0.1); the Restate
side is [docs.restate.dev/services/versioning](https://docs.restate.dev/services/versioning).

## Why not a plain Deployment

Restate pins every in-flight invocation to the exact code version it started
on: a registered deployment is **immutable**, new invocations go to the
latest deployment of a service, and retries of a running invocation always
replay against the version that started it — a journal recorded by v1 must
never be replayed against v2's code. A plain Kubernetes `Deployment` breaks
this: a rolling update tears down the old pods while they may still own
journaled, in-flight (possibly hours-long) invocations.

`RestateDeployment` is a Deployment-alike that makes rollouts
version-faithful: old code keeps running until nothing is pinned to it.

## What the operator does per revision

For every distinct pod template it sees, the operator:

1. computes a template hash and creates a **versioned ReplicaSet + Service**
   pair named `<name>-<hash>` (the CR name stays stable; revisions live next
   to each other),
2. **registers** `http://<name>-<hash>.<namespace>:<port>` with the cluster's
   admin API — this is why the container port must be **named `restate`**,
   and why registration is per-revision: each revision is its own immutable
   Restate deployment,
3. records the resulting deployment id on the ReplicaSet
   (`restate.dev/deployment-id` annotation) and on the CR
   (`status.deploymentId` for the latest revision),
4. labels the pods `allow.restate.dev/<cluster>: "true"` so the cluster's
   egress NetworkPolicy lets Restate call them (see
   [architecture](00-architecture.md#cross-namespace-networking)).

Rolling out a new image is just `kubectl apply` with a changed template: a
new ReplicaSet + Service + registration appear, new invocations flow to the
new revision, and the old revision enters the drain lifecycle below.

## Draining old revisions

On every reconcile the operator asks the cluster which registered deployments
are still **active**, via a SQL query against the admin API: a deployment is
active if it is the latest version of some service (`sys_service`) **or** any
not-yet-completed invocation is pinned to it (`sys_invocation_status`). Then,
per old revision:

- **Still active** → left alone at full replicas, no matter how old.
  A long-running workflow keeps its code alive.
- **Just went inactive** → stamped with a removal time of now +
  `spec.restate.drainDelaySeconds` (default 300). If it becomes active again
  inside the window, the stamp is removed — the timer resets.
- **Past the removal time** → scaled to **0 replicas**. The empty ReplicaSet
  is kept for rollback, up to `spec.revisionHistoryLimit` (default 10) —
  beyond that, oldest first, the operator force-removes the deployment from
  Restate and deletes the ReplicaSet + Service.

Deleting the whole `RestateDeployment` is graceful in the same way: a
finalizer blocks deletion until every revision has drained and sat out its
delay, then everything is deregistered and removed. (If the target
RestateCluster itself is gone, deletion proceeds immediately.)

**Rollback** is re-applying a previous pod template: the hash matches the
retained ReplicaSet, which is scaled back up and becomes the latest
registered deployment again — no image rebuild, no new revision.

## Observing it

```bash
kubectl -n restate-apps get restatedeployments -o wide   # replicas + deployment id
kubectl -n restate-apps get rs,svc                       # one pair per live revision
kubectl -n restate-apps get rs -o custom-columns=\
'NAME:.metadata.name,REPLICAS:.spec.replicas,REMOVE-AT:.metadata.annotations.restate\.dev/remove-version-at'
```

And from the Restate side (port-forward from the [runbook](02-runbook.md)
step 6, or `kubectl exec`):

```bash
restate deployments list                  # every registered revision
restate deployment describe <id> --extra  # what's still pinned to it
```

A revision that refuses to scale down is not stuck — it still has pinned
invocations. `describe --extra` shows them; they finish, get cancelled, or
get killed, and the drain proceeds.

## Knobs

| Field | Default | Meaning |
|---|---|---|
| `spec.replicas` | 1 | pods for the **latest** revision (older active revisions keep the value they had) |
| `spec.restate.drainDelaySeconds` | 300 | hold time between "nothing pinned" and scale-to-zero |
| `spec.revisionHistoryLimit` | 10 | zero-scaled ReplicaSets kept for rollback |
| `spec.minReadySeconds` | 0 | as on a native Deployment |
| `spec.autoscaling` | — | HPA template the operator manages per revision, scoped to that revision's pods (old draining revisions don't pollute the metrics) |
