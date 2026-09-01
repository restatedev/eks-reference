# Operations and troubleshooting

Use this guide after the cluster has been installed. It collects the checks
that answer three practical questions:

1. Is the deployment healthy?
2. Where should I look when it is not?
3. Which changes are safe to make, and which need a recovery plan?

For installation, use the [manual runbook](02-runbook.md) or the
[Terraform guide](../terraform/README.md). For SDK service rollout behavior,
use [Deploying services](03-deploying-services.md).

For an installation handoff, run the [five-minute health
check](#five-minute-health-check), [verify the snapshot
path](#verify-the-snapshot-path), and confirm the [network
boundary](#verify-the-network-boundary). The remaining sections are day-two
reference material and can be read when needed.

## What healthy looks like

| Layer | Healthy state |
|---|---|
| Operator | Deployment available in `restate-operator`; no repeating reconcile errors |
| RestateCluster | `status.provisioned=true` and `Ready=True` |
| Restate pods | `restate-0`, `restate-1`, and `restate-2` are Running and Ready on different nodes |
| Storage | Three Bound PVCs backed by `restate-gp3` PVs |
| Restate | `restatectl status` reports all nodes and partitions healthy |
| Snapshots | A manual snapshot succeeds and objects appear under `restate/snapshots/` in the dedicated bucket |
| SDK services | `RestateDeployment` is Ready and its latest revision is registered |
| Network boundary | `svc/restate` remains ClusterIP; NetworkPolicies exist and the CNI enforces them |

## Five-minute health check

The commands in this guide use these variables (`BUCKET` only for the
snapshot checks, `CLUSTER`/`REGION` only for the network-boundary checks):

```bash
export CLUSTER=...  REGION=...  BUCKET=...

kubectl get restatecluster restate -o wide
kubectl get restatecluster restate \
  -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{"  "}{.message}{"\n"}{end}'

kubectl -n restate get pods -o wide
kubectl -n restate get pvc
kubectl -n restate get svc,networkpolicy

kubectl -n restate exec restate-0 -- restatectl status
kubectl -n restate-apps get restatedeployments -o wide
```

The three Restate pods should be on distinct nodes. A Pending pod is usually a
capacity, anti-affinity, taint, or EBS provisioning problem—not a slow Restate
bootstrap.

## Admin and ingress access

The admin API on port 9070 is unauthenticated and grants full cluster control.
It is intentionally not exposed outside the cluster or to application
workloads. Reach it through a local port-forward:

```bash
kubectl -n restate port-forward svc/restate 8080:8080 9070:9070
```

In another shell:

```bash
curl --fail --silent localhost:9070/services | jq
curl localhost:8080/MyService/myHandler --json '{}'
```

Do not turn `svc/restate` into a LoadBalancer or publish port 9070 through an
Ingress without putting a real authentication and authorization layer in
front of it.

### Web UI and the playground

Restate serves its Web UI on the **admin** port, so the port-forward above also
gets you the UI. Keep both ports in that single command even if the UI is all
you want:

```bash
kubectl -n restate port-forward svc/restate 8080:8080 9070:9070
# then open http://localhost:9070/ui
```

Forwarding only 9070 gets you a working UI that cannot invoke anything, because
the playground sends invocations to the **ingress** port and your browser is
what dials it. The address it uses must therefore resolve from your machine, not
from inside the cluster.

Ask the cluster which address it advertises:

```bash
curl --fail --silent localhost:9070/version | jq -r .ingress_endpoint
```

With this reference as shipped, that returns the serving pod's own IP, for
example `http://192.168.130.168:8080/`. A browser on your laptop cannot reach a
VPC pod IP, so the playground's invocations fail even while the UI itself works
and `curl localhost:8080/...` succeeds through your forward. The advertised
address is not derived from the page you loaded the UI from.

Restate takes it from `[ingress] advertised-address`, environment variable
`RESTATE_INGRESS__ADVERTISED_ADDRESS`, which this reference leaves unset to match
the profile. Do not confuse it with the top-level `RESTATE_ADVERTISED_ADDRESS`
that `resources/04-restate-cluster.yaml` does set: that one is the node's own
address on 5122 for peer traffic, and repurposing it breaks cluster formation.

To make the playground work through a port-forward, advertise the tunnel:

```yaml
- name: RESTATE_INGRESS__ADVERTISED_ADDRESS
  value: http://localhost:8080/
```

Keep the forward's local port equal to 8080 so that address resolves. This value
is correct only for people reaching the cluster by port-forward, which is why no
value ships here — see the next section for a shared cluster. Changing it rolls
all three Restate pods.

### Making the playground work for a team

A shared cluster wants an ingress URL that resolves for everyone, not a
localhost tunnel. Four things have to line up, and the order matters:

1. **Expose port 8080 only, through a Service you own.** `svc/restate` is
   operator-managed and carries both ports, so do not convert it to a
   LoadBalancer — that publishes the unauthenticated admin API at the same
   time. Create a separate Service or Ingress selecting the same Restate pods
   with only 8080 in its port list.
2. **Prefer internal exposure and put authentication in front.** Restate's
   ingress accepts any caller that reaches it. An internal load balancer inside
   your VPC, or an ingress controller enforcing authentication, is the minimum;
   an internet-facing endpoint with neither invites anyone to invoke your
   handlers.
3. **Open the cluster's ingress peers.** `resources/04-restate-cluster.yaml`
   admits ingress only from `restate-apps` under `security.networkPeers`, so
   where NetworkPolicy is enforced, traffic arriving from a load balancer is
   denied — and a `namespaceSelector` cannot match it, because it does not
   originate from a pod. Widen that peer list for the actual source, and check
   which peer types the CRD accepts before assuming a form.
4. **Set the advertised address to the URL people will use**, so the UI's
   playground points at it:

   ```yaml
   - name: RESTATE_INGRESS__ADVERTISED_ADDRESS
     value: https://restate-ingress.internal.example.com/
   ```

Changing that environment variable rolls all three Restate pods, which moves
partition leadership. Do it deliberately, one change at a time, and verify
cluster health afterwards with the [five-minute health
check](#five-minute-health-check).

Setting the advertised address changes only what the UI and CLI *advertise*. It
does not expose anything by itself, and it does not change what the server
binds to. Equally, exposing ingress without setting it leaves the playground
pointing somewhere your users cannot reach.

## Verify the snapshot path

Automatic snapshots require both the configured record threshold and interval,
so they are a poor first-install signal — see [when automatic snapshots
fire](#when-automatic-snapshots-fire) for why they can be rarer than the
5-minute interval suggests. Trigger one explicitly:

```bash
kubectl -n restate exec restate-0 -- \
  restatectl snapshots create-snapshot

aws s3 ls "s3://$BUCKET/restate/snapshots/" --recursive | head
```

If this fails, check the entire chain rather than only the bucket:

```bash
kubectl -n restate get serviceaccount restate -o yaml
kubectl -n restate get pod restate-0 \
  -o jsonpath='{.spec.serviceAccountName}{"\n"}'
kubectl -n restate get pod restate-0 \
  -o jsonpath='{range .spec.containers[0].env[*]}{.name}{"="}{.value}{"\n"}{end}' \
  | grep -E 'AWS_REGION|SNAPSHOTS'
```

Confirm that:

- the ServiceAccount annotation contains the intended IRSA role ARN;
- the pod uses ServiceAccount `restate`;
- `AWS_REGION` and the S3 destination are correct;
- the role trust policy names `system:serviceaccount:restate:restate`;
- the attached IAM policy grants access to this exact bucket;
- a private STS interface endpoint is not being blocked by Restate's egress
  NetworkPolicy. See [Architecture](00-architecture.md#private-aws-endpoints).

### When automatic snapshots fire

The manifest sets `SNAPSHOT_INTERVAL_NUM_RECORDS` to 100,000 and
`SNAPSHOT_INTERVAL` to five minutes. Both conditions must hold, and the record
threshold is **per partition**, not cluster-wide: each leader partition
snapshots when its applied LSN reaches its last snapshot's LSN plus the
threshold, and only if the previous snapshot is older than the interval. The
interval is a floor on frequency, not a trigger.

With 48 partitions, that is easy to misjudge. A measured example on this
reference: 15,300 invocations spread evenly produced roughly 182,000 applied
records in aggregate but a maximum of about 6,300 on any single partition — six
per cent of one partition's threshold — and no automatic snapshot, correctly.
Aggregate throughput tells you nothing here; the busiest single partition is
what matters.

The consequence is operational, not cosmetic. A cluster with modest or evenly
spread traffic may go a long time between automatic snapshots, and
`resources/04-restate-cluster.yaml` relies on snapshots so that replacement pods
bootstrap from S3 instead of replaying a full log. If you depend on that — node
replacement time, or log growth — then either schedule manual snapshots or lower
`RESTATE_WORKER__SNAPSHOTS__SNAPSHOT_INTERVAL_NUM_RECORDS`. The 100,000 comes
from the profile and is left at its profile value here; see
[Profile fidelity](04-profile-fidelity.md).

Check where partitions actually stand before concluding anything is broken:

```bash
kubectl -n restate exec restate-0 -- restatectl status
aws s3 ls "s3://$BUCKET/restate/snapshots/" --recursive | wc -l
```

## Verify the network boundary

First confirm that the VPC CNI is configured to enforce NetworkPolicy:

```bash
aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \
  --addon-name vpc-cni --query addon.configurationValues
kubectl api-resources | grep policyendpoints
```

Then inspect the applied controls and Service types:

```bash
kubectl -n restate get networkpolicy
kubectl -n restate-apps get networkpolicy
kubectl -n restate get service restate restate-cluster \
  -o custom-columns='NAME:.metadata.name,TYPE:.spec.type,PORTS:.spec.ports[*].port'
```

The policies can exist while doing nothing if the CNI does not enforce them.
On a cluster without enforcement, every pod should be treated as trusted with
the Restate admin API and every SDK endpoint.

### Prove that the boundary blocks

Existing policies and an enforcing CNI are not the same as a boundary that
holds. Test the denials directly, with throwaway pods that touch nothing:

```bash
IMG=curlimages/curl:8.10.1
kubectl -n restate-apps get services
SDK_SERVICE=service-REPLACE_WITH_REVISION_HASH
kubectl -n restate-apps get endpointslice \
  -l "kubernetes.io/service-name=$SDK_SERVICE"
SDK_IP=$(kubectl -n restate-apps get svc "$SDK_SERVICE" \
  -o jsonpath='{.spec.clusterIP}')

# from the compute namespace: ingress allowed, admin denied
kubectl -n restate-apps run probe --rm -i --restart=Never --image=$IMG -- sh -c '
  curl -sS -m 5 -o /dev/null -w "apps->ingress 8080: %{http_code} %{time_total}s\n" http://restate.restate.svc.cluster.local:8080/ ;
  curl -sS -m 5 -o /dev/null -w "apps->admin   9070: %{http_code} %{time_total}s\n" http://restate.restate.svc.cluster.local:9070/services'

# from an unrelated namespace: both denied
kubectl -n default run probe --rm -i --restart=Never --image=$IMG -- sh -c "
  curl -sS -m 5 -o /dev/null -w 'default->sdk 9080: %{http_code} %{time_total}s\n' http://$SDK_IP:9080/ ;
  curl -sS -m 5 -o /dev/null -w 'default->ingress 8080: %{http_code} %{time_total}s\n' http://restate.restate.svc.cluster.local:8080/"
```

Set `SDK_SERVICE` to a specific operator-generated revision Service and confirm
its EndpointSlice has ready addresses before interpreting a timeout. Selecting
the first Service in the namespace is not a valid boundary test: list ordering
is unspecified, and a Service with no ready endpoint also times out.

**A timeout is the pass signal and a fast connection is the failure.** Both
render as HTTP `000`, so read `time_total`, not the status code: a denial sits
at the full 5-second limit, while a refusal or a success returns in
milliseconds.

Measured on EKS 1.34 with `vpc-cni` enforcement enabled:

| From | To | Result | Meaning |
|---|---|---|---|
| `restate-apps` | ingress 8080 | `400` in 2.1s | reachable, as intended — a bare `GET /` is a 400 from ingress |
| `restate-apps` | admin 9070 | timeout at 5.0s | denied: workloads cannot reach the unauthenticated admin API |
| `default` | SDK service 9080 | timeout at 5.0s | denied: an unrelated pod cannot bypass Restate to call an SDK endpoint |
| `default` | ingress 8080 | timeout at 5.0s | denied: `networkPeers.ingress` admits only `restate-apps` |

The fifth direction, Restate reaching a service ClusterIP on 9080, must
*succeed*; it is what
[`resources/06-restate-service-cidr-egress.yaml`](../resources/06-restate-service-cidr-egress.yaml)
exists for. If it fails, see
[a RestateDeployment is not Ready](#a-restatedeployment-is-not-ready).

Re-run this after any change to `security.networkPeers`, to
`resources/00-namespaces.yaml`, or to CNI enforcement. Widening a peer list to
expose ingress externally, as under [making the playground work for a
team](#making-the-playground-work-for-a-team), changes rows three and four by
design — know which ones you meant to change.

## Troubleshooting by symptom

### A Restate pod stays Pending

```bash
kubectl -n restate describe pod <pod>
kubectl -n restate get events --sort-by=.lastTimestamp
kubectl get nodes -o custom-columns=\
'NAME:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory'
kubectl describe node <candidate-node>
kubectl get storageclass restate-gp3
```

Common causes:

- fewer than three eligible nodes because hard anti-affinity permits only one
  Restate pod per node;
- less than 24 vCPU or 50 GiB memory remaining after existing pod requests on
  an eligible node—the `Allocated resources` section, not `kubectl top`, is the
  scheduler-relevant view;
- a taint without a matching toleration;
- the EBS CSI driver is absent or unhealthy;
- no subnet/AZ is available for an EBS volume selected by
  `WaitForFirstConsumer`.

### Pods are Running but not Ready

```bash
kubectl get restatecluster restate -o yaml
kubectl -n restate logs restate-0 --tail=200
kubectl -n restate-operator logs deploy/restate-operator --tail=200
```

The operator provisions the cluster after `restate-0` is Running; Restate pods
become Ready afterwards. Look for failed provisioning, metadata peer DNS, or
configuration validation errors. Do not run `restatectl provision` while
`spec.cluster.autoProvision` remains enabled: it can race the controller, and
operator 3.0.1 warns that concurrent provisioning methods can split the
cluster.

### A RestateDeployment is not Ready

```bash
kubectl -n restate-apps describe restatedeployment <name>
kubectl -n restate-apps get pods,rs,svc -l app=<service-label>
kubectl -n restate-apps logs <pod> --tail=200
kubectl -n restate-operator logs deploy/restate-operator --tail=200
```

Check that the image can be pulled, the container listens on port 9080, the
port is named `restate`, and `spec.restate.register.cluster` is `restate`.
Registration also depends on the operator reaching the cluster admin API and
the Restate namespace reaching the service pods.

If the pods are Ready and registration still times out, test the two hops
separately from a Restate pod — reachable pod IP with an unreachable ClusterIP
is the signature of the missing Service-CIDR egress policy:

```bash
SVC_IP="$(kubectl -n restate-apps get svc <revision-svc> \
  -o jsonpath='{.spec.clusterIP}')"
POD_IP="$(kubectl -n restate-apps get pod <pod> \
  -o jsonpath='{.status.podIP}')"

kubectl -n restate exec restate-0 -- curl -sS -m 5 -o /dev/null \
  -w 'pod %{http_code} %{time_total}s\n' "http://$POD_IP:9080/"
kubectl -n restate exec restate-0 -- curl -sS -m 5 -o /dev/null \
  -w 'clusterip %{http_code} %{time_total}s\n' "http://$SVC_IP:9080/"

kubectl -n restate get networkpolicy allow-egress-to-service-cidr
kubectl -n restate get policyendpoints
```

Apply `resources/06-restate-service-cidr-egress.yaml` with the cluster's real
`serviceIpv4Cidr` if that policy is absent. See
[Architecture: SDK service isolation](00-architecture.md#sdk-service-isolation).

### An old service revision does not scale down

This is normally expected. Restate keeps an old revision alive while any
in-flight invocation is pinned to it, then waits for the drain delay.

```bash
restate deployments list
restate deployment describe <deployment-id> --extra
```

Do not force-delete the old ReplicaSet as a routine cleanup step. See
[Deploying services](03-deploying-services.md#draining-old-revisions).

### Terraform cannot plan Restate custom resources

Stage 02 queries the live cluster for Restate CRD schemas during planning.
Confirm that stage 01 completed and the CRDs are served:

```bash
kubectl get crd restateclusters.restate.dev restatedeployments.restate.dev
helm -n restate-operator list
```

If AWS or Kubernetes resources were created previously by the manual path,
Terraform will not automatically adopt them. Import them into the appropriate
stage state or use a clean installation; do not alternate between paths.

## Routine changes

### Deploy a new SDK service revision

Update the pod template—usually the image—in
`resources/05-restate-compute.yaml`, review the diff, and apply it. The
operator creates a new immutable revision and drains the old one.

This is the same on both deployment paths: the Terraform modules deploy the
cluster, not your services. See
[Deploying services](03-deploying-services.md#roll-out-a-new-version).

### Increase storage

`spec.storage.storageRequestBytes` may only increase. Increasing it updates the
PVC request; actual expansion depends on the EBS CSI driver and the
StorageClass. Never reduce the value or assume that retained PVs shrink.

### Change runtime sizing or configuration

Changes to the `RestateCluster` pod template can roll StatefulSet pods and may
affect a live replicated system. Before applying:

1. verify cluster health and snapshots;
2. inspect the operator's planned diff or Terraform plan;
3. change one dimension at a time;
4. watch pods and `restatectl status` until the cluster is healthy again.

### Upgrade Restate or the operator

The image and chart are intentionally pinned. Before upgrading:

1. read both Restate and operator release notes;
2. verify that the operator version supports the target Restate version and CRD;
3. revalidate every `RESTATE_EXPERIMENTAL_*` option and the profile-derived
   tuning in `resources/04-restate-cluster.yaml`;
4. take and verify a snapshot;
5. test the change outside production;
6. update the documented version baseline and profile-fidelity notes with the
   manifests.

Changing only the container image is not a complete upgrade review.

## Data safety and recovery boundaries

Two independent mechanisms protect different failure modes:

- **Retained EBS PVs** preserve the node-local data volumes if the
  `RestateCluster`, namespace, or PVCs are deleted. Verified on 2026-09-01
  against a full teardown, which is the strongest form of this case: the CR,
  namespace, PVCs, CRDs, operator, and StorageClass were all deleted and the
  three volumes survived as `Released` PVs.
- **S3 partition snapshots** allow nodes to bootstrap without replaying the
  entire retained log and provide recovery material outside the EBS volumes.

Neither mechanism is a complete, automatic disaster-recovery workflow.
Released PVs retain their old claim references and do not bind to replacement
PVCs automatically. Before any destructive operation, record the PV, PVC,
Availability Zone, and EBS volume-id mapping:

```bash
kubectl -n restate get pvc -o wide
kubectl get pv \
  -o custom-columns='PV:.metadata.name,STATUS:.status.phase,CLAIM-NS:.spec.claimRef.namespace,CLAIM:.spec.claimRef.name,VOLUME:.spec.csi.volumeHandle'
```

If recovery is required, stop and design the reattachment or snapshot-restore
procedure for the incident. Do not delete Released PVs or empty the snapshot
bucket merely to make a deployment command succeed.

## Teardown checklist

Teardown is intentionally conservative because application revisions may need
to drain and data resources may need to survive. The order below applies to
both deployment paths through removal of the `RestateCluster`:

1. Stop new traffic, create and verify the latest snapshot, and record the
   current PV/PVC/AZ/EBS mapping **before** deleting anything.
2. Delete every `RestateDeployment` and wait for its finalizer to drain all
   revisions.
3. Delete the `RestateCluster` and wait for the operator-owned namespace to
   terminate.
4. Record the now-Released PV and EBS mapping again.
5. Only then remove the operator, repository-owned namespaces, StorageClass,
   and—after a cluster-wide dependency check—the retained CRDs.
6. Delete retained EBS volumes and empty/delete the S3 bucket only after an
   explicit data-retention decision.
7. Preserve a cluster-wide IAM OIDC provider whenever the EKS cluster remains
   or any other IRSA role still trusts it.

For the manual path, steps 2 and 3 are:

```bash
kubectl -n restate-apps delete restatedeployment --all \
  --wait=true --timeout=15m
kubectl delete restatecluster restate --wait=true --timeout=15m
```

If service deletion times out, inspect the pinned invocations and continue
waiting. Do not remove the finalizer or delete the cluster underneath them.

The remaining manual-path Kubernetes cleanup after steps 1–4 is:

```bash
helm uninstall restate-operator --namespace restate-operator --wait

# The chart deliberately keeps all three CRDs on uninstall. Before deleting
# them, prove that no Restate operator installation or custom resource remains.
kubectl get deployments --all-namespaces \
  -l app.kubernetes.io/name=restate-operator
kubectl get restateclusters.restate.dev
kubectl get restatedeployments.restate.dev --all-namespaces
kubectl get restatecloudenvironments.restate.dev --all-namespaces

kubectl delete crd \
  restateclusters.restate.dev \
  restatedeployments.restate.dev \
  restatecloudenvironments.restate.dev

kubectl delete namespace restate-apps restate-operator
kubectl delete storageclass restate-gp3
```

Do not delete a CRD merely because this installation is gone. CRDs are
cluster-wide, Helm annotates these with `helm.sh/resource-policy: keep`, and
deleting one also deletes every remaining custom resource of that kind. If
another operator installation or CR exists, leave all three definitions in
place and record the shared ownership.

This order was executed end to end on a live three-node cluster on 2026-09-01.
Steps 2 and 3 behaved as documented: the `RestateDeployment` finalizer drained
its revision and removed the ReplicaSet, Services, and pods, leaving
`restate-apps` empty; deleting the `RestateCluster` then removed the namespace
and PVCs while all three PVs became `Released` with their EBS volumes intact.

For Terraform, do not run the manual deletion commands for resources still in
state. Follow the ownership decisions, saved destroy plans, and post-destroy CRD
cleanup in
[Terraform: Destroy](../terraform/README.md#destroy).

### What a completed teardown leaves behind

Even after the complete Kubernetes cleanup above, billable AWS resources can
remain. Deleting the `RestateCluster`, its namespace and PVCs, the CRDs, the
operator release, and the StorageClass removes nothing on this list—verified by
doing exactly that on the manual path:

| Survives | Why | Removing it |
|---|---|---|
| 3 × EBS volumes behind `Released` PVs | `reclaimPolicy: Retain`, working as intended | Explicit `aws ec2 delete-volume` per volume |
| Snapshot bucket and its objects | Dedicated bucket, no lifecycle rule | Use the tool that owns it; empty it only after an explicit retention decision |
| Snapshots IAM role and policy | Manual path: eksctl/CloudFormation plus IAM policy; Terraform path: stage-01 state unless transferred | Remove through the owning delivery tool, or transfer ownership explicitly |
| IAM OIDC provider | Cluster-wide, shared by every IRSA role | Keep unless the EKS cluster is going too |
| The EKS cluster itself | This repository never creates it | Your cluster provisioning tool |

The retained volumes are the item most often forgotten, and the window to
identify them is narrower than it looks: the PV objects that carry the
`vol-*` handles live in the cluster, so deleting the EKS cluster destroys the
mapping while leaving the volumes themselves provisioned and billing. Capture
it while the cluster still answers:

```bash
kubectl get pv \
  -o custom-columns='PV:.metadata.name,STATUS:.status.phase,VOLUME:.spec.csi.volumeHandle,SIZE:.spec.capacity.storage'
```

Reading PV objects needs no AWS credentials, only a working kubeconfig, so this
remains possible even when `aws sts get-caller-identity` is failing. If the
cluster is already gone, the volumes are still findable by their EBS tags, but
that is a recovery path — record the mapping instead.
