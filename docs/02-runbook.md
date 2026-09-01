# Manual deployment runbook

This runbook is for a cloud engineer installing Restate with AWS CLI, eksctl,
Helm, and kubectl. It favors visible, verifiable steps over automation and does
not require detailed knowledge of Restate internals.

If Restate itself is new to you, start with the
[top-level overview](../README.md) for the product and ownership model, then
return here.

For a state-managed installation, use the [Terraform guide](../terraform/README.md)
instead. Please use one path per installation. If you move a manual installation
to Terraform, first import its resources into Terraform state.

The installation creates AWS snapshot access, cluster-scoped Kubernetes
resources, the Restate operator, and a three-node Restate cluster. It does not
create EKS infrastructure, expose Restate outside the cluster, or deploy a
customer application. Step 6 is an optional application example and is not
part of the infrastructure handoff.

In this guide, `RestateCluster` is a Kubernetes custom resource describing the
Restate runtime. It is not the EKS cluster itself. References to the EKS cluster
are always written explicitly.

## Installation flow

| Step | Result | Scope |
|---|---|---|
| 1 | Operator and application namespaces | Kubernetes cluster |
| 2 | Snapshot IAM policy and IRSA role | AWS account and target EKS identity provider |
| 3 | Restate operator, CRDs, and RBAC | Kubernetes cluster |
| 4 | StorageClass and three-node Restate cluster | Kubernetes and EBS |
| 5 | Proven S3 snapshot path | End-to-end validation |
| 6 | Optional SDK service example | Customer application namespace |
| 7 | Local ingress, admin API, and UI access | Operator workstation |

## Before you begin

