# Operations and troubleshooting

Use this guide after the cluster has been installed. It collects the checks
that answer three practical questions:

1. Is the deployment healthy?
2. Where should I look when it is not?
3. Which changes are safe to make, and which need a recovery plan?

For installation, use the [manual runbook](02-runbook.md) or the
[Terraform guide](../terraform/README.md). For SDK service rollout behavior,
use [Deploying services](03-deploying-services.md).

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

## Verify the snapshot path

Automatic snapshots require both the configured record threshold and interval,
so they are a poor first-install signal. Trigger one explicitly:

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

## Troubleshooting by symptom

### A Restate pod stays Pending

```bash
kubectl -n restate describe pod <pod>
kubectl -n restate get events --sort-by=.lastTimestamp
kubectl get nodes -o custom-columns=\
'NAME:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory'
kubectl get storageclass restate-gp3
```

Common causes:

- fewer than three eligible nodes because hard anti-affinity permits only one
  Restate pod per node;
- less than 24 allocatable vCPU or 50 GiB memory on an eligible node;
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
configuration validation errors. If automatic provisioning failed, the manual
fallback is idempotent:

```bash
kubectl -n restate exec restate-0 -- restatectl provision --yes
```

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

For Terraform, set `service_image` and apply stage 02. See
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
  `RestateCluster`, namespace, or PVCs are deleted.
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
to drain and data resources may need to survive.

1. Stop new traffic and verify the latest snapshot.
2. Delete the `RestateDeployment` and wait for its finalizer to drain all
   revisions.
3. Delete the `RestateCluster`.
4. Record the Released PV and EBS volume mapping before removing anything else.
5. Remove the operator and repository-owned namespaces only after the custom
   resources are gone.
6. Delete retained EBS volumes and empty/delete the S3 bucket only after an
   explicit data-retention decision.
7. Preserve a cluster-wide IAM OIDC provider if any other IRSA workload uses it.

For Terraform-specific ordering and the OIDC state escape hatch, follow
[Terraform: Destroy](../terraform/README.md#destroy).
