# Deploying SDK services

Restate invokes application code through SDK service endpoints. In this
reference deployment those services run in namespace `restate-apps` as
`RestateDeployment` custom resources rather than plain Kubernetes Deployments.

Start from `resources/05-restate-compute.yaml`, but treat it as a lifecycle
example—not a complete production application template.

The operator behavior below was verified against chart `3.0.1`. For the
Restate-side compatibility model, see
[Service versioning](https://docs.restate.dev/services/versioning).

## Why RestateDeployment exists

Restate pins an in-flight invocation to the exact code deployment on which it
started. Retries replay the journal against that same code. Replacing all old
pods during an ordinary Kubernetes rolling update can therefore remove code
that long-running invocations still require.

`RestateDeployment` gives each pod-template revision its own immutable
ReplicaSet and Service. New invocations use the latest registered revision;
old code remains available until nothing is pinned to it.

```text
RestateDeployment/service
  ├─ revision A: ReplicaSet + Service ── old invocations remain pinned here
  └─ revision B: ReplicaSet + Service ── latest; receives new invocations
```

## Minimum contract

Every SDK service template must satisfy these requirements:

| Requirement | Why |
|---|---|
| Namespace `restate-apps` | Matches the repository's ownership and NetworkPolicy model |
| `spec.restate.register.cluster: restate` | Selects the `RestateCluster` to register with |
| Container listens on port 9080 | Default Restate SDK endpoint port used here |
| Container port is named `restate` | The operator uses the named port to build the registration URL |
| Stable selector and matching pod labels | Required for Kubernetes workload ownership |
| Immutable/reproducible image reference | A revision must continue serving the same code while pinned work drains |

Prefer an image digest or an immutable release tag. Reusing a mutable tag can
change the code behind an existing template without creating the revision
boundary Restate expects.

## First deployment

Edit `resources/05-restate-compute.yaml` and replace
`REPLACE_ME_SERVICE_IMAGE`. Add the application-specific settings that the
skeleton deliberately omits, such as:

- environment and Secret references;
- image pull credentials;
- readiness/liveness probes appropriate for the SDK runtime;
- resource requests and limits based on measurements;
- pod security context and scheduling constraints;
- autoscaling, if required.

Review and apply:

```bash
grep -n 'REPLACE_ME' resources/05-restate-compute.yaml
kubectl diff -f resources/05-restate-compute.yaml
kubectl apply -f resources/05-restate-compute.yaml
kubectl -n restate-apps get restatedeployment service -w
```

Inspect the resulting revision:

```bash
kubectl -n restate-apps get restatedeployments -o wide
kubectl -n restate-apps get pods,replicasets,services
kubectl -n restate-operator logs deploy/restate-operator --tail=100
```

## What the operator creates

For each distinct pod template, the operator:

1. hashes the template and creates a versioned ReplicaSet and Service pair
   named `<name>-<hash>`;
2. builds `http://<name>-<hash>.<namespace>:<port>` from that Service and the
   container port named `restate`;
3. registers that endpoint with the selected Restate cluster's admin API;
4. records the deployment ID as the ReplicaSet annotation
   `restate.dev/deployment-id` and as `status.deploymentId` on the custom
   resource for the latest revision;
5. labels the pods `allow.restate.dev/<cluster>: "true"`, allowing the Restate
   namespace's egress policy to invoke them.

Registration is per revision. A service name may therefore have multiple
registered deployments while old invocations drain.

## Roll out a new version

Change the pod template—normally the image—and apply the resource again:

```bash
kubectl diff -f resources/05-restate-compute.yaml
kubectl apply -f resources/05-restate-compute.yaml
kubectl -n restate-apps get restatedeployment service -w
```

Watch both revisions and the Restate registration state:

```bash
kubectl -n restate-apps get replicasets,services

# With the runbook port-forward active:
restate deployments list
```

A successful rollout means:

- the new revision has Ready pods;
- the operator registered it;
- new invocations select it;
- the old revision stays available for pinned invocations.

Do not use `kubectl rollout restart` against the generated ReplicaSets or edit
them directly. Change the `RestateDeployment` template and let the operator
reconcile its children.

## Draining old revisions

On each reconcile, the operator queries the Restate admin API for registered
deployments that are still active. The activity definition is precise: a
deployment is active when it is the latest version of at least one service in
`sys_service` **or** when at least one not-yet-completed invocation in
`sys_invocation_status` is pinned to it.

| Revision state | Operator action |
|---|---|
| Still active | Keeps the revision at its configured replica count |
| Just became inactive | Adds a removal time of now plus `drainDelaySeconds` |
| Becomes active during the delay | Removes the timestamp and resets draining |
| Inactive beyond the delay | Scales the ReplicaSet to zero |
| Exceeds `revisionHistoryLimit` | Oldest first, force-removes the Restate deployment and deletes its ReplicaSet and Service |

The default drain delay is 300 seconds. A long-running invocation can keep an
old revision alive for hours or days; that is correct behavior.

Observe replicas and removal timestamps directly:

```bash
kubectl -n restate-apps get replicasets -o custom-columns=\
'NAME:.metadata.name,REPLICAS:.spec.replicas,REMOVE-AT:.metadata.annotations.restate\.dev/remove-version-at'
```

Diagnose a revision that remains active:

```bash
restate deployments list
restate deployment describe <deployment-id> --extra
```

Pinned invocations must finish, be cancelled, or be killed through an explicit
Restate operational decision before the revision can drain. Do not delete the
ReplicaSet to force progress.

## Roll back

Rollback means reapplying a previous pod template. If its retained revision is
still within `revisionHistoryLimit`, the template hash matches the old
ReplicaSet; the operator scales it up and registers it as the latest revision
again.

A Git-based workflow is the safest way to make the rollback exact:

1. restore the previous `RestateDeployment` pod template from a known commit;
2. inspect `kubectl diff`;
3. apply the restored manifest;
4. wait for the old revision to become Ready and registered;
5. confirm new traffic reaches the restored version.

Rolling back application code does not roll back completed Restate state or
external side effects. Application compatibility remains your responsibility.

## Scale and autoscale

`spec.replicas` controls pods for the latest revision. Older active revisions
keep the replica count they had when created so pinned work remains available.

The operator can manage an HPA per revision through `spec.autoscaling`. Each
HPA selects only its revision's pods; metrics from a draining version do not
affect the latest version.

Test scaling behavior with real invocation load. The example request of 1 CPU
and 1 GiB is a placeholder, not sizing guidance.

## Delete a service

Deleting a `RestateDeployment` is graceful. Its finalizer blocks deletion until
every revision is inactive and has completed its drain delay, then the operator
deregisters every revision and removes its ReplicaSets and Services.

```bash
kubectl delete -f resources/05-restate-compute.yaml
kubectl -n restate-apps get restatedeployments,replicasets,services -w
```

An object that remains `Terminating` is usually waiting for pinned invocations,
not stuck. Inspect the Restate deployment before considering finalizer changes.
If the target `RestateCluster` no longer exists, the operator permits immediate
cleanup because it cannot query or drain through that cluster.

## Useful fields

| Field | Default | Meaning |
|---|---:|---|
| `spec.replicas` | 1 | Pods for the latest revision |
| `spec.restate.register.cluster` | required here | Restate cluster that receives registration |
| `spec.restate.drainDelaySeconds` | 300 | Delay between becoming inactive and scaling to zero |
| `spec.revisionHistoryLimit` | 10 | Zero-scaled revisions retained for rollback |
| `spec.minReadySeconds` | 0 | Minimum Ready time, matching native Deployment semantics |
| `spec.autoscaling` | unset | Per-revision HPA configuration managed by the operator |

## Troubleshooting

If the latest revision never becomes Ready:

```bash
kubectl -n restate-apps describe restatedeployment service
kubectl -n restate-apps get pods,replicasets,services
kubectl -n restate-apps describe pod <pod>
kubectl -n restate-apps logs <pod> --tail=200
kubectl -n restate-operator logs deploy/restate-operator --tail=200
```

Check image pulls, container startup, the named `restate` port, cluster
reference, operator-to-admin connectivity, and Restate-to-service NetworkPolicy.
The broader symptom guide is in
[Operations and troubleshooting](05-operations.md#troubleshooting-by-symptom).
