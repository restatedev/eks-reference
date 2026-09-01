# Building the manual deployment PDF

This directory contains the source for the committed customer-facing manual
deployment companion:

```text
misc/pdf/build_manual_reference.py
  -> output/pdf/restate-eks-manual-deployment-reference.pdf
```

The PDF is intentionally versioned. It is useful as a printable change-review,
field-installation, and handoff reference alongside the more detailed Markdown
documentation. The Markdown files and manifests remain the source of truth.

This guide is written so that an LLM coding agent can regenerate the artifact
without relying on context from the conversation that originally produced it.

## Source material

Before changing the PDF, read the current versions of:

- `README.md`
- `docs/01-prerequisites.md`
- `docs/02-runbook.md`
- `docs/00-architecture.md`
- `docs/05-operations.md`
- `docs/03-deploying-services.md`
- `resources/00-namespaces.yaml` through
  `resources/06-restate-service-cidr-egress.yaml`

Do not copy a command or version from memory. Keep the PDF consistent with the
checked-out repository, especially for image versions, chart versions, ports,
resource names, sizing, IAM trust, NetworkPolicy behavior, and teardown order.

## Build environment

The repository's Nix shell includes Python, ReportLab, pypdf, pdfplumber, and
Poppler:

```bash
nix-shell
```

Outside Nix, install the equivalent tools in an isolated environment:

```bash
python3 -m venv /tmp/eks-reference-pdf-venv
/tmp/eks-reference-pdf-venv/bin/pip install reportlab pypdf pdfplumber
# Also install Poppler so pdfinfo and pdftoppm are available.
```

## Reproduce the committed PDF

The generator defaults preserve the source revision and date printed in the
committed artifact:

```bash
python3 misc/pdf/build_manual_reference.py
```

The stable output path is:

```text
output/pdf/restate-eks-manual-deployment-reference.pdf
```

## Build a new revision

When the repository documentation or manifests change, pass the new source
metadata explicitly. Run this only after the relevant repository changes are
final:

```bash
python3 misc/pdf/build_manual_reference.py \
  --baseline "$(git rev-parse --short=8 HEAD)" \
  --source-commit "$(git rev-parse HEAD)" \
  --source-date "$(git show -s --format=%cs HEAD)" \
  --prepared "$(date '+%d %B %Y')"
```

Use `--output <path>` only for a review copy. The committed customer artifact
must retain the stable path under `output/pdf/`.

## Required LLM workflow

An LLM updating this artifact should follow this sequence:

1. Inspect `git status` and preserve unrelated user changes.
2. Read the source material listed above and identify every fact that changed.
3. Update the generator content and metadata. Keep command examples copyable,
   line lengths within their code boxes, and ASCII hyphens in generated text.
4. Generate the PDF with the repository's Python environment.
5. Reopen it with pypdf or pdfplumber and confirm the expected page count,
   section headings, extractable text, and page bounds.
6. Render every page to PNG with Poppler and visually inspect every rendered
   page. Check for clipping, overflow, overlaps, broken tables, poor page
   balance, unreadable text, black squares, and inconsistent headers or
   footers.
7. Fix every visual defect, regenerate, and repeat both programmatic and visual
   checks. Text extraction alone is not layout validation.
8. Remove `tmp/pdfs/` after review. Commit the generator, this build guide, and
   the final PDF together only when explicitly requested.

## Programmatic checks

Create temporary renders under the repository-local scratch directory:

```bash
mkdir -p tmp/pdfs
pdfinfo output/pdf/restate-eks-manual-deployment-reference.pdf
pdftoppm -png -r 120 \
  output/pdf/restate-eks-manual-deployment-reference.pdf \
  tmp/pdfs/manual-reference
```

Then run a structural check in the same Python environment:

```bash
python3 - <<'PY'
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

path = Path("output/pdf/restate-eks-manual-deployment-reference.pdf")
reader = PdfReader(path)
assert reader.pages
assert all((page.extract_text() or "").strip() for page in reader.pages)

with pdfplumber.open(path) as pdf:
    for page_number, page in enumerate(pdf.pages, 1):
        rightmost = max((char["x1"] for char in page.chars), default=0)
        assert rightmost <= 540, (page_number, rightmost)

print(f"validated {path} ({len(reader.pages)} pages)")
PY
```

The `540` point bound corresponds to the current A4 content frame. If the page
geometry changes, update both the generator and this check deliberately.

## Content and design rules

- Write for a customer cloud or platform engineer who understands AWS and EKS
  but may not know Restate.
- Lead with outcomes, stop conditions, and evidence. Keep internal rationale
  only where it changes an operator decision.
- Separate the EKS cluster, Restate cluster, and optional SDK service clearly.
- Keep port 9070 described as an unauthenticated admin boundary and never imply
  that the operator-managed Service should be exposed publicly.
- Preserve the distinction between retained EBS volumes and S3 snapshots;
  neither is an automatic disaster-recovery procedure.
- Keep optional application deployment separate from infrastructure acceptance.
- Do not add credentials, account identifiers, bucket names, or customer data.
- When the PDF and repository disagree, the checked-out repository wins.

## Final repository validation

After PDF QA and before committing, run:

```bash
nix-shell --run ./scripts/validate.sh
git diff --check
git status --short
```

The PDF generator and artifact are not run by ordinary repository validation
because visual inspection is a required part of their release process.