1. Complete the [prerequisite checklist](01-prerequisites.md#deployment-checklist).
2. Run commands from the repository root.
3. Work on a branch or copy so placeholder substitutions remain reviewable.
4. Confirm that your current AWS identity and Kubernetes context point to the
   intended environment.

Set the shared values once:

```bash
export CLUSTER=...
export REGION=...
export ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export BUCKET=...

aws sts get-caller-identity
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"
kubectl config current-context
kubectl cluster-info
```

If the account, cluster, or context is not the intended target, pause here and
correct it before continuing.

## Prepare the manifests

Replace the manual-path placeholders listed in
[Prerequisites](01-prerequisites.md#manual-path-placeholders). At minimum:

- replace `REPLACE_ME_SNAPSHOTS_BUCKET` in the cluster manifest; step 2 renders
  a temporary IAM policy from the canonical JSON without modifying that file;
- replace `REPLACE_ME_AWS_REGION` in the cluster manifest;
- replace `REPLACE_ME_SNAPSHOTS_ROLE_ARN` after step 2;
- leave `resources/05-restate-compute.yaml` unapplied until its service image
  is set.

Check before every apply:

```bash
grep -RIn 'REPLACE_ME' resources
git diff -- resources
```

The IAM policy's bucket token, the unapplied compute image, and the commented
`REPLACE_ME_EKS_CLUSTER_NAME` may still appear at this point. Before each step,
confirm that the specific file or rendered payload being applied has no active
placeholder. The EKS cluster-name token is only activated for the EKS Pod
Identity alternative.

## Step 1: Create repository-owned namespaces

Apply `resources/00-namespaces.yaml`:

```bash
kubectl apply -f resources/00-namespaces.yaml
kubectl get namespace restate-operator restate-apps
kubectl -n restate-apps get networkpolicy
```

This creates:

- `restate-operator`, the Helm target;
- `restate-apps`, where SDK services run;
- the `restate-apps` ingress policy, allowing calls only from the future
  `restate` namespace.

Leave the `restate` namespace for the operator to create and manage when the
`RestateCluster` is applied.

## Step 2: Configure snapshot IAM

The Restate pods use a ServiceAccount named `restate` in namespace `restate`.
Create a cluster-qualified IAM policy and IRSA role for that exact subject.

First confirm that the dedicated bucket required by the prerequisites exists
and retains its public-access and HTTPS-only controls:

```bash
aws s3api head-bucket --bucket "$BUCKET"
aws s3api get-public-access-block --bucket "$BUCKET"
aws s3api get-bucket-policy --bucket "$BUCKET" \
  --query Policy --output text | jq
```

Then ensure the EKS IAM OIDC provider exists. This command is safe when the
provider is already associated:

```bash
eksctl utils associate-iam-oidc-provider \
  --cluster "$CLUSTER" \
  --region "$REGION" \
  --approve
```

Render and create the snapshot policy:

```bash
sed "s/REPLACE_ME_SNAPSHOTS_BUCKET/$BUCKET/" \
  resources/01-restate-snapshots-iam-policy.json > /tmp/restate-snapshot-policy.json

aws iam create-policy \
  --policy-name "${CLUSTER}-restate-snapshots" \
  --policy-document file:///tmp/restate-snapshot-policy.json
```

Create only the IAM role and trust relationship. The operator will create the
Kubernetes ServiceAccount later:

```bash
eksctl create iamserviceaccount \
  --cluster "$CLUSTER" \
  --region "$REGION" \
  --namespace restate \
  --name restate \
  --role-name "${CLUSTER}-restate-snapshots" \
  --attach-policy-arn "arn:aws:iam::$ACCOUNT:policy/${CLUSTER}-restate-snapshots" \
  --role-only \
  --approve
```

The name `${CLUSTER}-restate-snapshots` must fit IAM's 64-character role-name
limit. Because the suffix is 18 characters, `$CLUSTER` must be no longer than
46 characters.

Replace `REPLACE_ME_SNAPSHOTS_ROLE_ARN` in
`resources/04-restate-cluster.yaml` with:

```text
arn:aws:iam::<account>:role/<cluster>-restate-snapshots
```

Verify the role and attached policy:

```bash
aws iam get-role --role-name "${CLUSTER}-restate-snapshots" \
  --query 'Role.{arn:Arn,trust:AssumeRolePolicyDocument}'
aws iam list-attached-role-policies \
  --role-name "${CLUSTER}-restate-snapshots"
```

### Rerunning the IAM step

`aws iam create-policy` fails when the named policy already exists. Update an
existing policy with a new policy version rather than trying to create it
again. The eksctl-created role lives in an eksctl-managed CloudFormation stack;
change it with `eksctl update iamserviceaccount` using the same identity flags.

If adapting the reference to EKS Pod Identity—the supplied IAM path does not
automate it—see
[Architecture: IAM for snapshots](00-architecture.md#iam-for-snapshots).

## Step 3: Install the Restate operator

`resources/02-restate-operator.values.yaml` is a Helm values file, not a
Kubernetes manifest:

```bash
helm upgrade --install restate-operator \
  oci://ghcr.io/restatedev/restate-operator-helm \
  --version 3.0.1 \
  --namespace restate-operator \
  --values resources/02-restate-operator.values.yaml \
  --wait \
  --timeout 5m
```

Verify the controller and CRDs:

```bash
kubectl -n restate-operator get deployment,pods
kubectl get crd \
  restateclusters.restate.dev \
  restatedeployments.restate.dev \
  restatecloudenvironments.restate.dev
```

The v3 chart installs and upgrades its CRDs. It does not require cert-manager.
The chart marks those CRDs to survive Helm uninstall; the teardown guide
performs a cluster-wide dependency check before deleting them explicitly.

### If the chart pull fails with 401 or 403

The chart is public and pulls anonymously. A `401` or `403` usually means Helm
is presenting a stale or insufficiently scoped `ghcr.io` credential instead of
falling back to anonymous access. Clear it and retry the pull on its own:

```bash
helm registry logout ghcr.io || true
docker logout ghcr.io || true
helm pull oci://ghcr.io/restatedev/restate-operator-helm \
  --version 3.0.1 --destination /tmp
```

If the unauthenticated pull also fails, your environment blocks anonymous
registry access; authenticate as described in
[Prerequisites: OCI chart registry access](01-prerequisites.md#oci-chart-registry-access).
Either way this is a registry-access failure, not a Kubernetes or AWS failure,
and nothing in the cluster has changed yet.

## Step 4: Create storage and the Restate cluster

Apply the StorageClass first and inspect it before creating PVCs:

```bash
kubectl apply -f resources/03-gp3-storageclass.yaml
kubectl get storageclass restate-gp3 -o yaml
```

The expected class uses encrypted XFS, 6000 IOPS, 500 MiB/s,
`WaitForFirstConsumer`, and `reclaimPolicy: Retain`.

Confirm that no active placeholder remains in the cluster manifest, then apply
it:

```bash
grep -n 'REPLACE_ME' resources/04-restate-cluster.yaml
kubectl apply -f resources/04-restate-cluster.yaml
```

Watch the operator-owned namespace come online:

```bash
kubectl get restatecluster restate -w
```

In another shell:

```bash
kubectl -n restate get pods,pvc -w
```

The sequence is expected to be:

1. `restate-0..2` are scheduled on different nodes;
2. EBS PVCs bind in each pod's Availability Zone;
3. pods start unprovisioned and form the metadata cluster;
4. the operator provisions 48 partitions with node replication 2;
5. all three pods become Ready and the CR reports `Ready=True`.

Wait and verify:

```bash
kubectl wait --for=condition=Ready restatecluster/restate --timeout=15m
kubectl get restatecluster restate \
  -o jsonpath='{.status.provisioned}{"\n"}'
kubectl -n restate get pods -o wide
kubectl -n restate exec restate-0 -- restatectl status
```

If automatic provisioning fails after the pods are Running, inspect the
`RestateCluster` conditions and operator logs. Do **not** run
`restatectl provision` while `spec.cluster.autoProvision` remains enabled: it
can race the controller and operator 3.0.1 warns that concurrent provisioning
methods can split the cluster.

For the full sequence, see
[Architecture: Cluster bootstrap](00-architecture.md#cluster-bootstrap-sequence).

### Allow egress to SDK service ClusterIPs

Skip this only if your CNI does not enforce NetworkPolicy. Where it does — the
EKS VPC CNI with `enableNetworkPolicy: true` included — the operator's egress
rules cover service pod IPs but not the ClusterIP it registers each service
revision under, so registration in step 6 will time out until this policy
exists. The namespace it targets was created by step 4, which is why it is
applied here rather than earlier.

```bash
SERVICE_CIDR="$(aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
  --query 'cluster.kubernetesNetworkConfig.serviceIpv4Cidr' --output text)"
echo "$SERVICE_CIDR"

sed "s|REPLACE_ME_SERVICE_CIDR|$SERVICE_CIDR|" \
  resources/06-restate-service-cidr-egress.yaml | kubectl apply -f -

kubectl -n restate get networkpolicy allow-egress-to-service-cidr
```

Read the file's header before applying it: it documents the mechanism, and that
the allowance covers TCP 9080 to any ClusterIP rather than only the SDK
services. Where enforcement is on, confirm the CNI picked the rule up:

```bash
kubectl -n restate get policyendpoints
```

## Step 5: Prove snapshots work

Trigger a snapshot directly and confirm objects reach the dedicated bucket.
The automatic cadence requires both 100,000 records and five minutes:

```bash
kubectl -n restate exec restate-0 -- \
  restatectl snapshots create-snapshot
aws s3 ls "s3://$BUCKET/restate/snapshots/" --recursive | head
```

This checks the ServiceAccount annotation, OIDC trust, IAM policy, AWS region,
network egress, bucket, and Restate snapshot configuration together. Confirm
that it succeeds before continuing to production use.

## Step 6: Deploy an SDK service (optional)

Skip this step if you only need the Restate cluster.

Set `REPLACE_ME_SERVICE_IMAGE` in `resources/05-restate-compute.yaml` to an
image that listens on port 9080, then apply it:

```bash
grep -n 'REPLACE_ME' resources/05-restate-compute.yaml
kubectl apply -f resources/05-restate-compute.yaml
kubectl -n restate-apps get restatedeployments,pods -w
```

The operator creates a versioned ReplicaSet and Service, registers the
revision, and reports the `RestateDeployment` Ready. It also labels the pods so
the Restate namespace may invoke them through the enforced NetworkPolicy.

Read [Deploying services](03-deploying-services.md) before rolling out a second
version or deleting an old ReplicaSet.

## Step 7: Test ingress and admin access

Forward the ClusterIP Service, not the headless node Service:

```bash
kubectl -n restate port-forward svc/restate 8080:8080 9070:9070
```

In another shell:

```bash
curl --fail --silent localhost:9070/services | jq
curl localhost:8080/MyService/myHandler --json '{}'
```

`svc/restate-cluster` is headless and carries node traffic on port 5122; it does
not expose ports 8080 or 9070.

The port-forward tunnels through the kubelet and bypasses NetworkPolicy. This
is the intended operator access path for the unauthenticated admin API. Keep
port 9070 private unless it is protected by a suitable authentication and
authorization layer.

The same forward serves the Web UI at `http://localhost:9070/ui`. Keep 8080 in
the command: the UI is served by the admin port, but its playground sends
invocations to the ingress port, and your browser is what dials it. See
[Operations: Web UI and the playground](05-operations.md#web-ui-and-the-playground)
for a shared-cluster setup.

## Completion checklist

- [ ] `RestateCluster/restate` is provisioned and Ready.
- [ ] Three Restate pods are Ready on different nodes.
- [ ] Three PVCs are Bound through `restate-gp3`.
- [ ] `restatectl status` reports healthy nodes, logs, and partitions.
- [ ] A manual snapshot succeeded and objects exist in S3.
- [ ] `svc/restate` is still a ClusterIP.
- [ ] NetworkPolicy enforcement matches the trust decision made in the
      prerequisites.
- [ ] If deployed, the SDK service is Ready and registered.
- [ ] No active `REPLACE_ME_*` value remains in an applied file.

Continue with [Operations and troubleshooting](05-operations.md) for routine
checks, changes, recovery boundaries, and teardown.
