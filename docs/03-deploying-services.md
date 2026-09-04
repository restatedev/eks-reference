# Deploying SDK services

Restate invokes application code through SDK service endpoints. In this
reference deployment those services run in namespace `restate-apps` as
`RestateDeployment` custom resources rather than plain Kubernetes Deployments.

This guide is an application/platform-team handoff. If your responsibility is
only to install the Restate cluster, the installation completion checklist is
your handoff point; share this document with the team that owns the application
image, configuration, scaling, and rollout. Apply the example after replacing
its image placeholder.

Start from `resources/05-restate-compute.yaml`, but treat it as a lifecycle
example—not a complete production application template. This repository ships
no service image. Build one from the
[Restate SDK examples](https://github.com/restatedev/examples) in the language
your team uses; any image whose SDK endpoint listens on port 9080 fits the
manifest unchanged.

Both deployment paths finish with the Restate cluster installed. A service
changes at your application's cadence and should not share the state that owns
the cluster. Apply the manifest below with `kubectl`, fold it into your existing
delivery system, or use the optional `terraform/03-services` example in its own
state.

That is a boundary of the deployment paths, not of the operator. The operator
installed in stage 01 reconciles `RestateDeployment` resources the same way it
reconciles the cluster — revisioning, registration, and draining are its job,
described below. Upstream references for the same model:

- [operator service examples](https://github.com/restatedev/restate-operator/tree/main/examples/services/greeter)
  — a working `RestateDeployment`, plus a Knative variant
  ([`replicaset-v1.yaml`](https://github.com/restatedev/restate-operator/blob/main/examples/services/greeter/k8s/replicaset-v1.yaml));
- [Restate on Kubernetes](https://docs.restate.dev/deploy/services/kubernetes);
- [restate-operator](https://github.com/restatedev/restate-operator) — the
  operator itself, including its CRD reference.

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

Make rollout changes through the `RestateDeployment` template and let the
operator reconcile its generated ReplicaSets. This preserves the revision
lifecycle that a direct edit or `kubectl rollout restart` would bypass.

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
Restate operational decision before the revision can drain. Allow that process
to finish rather than deleting the ReplicaSet to force progress.

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

`spec.autoscaling` does **not** autoscale the latest revision. In ReplicaSet
mode, the operator uses that template to create one HPA for each non-latest
revision that still has active invocations, allowing old capacity to shrink as
work drains. It injects `scaleTargetRef`; provide the remaining HPA fields such
as `minReplicas`, `maxReplicas`, and `metrics`. The minimum is floored at one.

To autoscale the latest revision, create a separate application-owned HPA whose
`scaleTargetRef` targets `restate.dev/v1beta1`, kind `RestateDeployment`, and
this resource's name. Keep that HPA in the application pipeline, not in the
cluster Terraform state.

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

This was verified on 2026-09-01 against a live cluster with no in-flight
invocations: the finalizer drained the revision and the operator removed the
ReplicaSet, Services, and pods, leaving the namespace empty without manual
intervention.

Deletion always takes at least `drainDelaySeconds` (300 seconds by default)
even when no invocation is in flight, because the latest revision only becomes
inactive when it is deregistered and then waits out its drain delay like any
other. Budget for that in pipelines that delete and recreate services.

An object that remains `Terminating` is usually waiting for pinned invocations,
not stuck. Inspect the Restate deployment before considering finalizer changes.
If the target `RestateCluster` no longer exists, the operator permits immediate
cleanup because it cannot query or drain through that cluster.

## Team isolation

A Restate cluster is one trust domain. Every service registered with it can
invoke every other service through the cluster, regardless of which namespace
the services run in or who deployed them: the NetworkPolicies in this
repository control which pods may reach Restate's ingress and which may reach
SDK pods directly, but service-to-service calls travel through Restate itself,
which does not authorize them. Service names are also cluster-global, so two
teams cannot both register a service called `Greeter`.

Sharing one Restate cluster is therefore appropriate for teams that already
trust each other's code. Teams or applications that must not be able to call
into each other belong on separate `RestateCluster`s, and should talk to each
other the way any external client does: through the other cluster's ingress,
behind the authenticating layer described under
[Making the playground work for a team](05-operations.md#making-the-playground-work-for-a-team).

The manifests in this repository assume a single cluster named `restate`; the
[invariants list](00-architecture.md#invariants-to-preserve) enumerates what
that name is wired into. A second cluster needs its own name and generated
namespace, its own snapshot bucket and IAM role, and a copy of the
`restate-apps` isolation policy for its own service namespace.

## Health signals for delivery tools

A `RestateDeployment` reports one `Ready` condition. Delivery tools need to
read it, because a rejected revision looks healthy at the pod level: the new
pods run and pass their probes, and only the condition says that Restate
refused to register them.

| `Ready` | Reason | Meaning |
|---|---|---|
| `True` | `Deployed` | Latest revision registered and serving new invocations |
| `False` | `ReplicaSetScaling`, `ReplicaSetPodNotReady`, `ReplicaSetPodNotAvailable` | Pods still starting; normal during a rollout |
| `False` | initial ReplicaSet status absent | Operator 3.0.1 may put `ReplicaSetNoStatus` in the message rather than the reason; continue waiting for pod status |
| `False` | `AdminCallFailed` | The admin request failed in transport or response decoding; the operator retries |
| `False` | `AdminCallRejected` | The admin API returned a non-success response, including a 5xx; inspect the response in the message to distinguish a transient server problem from an incompatible registration |
| `False` | `NotLatest`, `ForeignDeployment` | The revision conflicts with the deployment Restate considers current; inspect the resource, Restate deployments, and operator logs before retrying |
| `False` | `HashCollision` | The generated revision name collided; the operator retries with a new collision count |
| `False` | `RouteNotReady`, `ConfigurationNotReady` | A Knative-backed service is still reconciling |
| `Unknown` | `FailedReconcile` | The controller hit an unexpected reconciliation error; inspect the condition message and operator logs |

The operator also publishes a Warning Event with the same message for
`AdminCallFailed` and `AdminCallRejected`, so `kubectl describe
restatedeployment <name>` shows the reason without reading logs.

For example, a revision that changes a service's type from Service to Virtual
Object is rejected by Restate with `META0006`. The condition and Event carry
that message, the previous revision keeps serving traffic, and the new pods
run unregistered until the spec is corrected.

### Terraform

The `kubernetes_manifest` condition waiter compares condition type and status,
but not `status.observedGeneration`. During an update it can therefore accept
`Ready=True` from the previous generation before the operator observes the new
template. It also cannot stop early on `Ready=False` or `Unknown` with a useful
Restate reason.

The optional `terraform/03-services` root avoids this race with
`scripts/wait-restatedeployment.sh`. The script waits for
`status.observedGeneration` to equal `metadata.generation`, then requires
`Ready=True`; on timeout it prints the last reason and message. If you manage a
`RestateDeployment` in another Terraform root, use the same generation-aware
gate rather than a positive condition wait alone:

```bash
kubectl -n restate-apps get restatedeployment <name> \
  -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status} {.reason}: {.message}{"\n"}{end}'
```

### Argo CD

Argo CD has no built-in health assessment for `restate.dev` kinds and reports
unknown custom resources as Healthy. Add a health check to `argocd-cm` so a
rejected revision shows as Degraded with Restate's message, and a rollout in
progress shows as Progressing:

```yaml
data:
  resource.customizations.health.restate.dev_RestateDeployment: |
    hs = { status = "Progressing", message = "Waiting for RestateDeployment status" }
    if obj.status == nil then
      return hs
    end
    if obj.metadata.generation ~= nil and
       (obj.status.observedGeneration == nil or
        obj.status.observedGeneration < obj.metadata.generation) then
      hs.message = "Waiting for the operator to observe the latest generation"
      return hs
    end
    if obj.status.conditions ~= nil then
      for _, c in ipairs(obj.status.conditions) do
        if c.type == "Ready" then
          if c.status == "True" then
            hs.status = "Healthy"
            hs.message = c.message or "Deployed"
          elseif c.status == "Unknown" or c.reason == "ForeignDeployment"
              or c.reason == "NotLatest"
              or c.reason == "FailedReconcile" then
            hs.status = "Degraded"
            hs.message = c.message
          else
            hs.message = (c.reason or "") .. ": " .. (c.message or "")
          end
          return hs
        end
      end
    end
    return hs
```

With this in place, a controller failure or a foreign-deployment conflict shows
as Degraded within one reconcile. `AdminCallRejected` is not reliably terminal:
the operator uses it for transient 5xx responses as well as incompatible
registrations, so the check leaves it Progressing and preserves the response
details in the message. The previous revision keeps serving because the
operator never replaced it.

The health check itself has no elapsed-time rule. Bound an interactive or CI
wait explicitly so a permanent rejection cannot leave the caller waiting
indefinitely:

```bash
argocd app sync <application> --timeout 600
# For a sync that another actor started:
argocd app wait <application> --health --timeout 600
```

A CLI timeout does not repair or reclassify the revision. Inspect the
`RestateDeployment` condition, correct an incompatible specification, and
configure an alert on prolonged Progressing health for automated syncs. Teams
that deploy the cluster stages with Terraform and applications with Argo CD
retain automated health gating without treating a transient server response as
a failed release.

### Flux

Without a custom expression, Flux's kstatus handling leaves these
`Ready=False` failures in progress until the `Kustomization` timeout because
the operator does not set `Stalled=True`. Current Flux releases support
[`healthCheckExprs`](https://fluxcd.io/flux/components/kustomize/kustomizations/#health-check-expressions),
so add a generation-aware check to the application `Kustomization`:

```yaml
spec:
  wait: true
  timeout: 10m
  healthCheckExprs:
    - apiVersion: restate.dev/v1beta1
      kind: RestateDeployment
      current: >-
        has(status.observedGeneration) &&
        status.observedGeneration == metadata.generation &&
        has(status.conditions) &&
        status.conditions.exists(c,
          c.type == 'Ready' && c.status == 'True')
      failed: >-
        has(status.observedGeneration) &&
        status.observedGeneration == metadata.generation &&
        has(status.conditions) &&
        status.conditions.exists(c,
          c.type == 'Ready' &&
          (c.status == 'Unknown' ||
           c.reason == 'ForeignDeployment' ||
           c.reason == 'NotLatest' ||
           c.reason == 'FailedReconcile'))
```

When neither expression is true, Flux continues waiting. Do not include
`AdminCallRejected` in `failed`: the operator also uses that reason for
transient 5xx responses. Keep a bounded timeout for transient scaling and
admin-connectivity failures, and inspect the `Ready` condition if it expires.

## Useful fields

| Field | Default | Meaning |
|---|---:|---|
| `spec.replicas` | 1 | Pods for the latest revision |
| `spec.restate.register.cluster` | required here | Restate cluster that receives registration |
| `spec.restate.drainDelaySeconds` | 300 | Delay between becoming inactive and scaling to zero |
| `spec.revisionHistoryLimit` | 10 | Zero-scaled revisions retained for rollback |
| `spec.minReadySeconds` | 0 | Minimum Ready time, matching native Deployment semantics |
| `spec.autoscaling` | unset | HPA template for active, non-latest draining revisions; it does not autoscale the latest revision |

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
