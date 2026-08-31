# Runbook

Apply the files in [`resources/`](../resources/) in numeric order. Each step
below names the resource it consumes. Check
[prerequisites](01-prerequisites.md) and fill every `REPLACE_ME` first.

## 0. Auth + kubeconfig

```bash
export CLUSTER=...  REGION=...  ACCOUNT=...  BUCKET=...

aws sts get-caller-identity            # sanity
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"
```

## 1. Namespaces — `resources/00-namespaces.yaml`

Creates `restate-operator` (helm target) and `restate-apps` (compute), plus a
NetworkPolicy on `restate-apps` so only the Restate cluster can call the SDK
services (nothing else should reach an SDK endpoint directly). The `restate`
namespace is **not** here — the operator creates it from the RestateCluster in
step 4.

```bash
kubectl apply -f resources/00-namespaces.yaml
```

## 2. IAM for snapshots (IRSA) — `resources/01-restate-snapshots-iam-policy.json`

The operator will create ServiceAccount `restate` in namespace `restate`;
`security.serviceAccountAnnotations` in `resources/04-restate-cluster.yaml`
binds it to the role created here.

```bash
# once per cluster
eksctl utils associate-iam-oidc-provider --cluster "$CLUSTER" --region "$REGION" --approve

sed "s/REPLACE_ME_SNAPSHOTS_BUCKET/$BUCKET/" \
  resources/01-restate-snapshots-iam-policy.json > /tmp/policy.json

# Cluster-qualified names: IAM policies/roles are account-global, and the
# role's IRSA trust is tied to THIS cluster's OIDC provider — a second EKS
# cluster in the account needs its own pair (and its own bucket, see step 4).
aws iam create-policy --policy-name "${CLUSTER}-restate-snapshots" \
  --policy-document file:///tmp/policy.json

# --role-only: the operator owns the ServiceAccount, we only need the role + trust policy
eksctl create iamserviceaccount --cluster "$CLUSTER" --region "$REGION" \
  --namespace restate --name restate \
  --role-name "${CLUSTER}-restate-snapshots" \
  --attach-policy-arn "arn:aws:iam::$ACCOUNT:policy/${CLUSTER}-restate-snapshots" \
  --role-only --approve
```

Then fill the role ARN —
`arn:aws:iam::$ACCOUNT:role/${CLUSTER}-restate-snapshots` — into
`resources/04-restate-cluster.yaml` → `security.serviceAccountAnnotations`
(`REPLACE_ME_SNAPSHOTS_ROLE_ARN`).

Rerunning this step: `create-policy` fails if the policy exists — update it
with `aws iam create-policy-version --set-as-default` instead. The role lives
in an eksctl-owned CloudFormation stack; change it with
`eksctl update iamserviceaccount` (same flags), not a second `create`.

*Alternative (what Restate Cloud itself runs):* operator-managed EKS Pod
Identity — see [architecture](00-architecture.md#iam-for-snapshots).

## 3. Operator — `resources/02-restate-operator.values.yaml`

This one is a helm values file, not a kubectl manifest:

```bash
helm upgrade --install restate-operator \
  oci://ghcr.io/restatedev/restate-operator-helm \
  --version 3.0.1 \
  --namespace restate-operator \
  -f resources/02-restate-operator.values.yaml
```

CRDs ship with the chart and upgrade with it (v3+). Nothing else to install —
no cert-manager.

## 4. Storage class + cluster — `resources/03-…` and `resources/04-…`

```bash
kubectl apply -f resources/03-gp3-storageclass.yaml
kubectl apply -f resources/04-restate-cluster.yaml

kubectl -n restate get pods -w          # restate-0..2 -> Running
```

The pods come up **unprovisioned** (`auto-provision = false` in the config
TOML) and wait. The **operator bootstraps the cluster**: once `restate-0` is
Running it calls the ProvisionCluster gRPC API with no explicit parameters,
so the config TOML's defaults apply — 48 partitions, `{node: 2}` replication —
and the pods then turn Ready. Verify:

```bash
kubectl get restatecluster restate -o jsonpath='{.status.provisioned}'  # true
kubectl -n restate exec restate-0 -- restatectl status   # nodes, logs, partitions
```

Then prove the snapshot path (IAM role, region, bucket) end to end. Automatic
snapshots only fire once a partition has seen **both** 100k records **and**
5 minutes, so a misconfigured role would otherwise surface much later:

```bash
kubectl -n restate exec restate-0 -- restatectl snapshots create-snapshot
aws s3 ls "s3://$BUCKET/restate/snapshots/" --recursive | head
```

The `restate/snapshots` prefix is fixed by the manifest, which is why the
bucket must be **dedicated to this cluster**: a snapshot repository belongs to
exactly one Restate cluster, and a second cluster pointed at the same prefix
fails repository validation rather than silently mixing.

Manual fallback if you ever need it (`restatectl` ships in the restate image;
safe to re-run — an already-provisioned cluster is reported, not
re-initialized):

```bash
kubectl -n restate exec restate-0 -- restatectl provision --yes
```

## 5. Compute — `resources/05-restate-compute.yaml`

Set the image, then:

```bash
kubectl apply -f resources/05-restate-compute.yaml
kubectl -n restate-apps get restatedeployments   # READY + registered
```

The operator registers each revision with the cluster's admin API itself and
labels the pods `allow.restate.dev/restate: "true"`, which the cluster's
egress NetworkPolicy matches — cross-namespace invocation needs no extra
config (details in [architecture](00-architecture.md#cross-namespace-networking)).
Versioning, draining and rollback of these services:
[deploying services](03-deploying-services.md).

## 6. Poke it

```bash
# svc/restate is the ClusterIP Service carrying 8080 + 9070; svc/restate-cluster
# is the headless node-to-node Service and only has 5122.
kubectl -n restate port-forward svc/restate 8080:8080 9070:9070 &
curl localhost:9070/services | jq       # admin API (or: restate services list)
curl localhost:8080/MyService/myHandler --json '{}'
```

Port-forward tunnels through the kubelet, so the deny-all NetworkPolicies
don't apply — this is the intended path to the admin API, which has no
authentication and is deliberately not network-exposed to workloads
(see [architecture](00-architecture.md#cross-namespace-networking)).
