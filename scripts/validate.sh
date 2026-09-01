#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPOSITORY_ROOT"

export TF_IN_AUTOMATION=1

tofu fmt -check -recursive terraform

for TOFU_STAGE in terraform/01-foundation terraform/02-restate; do
  tofu -chdir="$TOFU_STAGE" init -backend=false -input=false -no-color >/dev/null
  tofu -chdir="$TOFU_STAGE" validate -no-color
done

ruby scripts/check_repository.rb
