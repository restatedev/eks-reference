# Runbook

Apply the files in [`resources/`](../resources/) in numeric order. Each step
below names the resource it consumes. Check
[prerequisites](00-prerequisites.md) and fill every `REPLACE_ME` first.

## 0. Auth + kubeconfig

```bash
export CLUSTER=...  REGION=...  ACCOUNT=...  BUCKET=...

aws sts get-caller-identity            # sanity
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"
```

## 1. Namespaces — `resources/00-namespaces.yaml`

Creates `restate-operator` (helm target) and `restate-apps` (compute). The
`restate` namespace is **not** here — the operator creates it from the
RestateCluster in step 4.

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
aws iam create-policy --policy-name restate-snapshots --policy-document file:///tmp/policy.json

# --role-only: the operator owns the ServiceAccount, we only need the role + trust policy
eksctl create iamserviceaccount --cluster "$CLUSTER" --region "$REGION" \
  --namespace restate --name restate \
  --role-name restate-snapshots \
  --attach-policy-arn "arn:aws:iam::$ACCOUNT:policy/restate-snapshots" \
  --role-only --approve
```

Then fill the role ARN into `resources/04-restate-cluster.yaml` →
`security.serviceAccountAnnotations`.

*Alternative (what Restate Cloud itself runs):* operator-managed EKS Pod
Identity — see [architecture](02-architecture.md#iam-for-snapshots).

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

The pods come up **unprovisioned** and wait (`auto-provision = false` in the
config TOML). Provision once, against any single node — `restatectl` ships in
the restate image:

```bash
kubectl -n restate exec restate-0 -- restatectl provision --yes
kubectl -n restate exec restate-0 -- restatectl status   # nodes, logs, partitions
```

Run without flags, `provision` adopts the contacted node's configured
defaults — 48 partitions, `{node: 2}` replication from the config TOML. Drop
`--yes` (and add `-it` to the exec) to review the dry-run configuration
interactively before confirming. Re-running is safe: an already-provisioned
cluster is reported, not re-initialized.

## 5. Compute — `resources/05-restate-compute.yaml`

Set the image, then:

```bash
kubectl apply -f resources/05-restate-compute.yaml
kubectl -n restate-apps get restatedeployments   # READY + registered
```

The operator registers each revision with the cluster's admin API itself and
labels the pods `allow.restate.dev/restate: "true"`, which the cluster's
egress NetworkPolicy matches — cross-namespace invocation needs no extra
config (details in [architecture](02-architecture.md#cross-namespace-networking)).

## 6. Poke it

```bash
kubectl -n restate port-forward svc/restate-cluster 8080:8080 9070:9070 &
curl localhost:9070/services | jq       # admin API (or: restate services list)
curl localhost:8080/MyService/myHandler --json '{}'
```
