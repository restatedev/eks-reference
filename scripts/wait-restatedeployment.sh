#!/usr/bin/env bash
set -euo pipefail

: "${CLUSTER_NAME:?Set CLUSTER_NAME to the EKS cluster name}"
: "${AWS_REGION:?Set AWS_REGION to the EKS cluster region}"
: "${RSD_NAMESPACE:?Set RSD_NAMESPACE to the RestateDeployment namespace}"
: "${RSD_NAME:?Set RSD_NAME to the RestateDeployment name}"

RSD_TIMEOUT_SECONDS="${RSD_TIMEOUT_SECONDS:-600}"

for command in aws kubectl jq; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

TEMP_KUBECONFIG="$(mktemp "${TMPDIR:-/tmp}/restate-kubeconfig.XXXXXX")"
trap 'rm -f -- "$TEMP_KUBECONFIG"' EXIT

aws eks update-kubeconfig \
  --dry-run \
  --name "$CLUSTER_NAME" \
  --region "$AWS_REGION" >"$TEMP_KUBECONFIG"

deadline=$((SECONDS + RSD_TIMEOUT_SECONDS))
last_summary=""

echo "Waiting for RestateDeployment ${RSD_NAMESPACE}/${RSD_NAME} to become Ready at its current generation..."

while ((SECONDS < deadline)); do
  if deployment_json="$(
    kubectl --kubeconfig "$TEMP_KUBECONFIG" \
      --namespace "$RSD_NAMESPACE" \
      get restatedeployment "$RSD_NAME" \
      --output json 2>/dev/null
  )"; then
    summary="$(
      jq -j '
        (.status.conditions // [] | map(select(.type == "Ready")) | last) as $ready
        | [
            (.metadata.generation // 0),
            (.status.observedGeneration // 0),
            ($ready.status // "Missing"),
            ($ready.reason // "NoReason"),
            ($ready.message // "No Ready condition reported")
          ]
        | map(tostring)
        | join("\u001f")
      ' <<<"$deployment_json"
    )"

    IFS=$'\x1f' read -r generation observed_generation ready_status ready_reason ready_message <<<"$summary"

    current_summary="generation=${generation}, observedGeneration=${observed_generation}, Ready=${ready_status}, reason=${ready_reason}: ${ready_message}"
    if [[ "$current_summary" != "$last_summary" ]]; then
      echo "$current_summary"
      last_summary="$current_summary"
    fi

    if [[ "$observed_generation" =~ ^[0-9]+$ ]] \
      && [[ "$generation" =~ ^[0-9]+$ ]] \
      && ((observed_generation >= generation)) \
      && [[ "$ready_status" == "True" ]]; then
      echo "RestateDeployment ${RSD_NAMESPACE}/${RSD_NAME} is Ready at generation ${generation}."
      exit 0
    fi
  elif [[ "$last_summary" != "resource not found" ]]; then
    echo "RestateDeployment ${RSD_NAMESPACE}/${RSD_NAME} is not readable yet; continuing to wait."
    last_summary="resource not found"
  fi

  sleep 3
done

echo "Timed out after ${RSD_TIMEOUT_SECONDS}s waiting for RestateDeployment ${RSD_NAMESPACE}/${RSD_NAME}." >&2
if [[ -n "$last_summary" ]]; then
  echo "Last status: ${last_summary}" >&2
fi
exit 1
