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

Both deployment paths finish with the Restate cluster installed. Neither the
runbook nor the Terraform modules deploy your services: a service changes at
your application's cadence, from your application's pipeline, and does not
belong in the state that owns the cluster. Apply the manifest below with
`kubectl`, or fold it into whatever already ships your applications.

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
| `False` | `ReplicaSetScaling`, `ReplicaSetPodNotReady`, `ReplicaSetPodNotAvailable`, `ReplicaSetNoStatus` | Pods still starting; normal during a rollout |
| `False` | `AdminCallFailed` | Admin API unreachable or returned a server error; the operator retries |
| `False` | `AdminCallRejected` | Restate refused the registration; the message carries Restate's error and the operator retries every 30 s but will not succeed until the template changes |
| `False` | `HashCollision`, `FailedReconcile` | Operator-side error; inspect the operator logs |

The operator also publishes a Warning Event with the same message for
`AdminCallFailed` and `AdminCallRejected`, so `kubectl describe
restatedeployment <name>` shows the reason without reading logs.

Verified on operator `3.0.1`: changing `Greeter` from a Service to a Virtual
Object was rejected by Restate with `META0006`, the condition and Event carried
that text within about 15 seconds, the previous revision kept serving traffic,
and the new pods ran unregistered until the template was corrected.

### Terraform

The `kubernetes_manifest` `wait` block matches only positive states: a
condition reaching a value, a field matching a regex, or a rollout completing
for the built-in workload kinds. It cannot fail on `Ready=False`, so a rejected
revision makes `terraform apply` block until its timeout and then report
`context deadline exceeded` without Restate's reason.

If a `RestateDeployment` is applied from Terraform anyway, set an update
timeout well under the default, print the condition on failure, and read the
reason from the resource rather than from Terraform:

```bash
kubectl -n restate-apps get restatedeployment <name> \
  -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status} {.reason}: {.message}{"\n"}{end}'
```

State is not left inconsistent: the provider keeps the previous manifest in
state when the wait fails, so the next plan already proposes the rollback.

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
    if obj.metadata.generation ~= nil and obj.status.observedGeneration ~= nil
       and obj.status.observedGeneration < obj.metadata.generation then
      hs.message = "Waiting for the operator to observe the latest generation"
      return hs
    end
    if obj.status.conditions ~= nil then
      for _, c in ipairs(obj.status.conditions) do
        if c.type == "Ready" then
          if c.status == "True" then
            hs.status = "Healthy"
            hs.message = c.message or "Deployed"
          elseif c.reason == "AdminCallRejected" then
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

With this in place, a sync of a rejected revision fails its health check within
one reconcile instead of waiting on a timeout, and the previous revision keeps
serving because the operator never replaced it. Teams that deploy the cluster
stages with Terraform and the applications with Argo CD get the boundary this
guide recommends without giving up automated health gating.

### Flux

Flux's health checks use kstatus, which treats a `Ready=False` condition as
still reconciling and reports failure only on a `Stalled=True` condition. The
operator does not set `Stalled`, so a rejected revision keeps a Flux
`Kustomization` in progress until its `timeout`. Set that timeout to a few
minutes and read the `Ready` reason as above to see why.

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
