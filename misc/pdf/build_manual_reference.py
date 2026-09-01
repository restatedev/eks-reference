#!/usr/bin/env python3
"""Build the customer-facing manual deployment reference PDF."""

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = "output/pdf/restate-eks-manual-deployment-reference.pdf"
DEFAULT_SOURCE_COMMIT = "388fbec8fdb93b9e9218efaae8fc7fb63120a50b"
DEFAULT_SOURCE_DATE = "2026-09-01"
DEFAULT_PREPARED = "1 September 2026"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", default=DEFAULT_OUTPUT)
parser.add_argument("--source-commit", default=DEFAULT_SOURCE_COMMIT)
parser.add_argument("--source-date", default=DEFAULT_SOURCE_DATE)
parser.add_argument("--prepared", default=DEFAULT_PREPARED)
parser.add_argument(
    "--baseline",
    default=DEFAULT_SOURCE_COMMIT[:8],
    help="Short source revision shown in page headers",
)
args = parser.parse_args()

OUTPUT = Path(args.output)
if not OUTPUT.is_absolute():
    OUTPUT = ROOT / OUTPUT
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

PAGE_W, PAGE_H = A4
NAVY = colors.HexColor("#102A43")
INK = colors.HexColor("#243B53")
MUTED = colors.HexColor("#627D98")
TEAL = colors.HexColor("#007F86")
TEAL_PALE = colors.HexColor("#E6F6F7")
AMBER = colors.HexColor("#B35C00")
AMBER_PALE = colors.HexColor("#FFF3DD")
RED = colors.HexColor("#B42318")
RED_PALE = colors.HexColor("#FDECEC")
GREEN = colors.HexColor("#1F7A4D")
GREEN_PALE = colors.HexColor("#E9F7EF")
LINE = colors.HexColor("#D9E2EC")
SURFACE = colors.HexColor("#F5F7FA")
WHITE = colors.white


styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="CoverKicker",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#8BE0E3"),
        spaceAfter=10,
        tracking=1.4,
    )
)
styles.add(
    ParagraphStyle(
        name="CoverTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=32,
        leading=37,
        textColor=WHITE,
        spaceAfter=16,
    )
)
styles.add(
    ParagraphStyle(
        name="CoverSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=13,
        leading=19,
        textColor=colors.HexColor("#D9EAF0"),
        spaceAfter=16,
    )
)
styles.add(
    ParagraphStyle(
        name="CoverMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.2,
        leading=14,
        textColor=colors.HexColor("#B8CDD9"),
    )
)
styles.add(
    ParagraphStyle(
        name="SectionKicker",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=TEAL,
        spaceAfter=5,
        tracking=1.1,
    )
)
styles.add(
    ParagraphStyle(
        name="H1Custom",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=27,
        textColor=NAVY,
        spaceBefore=0,
        spaceAfter=9,
    )
)
styles.add(
    ParagraphStyle(
        name="Lead",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.4,
        leading=15.5,
        textColor=MUTED,
        spaceAfter=13,
    )
)
styles.add(
    ParagraphStyle(
        name="H2Custom",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=NAVY,
        spaceBefore=11,
        spaceAfter=6,
    )
)
styles.add(
    ParagraphStyle(
        name="BodyCustom",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.2,
        leading=13.3,
        textColor=INK,
        spaceAfter=7,
    )
)
styles.add(
    ParagraphStyle(
        name="BodySmall",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.1,
        leading=11.6,
        textColor=INK,
        spaceAfter=5,
    )
)
styles.add(
    ParagraphStyle(
        name="BulletCustom",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.9,
        leading=12.8,
        leftIndent=13,
        firstLineIndent=-9,
        bulletIndent=1,
        textColor=INK,
        spaceAfter=4,
    )
)
styles.add(
    ParagraphStyle(
        name="CodeCustom",
        parent=styles["Code"],
        fontName="Courier",
        fontSize=7.1,
        leading=9.8,
        textColor=colors.HexColor("#102A43"),
    )
)
styles.add(
    ParagraphStyle(
        name="TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=WHITE,
    )
)
styles.add(
    ParagraphStyle(
        name="TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.8,
        leading=10.6,
        textColor=INK,
    )
)
styles.add(
    ParagraphStyle(
        name="TableCellBold",
        parent=styles["TableCell"],
        fontName="Helvetica-Bold",
        textColor=NAVY,
    )
)
styles.add(
    ParagraphStyle(
        name="CalloutLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.4,
        leading=9,
        textColor=NAVY,
        spaceAfter=2,
        tracking=0.6,
    )
)
styles.add(
    ParagraphStyle(
        name="CalloutBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.4,
        leading=11.7,
        textColor=INK,
    )
)


def P(text, style="BodyCustom"):
    return Paragraph(text, styles[style])


def bullet(text):
    return Paragraph("- " + text, styles["BulletCustom"])


def section(kicker, title, lead):
    return [
        P(kicker.upper(), "SectionKicker"),
        P(title, "H1Custom"),
        P(lead, "Lead"),
    ]


def code(text):
    content = Preformatted(text.strip("\n"), styles["CodeCustom"])
    box = Table([[content]], colWidths=[169 * mm], hAlign="LEFT")
    box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return box


def callout(label, body, tone="blue"):
    palette = {
        "blue": (TEAL_PALE, TEAL),
        "amber": (AMBER_PALE, AMBER),
        "red": (RED_PALE, RED),
        "green": (GREEN_PALE, GREEN),
    }
    bg, accent = palette[tone]
    inner = [P(label.upper(), "CalloutLabel"), P(body, "CalloutBody")]
    table = Table([[inner]], colWidths=[169 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def data_table(headers, rows, widths, font_size=7.8):
    header = [P(h, "TableHeader") for h in headers]
    data = [header]
    for row in rows:
        data.append(
            [
                P(str(cell), "TableCellBold" if idx == 0 else "TableCell")
                for idx, cell in enumerate(row)
            ]
        )
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SURFACE]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def two_cards(left_title, left_body, right_title, right_body):
    left = [P(left_title, "TableCellBold"), Spacer(1, 3), P(left_body, "TableCell")]
    right = [P(right_title, "TableCellBold"), Spacer(1, 3), P(right_body, "TableCell")]
    table = Table([[left, right]], colWidths=[82.5 * mm, 82.5 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("BOX", (0, 0), (0, 0), 0.7, LINE),
                ("BOX", (1, 0), (1, 0), 0.7, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def draw_cover(canvas, doc):
    canvas.saveState()
    canvas.setTitle("Restate on Amazon EKS - Manual Deployment Reference and Best Practices")
    canvas.setAuthor("Restate EKS reference repository")
    canvas.setSubject("Manual installation companion for Restate on an existing EKS cluster")
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#0B737A"))
    canvas.rect(0, 0, 16 * mm, PAGE_H, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#164A63"))
    canvas.circle(PAGE_W - 9 * mm, PAGE_H - 28 * mm, 39 * mm, stroke=0, fill=1)
    canvas.setStrokeColor(colors.HexColor("#2E677E"))
    canvas.setLineWidth(0.8)
    for offset in range(5):
        y = 35 * mm + offset * 8 * mm
        canvas.line(22 * mm, y, PAGE_W - 22 * mm, y)
    canvas.restoreState()


def draw_later(canvas, doc):
    canvas.saveState()
    canvas.setTitle("Restate on Amazon EKS - Manual Deployment Reference and Best Practices")
    canvas.setAuthor("Restate EKS reference repository")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, PAGE_H - 17 * mm, PAGE_W - 20 * mm, PAGE_H - 17 * mm)
    canvas.setFont("Helvetica-Bold", 7.2)
    canvas.setFillColor(NAVY)
    canvas.drawString(20 * mm, PAGE_H - 13 * mm, "RESTATE ON AMAZON EKS")
    canvas.setFont("Helvetica", 7.2)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(
        PAGE_W - 20 * mm,
        PAGE_H - 13 * mm,
        f"Manual deployment reference | Baseline {args.baseline}",
    )
    canvas.line(20 * mm, 16 * mm, PAGE_W - 20 * mm, 16 * mm)
    canvas.setFont("Helvetica", 7.2)
    canvas.drawString(20 * mm, 10.5 * mm, "Companion artifact - use with the repository version shown")
    canvas.drawRightString(PAGE_W - 20 * mm, 10.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(
    str(OUTPUT),
    pagesize=A4,
    rightMargin=20 * mm,
    leftMargin=20 * mm,
    topMargin=23 * mm,
    bottomMargin=21 * mm,
    title="Restate on Amazon EKS - Manual Deployment Reference and Best Practices",
    author="Restate EKS reference repository",
    subject="Manual deployment companion",
)

story = []

# Cover
story.extend(
    [
        Spacer(1, 40 * mm),
        P("CUSTOMER OPERATIONS COMPANION", "CoverKicker"),
        P("Restate on<br/>Amazon EKS", "CoverTitle"),
        P("Manual Deployment Reference<br/>and Best Practices", "CoverSub"),
        Spacer(1, 14 * mm),
        callout(
            "PURPOSE",
            "A field-ready companion for the cloud or platform engineer asked to install Restate into an existing EKS cluster. It condenses the repository runbook into deployment gates, commands, evidence, and safety boundaries.",
            "blue",
        ),
        Spacer(1, 17 * mm),
        P(
            f"Repository baseline: <b>{args.baseline}</b><br/>"
            "Restate image: <b>1.7.7</b> &nbsp;&nbsp; Operator chart: <b>3.0.1</b><br/>"
            "Reference topology: <b>3 nodes / 48 partitions / replication 2</b><br/>"
            f"Prepared: <b>{args.prepared}</b>",
            "CoverMeta",
        ),
    ]
)
story.append(PageBreak())

# 1
story.extend(
    section(
        "01 / Orientation",
        "What this reference deploys",
        "Restate is a durable execution runtime. This reference installs the runtime and its Kubernetes operator into an existing EKS cluster; it does not create the EKS cluster or deploy a customer application.",
    )
)
story.append(
    data_table(
        ["Layer", "What it means", "Ownership"],
        [
            ("EKS cluster", "Existing AWS and Kubernetes infrastructure", "Customer platform team; this repository does not create it"),
            ("Restate cluster", "Three stateful Restate server pods managed by a RestateCluster custom resource", "Restate operator inside EKS"),
            ("SDK service", "Application code built with a Restate SDK and listening on port 9080", "Application team; deployed separately"),
        ],
        [36 * mm, 72 * mm, 61 * mm],
    )
)
story.append(Spacer(1, 8))
story.append(P("Deployment shape", "H2Custom"))
story.append(
    data_table(
        ["Component", "Reference value", "Operational meaning"],
        [
            ("Restate", "3 replicas; 24 vCPU and 50 GiB each", "Requires three different eligible nodes"),
            ("Data", "1 TiB encrypted gp3 per pod; Retain", "EBS survives PVC deletion; reattachment is manual"),
            ("Snapshots", "Dedicated S3 bucket through IRSA", "One bucket or unique prefix per Restate cluster"),
            ("Network", "Default-deny policies where enforced", "Admin 9070 stays private; SDK port 9080 is isolated"),
            ("Exposure", "ClusterIP only", "No ingress, DNS, public endpoint, or auth gateway is created"),
        ],
        [36 * mm, 55 * mm, 78 * mm],
    )
)
story.append(Spacer(1, 9))
story.append(
    two_cards(
        "This guide is for",
        "A cloud or platform engineer with AWS, EKS, IAM, Kubernetes, Helm, and change-management access. Detailed Restate internals are not assumed.",
        "The successful handoff",
        "A Ready three-node Restate cluster, Bound EBS volumes, a proven S3 snapshot path, verified network posture, and recorded ownership. No application or public ingress is implied.",
    )
)
story.append(Spacer(1, 9))
story.append(
    callout(
        "CHOOSE ONE DELIVERY PATH",
        "This artifact covers the manual AWS CLI, eksctl, Helm, and kubectl path. Please use either the manual or Terraform path for an installation. If Terraform will take over manually created resources, import them into state before switching.",
        "amber",
    )
)
story.append(PageBreak())

# 2
story.extend(
    section(
        "02 / Readiness",
        "Readiness checks before you begin",
        "Please confirm each item below before the first apply and record the evidence in the change ticket. If an item is not yet confirmed, pause here and resolve it before continuing.",
    )
)
story.append(
    data_table(
        ["Check", "Ready when", "Why it matters"],
        [
            ("Identity", "AWS account, region, EKS name, and kubectl context are confirmed", "Prevents a correct deployment to the wrong environment"),
            ("Capacity", "3 eligible nodes each have at least 24 CPU and 50 GiB remaining by requests", "Hard host anti-affinity allows one Restate pod per node"),
            ("Storage", "EBS CSI controller is healthy; persistent EBS is supported", "The three data volumes must survive node replacement"),
            ("IP family", "EKS reports ipv4 and a Service IPv4 CIDR", "The supplied Service-CIDR policy is IPv4-only"),
            ("NetworkPolicy", "Enforcement state and trust decision are documented", "Objects are inert unless the CNI enforces them"),
            ("Snapshots", "A unique, dedicated S3 bucket exists in the target region", "The configured snapshot prefix is shared by every default install"),
            ("Authorization", "Required AWS permissions and six kubectl can-i checks pass", "Installation creates IAM, cluster-scoped RBAC, CRDs, and storage"),
            ("IRSA", "OIDC exists or the approved change includes creating it", "The Restate ServiceAccount needs STS web identity"),
        ],
        [32 * mm, 76 * mm, 61 * mm],
    )
)
story.append(Spacer(1, 9))
story.append(P("Set and verify the target", "H2Custom"))
story.append(
    code(
        """
export CLUSTER=...
export REGION=...
export BUCKET=...   # globally unique; dedicated to this Restate cluster
export ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

aws sts get-caller-identity
aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \\
  --query \\
  'cluster.{name:name,status:status,ipFamily:kubernetesNetworkConfig.ipFamily}'
aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \\
  --query 'cluster.kubernetesNetworkConfig.serviceIpv4Cidr' --output text
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION"
kubectl config current-context
kubectl cluster-info
"""
    )
)
story.append(Spacer(1, 8))
story.append(
    callout(
        "PLEASE PAUSE AND CHECK",
        "If the account, cluster, context, region, or bucket is not the reviewed target, please pause and correct it before continuing. This reference currently supports EKS clusters where <b>ipFamily</b> is <b>ipv4</b>.",
        "red",
    )
)
story.append(PageBreak())

# 3
story.extend(
    section(
        "03 / Preflight",
        "Prove capacity, access, and dependencies",
        "Scheduler capacity is based on requested resources, not current utilization. IAM access and Kubernetes authorization are also separate checks.",
    )
)
story.append(P("Capacity and EBS", "H2Custom"))
story.append(
    code(
        """
kubectl get nodes -L topology.kubernetes.io/zone
kubectl describe node <candidate-node>   # inspect Allocated resources

aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \\
  --addon-name aws-ebs-csi-driver --query 'addon.{status:status,version:addonVersion}'
kubectl -n kube-system get deployment ebs-csi-controller
"""
    )
)
story.append(Spacer(1, 7))
story.append(
    callout(
        "CAPACITY RULE",
        "Each of three different eligible nodes needs 24 CPU and 50 GiB still available after existing pod and DaemonSet requests. Please use the node's <b>Allocated resources</b> view rather than <b>kubectl top</b>, because the scheduler works from requests.",
        "amber",
    )
)
story.append(P("Kubernetes authorization", "H2Custom"))
story.append(
    code(
        """
kubectl auth can-i create namespaces
kubectl auth can-i create storageclasses.storage.k8s.io
kubectl auth can-i create networkpolicies.networking.k8s.io --all-namespaces
kubectl auth can-i create customresourcedefinitions.apiextensions.k8s.io
kubectl auth can-i create clusterroles.rbac.authorization.k8s.io
kubectl auth can-i create clusterrolebindings.rbac.authorization.k8s.io
"""
    )
)
story.append(Spacer(1, 7))
story.append(P("NetworkPolicy enforcement", "H2Custom"))
story.append(
    code(
        """
aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" \\
  --addon-name vpc-cni --query addon.configurationValues
kubectl api-resources | grep policyendpoints
"""
    )
)
story.append(Spacer(1, 7))
story.append(
    two_cards(
        "Enforcement on",
        "Preferred for shared clusters. The EKS VPC CNI must have <b>enableNetworkPolicy: true</b>. Apply the Service-CIDR egress policy after the Restate namespace exists.",
        "Enforcement off",
        "Formally supported only with an explicit trust decision. NetworkPolicy objects still appear, but every pod can reach the unauthenticated admin API and SDK endpoints.",
    )
)
story.append(PageBreak())

# 4
story.extend(
    section(
        "04 / Change preparation",
        "Prepare a reviewable installation",
        "Run commands from the repository root. Keep substitutions visible in a working copy or branch, and compare every applied file with the approved change.",
    )
)
story.append(
    data_table(
        ["Order", "Repository asset", "Action"],
        [
            ("1", "resources/00-namespaces.yaml", "Create restate-operator and restate-apps; leave restate to the operator"),
            ("2", "resources/01-restate-snapshots-iam-policy.json", "Render a temporary policy with the dedicated bucket"),
            ("3", "resources/02-restate-operator.values.yaml", "Pass to Helm as values; this file is not a kubectl manifest"),
            ("4", "resources/03-gp3-storageclass.yaml", "Create encrypted gp3 with Retain and delayed binding"),
            ("5", "resources/04-restate-cluster.yaml", "Set region, bucket, and snapshot role ARN; then apply"),
            ("6", "resources/06-restate-service-cidr-egress.yaml", "Render with the real Service CIDR where policy is enforced"),
            ("Optional", "resources/05-restate-compute.yaml", "Apply only after a real SDK service image is set"),
        ],
        [18 * mm, 72 * mm, 79 * mm],
    )
)
story.append(Spacer(1, 9))
story.append(P("Placeholder discipline", "H2Custom"))
story.append(
    code(
        """
grep -RIn 'REPLACE_ME' resources
git diff -- resources
"""
    )
)
story.append(Spacer(1, 6))
story.append(
    data_table(
        ["Placeholder", "Required value"],
        [
            ("REPLACE_ME_SNAPSHOTS_BUCKET", "Dedicated bucket name in IAM policy render and RestateCluster"),
            ("REPLACE_ME_AWS_REGION", "Target AWS region"),
            ("REPLACE_ME_SNAPSHOTS_ROLE_ARN", "arn:aws:iam::<account>:role/<cluster>-restate-snapshots"),
            ("REPLACE_ME_SERVICE_CIDR", "EKS serviceIpv4Cidr; render through stdin"),
            ("REPLACE_ME_SERVICE_IMAGE", "Only for the optional SDK-service example"),
        ],
        [74 * mm, 95 * mm],
    )
)
story.append(Spacer(1, 9))
story.append(
    callout(
        "OWNERSHIP BOUNDARY",
        "Create <b>restate-operator</b> and <b>restate-apps</b>, and please leave <b>restate</b> for the operator to create and own from RestateCluster/restate. That ownership includes its StatefulSet, Services, ServiceAccount, PVCs, and policies.",
        "blue",
    )
)
story.append(PageBreak())

# 5
story.extend(
    section(
        "05 / AWS plane",
        "Create snapshot access with IRSA",
        "The manual path assumes a pre-existing, dedicated S3 bucket. Verify its controls before creating a least-privilege policy and a role trusted only by the Restate ServiceAccount.",
    )
)
story.append(P("1. Apply repository-owned namespaces", "H2Custom"))
story.append(
    code(
        """
kubectl apply -f resources/00-namespaces.yaml
kubectl get namespace restate-operator restate-apps
kubectl -n restate-apps get networkpolicy
"""
    )
)
story.append(P("2. Verify the bucket and OIDC provider", "H2Custom"))
story.append(
    code(
        """
aws s3api head-bucket --bucket "$BUCKET"
aws s3api get-bucket-location --bucket "$BUCKET"
aws s3api get-public-access-block --bucket "$BUCKET"
aws s3api get-bucket-policy --bucket "$BUCKET" --query Policy --output text | jq

eksctl utils associate-iam-oidc-provider \\
  --cluster "$CLUSTER" --region "$REGION" --approve
"""
    )
)
story.append(P("3. Create the IAM policy and role", "H2Custom"))
story.append(
    code(
        """
sed "s/REPLACE_ME_SNAPSHOTS_BUCKET/$BUCKET/" \\
  resources/01-restate-snapshots-iam-policy.json > /tmp/restate-snapshot-policy.json

aws iam create-policy --policy-name "${CLUSTER}-restate-snapshots" \\
  --policy-document file:///tmp/restate-snapshot-policy.json

eksctl create iamserviceaccount --cluster "$CLUSTER" --region "$REGION" \\
  --namespace restate --name restate --role-name "${CLUSTER}-restate-snapshots" \\
  --attach-policy-arn "arn:aws:iam::$ACCOUNT:policy/${CLUSTER}-restate-snapshots" \\
  --role-only --approve
"""
    )
)
story.append(Spacer(1, 7))
story.append(
    callout(
        "VERIFY BEFORE CONTINUING",
        "The role trust should name <b>system:serviceaccount:restate:restate</b>, and the policy and Restate snapshot destination should name the same bucket. The derived role name limits <b>CLUSTER</b> to 46 characters.",
        "green",
    )
)
story.append(PageBreak())

# 6
story.extend(
    section(
        "06 / Control plane",
        "Install and verify the operator",
        "Helm installs the controller, CRDs, and cluster RBAC. Keep the chart version pinned and wait for the deployment rather than racing ahead to custom resources.",
    )
)
story.append(P("Install", "H2Custom"))
story.append(
    code(
        """
helm upgrade --install restate-operator \\
  oci://ghcr.io/restatedev/restate-operator-helm \\
  --version 3.0.1 \\
  --namespace restate-operator \\
  --values resources/02-restate-operator.values.yaml \\
  --wait --timeout 5m
"""
    )
)
story.append(P("Verify", "H2Custom"))
story.append(
    code(
        """
kubectl -n restate-operator get deployment,pods
kubectl get crd \\
  restateclusters.restate.dev \\
  restatedeployments.restate.dev \\
  restatecloudenvironments.restate.dev
"""
    )
)
story.append(Spacer(1, 8))
story.append(
    data_table(
        ["Check", "Expected", "If it fails"],
        [
            ("Helm release", "deployed in restate-operator", "Inspect Helm status and controller events"),
            ("Controller", "Deployment Available; pod Ready", "Read controller logs before creating RestateCluster"),
            ("CRDs", "All three definitions served", "Please wait for the schemas before applying custom resources"),
            ("Registry pull", "Public anonymous pull succeeds", "Clear stale ghcr.io credentials; authenticate only if your environment requires it"),
        ],
        [36 * mm, 61 * mm, 72 * mm],
    )
)
story.append(Spacer(1, 9))
story.append(P("Registry diagnostic", "H2Custom"))
story.append(
    code(
        """
helm registry logout ghcr.io || true
docker logout ghcr.io || true
helm pull oci://ghcr.io/restatedev/restate-operator-helm \\
  --version 3.0.1 --destination /tmp
"""
    )
)
story.append(Spacer(1, 8))
story.append(
    callout(
        "CRD LIFECYCLE",
        "The chart marks its CRDs to survive Helm uninstall. That is intentional. During teardown, retain them until a cluster-wide check confirms that no Restate operator installation or custom resource remains.",
        "amber",
    )
)
story.append(PageBreak())

# 7
story.extend(
    section(
        "07 / Data plane",
        "Create storage and bootstrap Restate",
        "Apply storage first, confirm its safety settings, then apply the RestateCluster. The operator performs the one-time cluster provisioning after the pods form metadata membership.",
    )
)
story.append(P("1. Create and inspect the StorageClass", "H2Custom"))
story.append(
    code(
        """
kubectl apply -f resources/03-gp3-storageclass.yaml
kubectl get storageclass restate-gp3 -o yaml
"""
    )
)
story.append(
    callout(
        "EXPECTED STORAGE",
        "EBS CSI, encrypted XFS, 6000 IOPS, 500 MiB/s, WaitForFirstConsumer, allowVolumeExpansion, and reclaimPolicy Retain. Retain preserves EBS after PVC deletion; it does not perform automatic recovery.",
        "blue",
    )
)
story.append(P("2. Apply the cluster and watch bootstrap", "H2Custom"))
story.append(
    code(
        """
grep -n 'REPLACE_ME' resources/04-restate-cluster.yaml
kubectl apply -f resources/04-restate-cluster.yaml

kubectl get restatecluster restate -w
# second shell
kubectl -n restate get pods,pvc -w
"""
    )
)
story.append(P("3. Wait for the acceptance state", "H2Custom"))
story.append(
    code(
        """
kubectl wait --for=condition=Ready restatecluster/restate --timeout=15m
kubectl get restatecluster restate -o jsonpath='{.status.provisioned}{"\\n"}'
kubectl -n restate get pods -o wide
kubectl -n restate exec restate-0 -- restatectl status
"""
    )
)
story.append(Spacer(1, 8))
story.append(
    callout(
        "KEEP PROVISIONING OPERATOR-MANAGED",
        "Please leave provisioning to the operator while <b>spec.cluster.autoProvision</b> is enabled. Running <b>restatectl provision</b> at the same time can race the operator and split cluster initialization. If pods run but remain unready, inspect RestateCluster conditions and operator logs.",
        "red",
    )
)
story.append(PageBreak())

# 8
story.extend(
    section(
        "08 / Boundaries and backup",
        "Complete the network policy and verify snapshots",
        "Where EKS VPC CNI enforcement is enabled, Restate needs an additional egress rule to the cluster Service CIDR on port 9080. Then prove snapshot access end to end instead of waiting for the automatic cadence.",
    )
)
story.append(P("Apply the Service-CIDR policy", "H2Custom"))
story.append(
    code(
        """
SERVICE_CIDR="$(aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \\
  --query 'cluster.kubernetesNetworkConfig.serviceIpv4Cidr' --output text)"
echo "$SERVICE_CIDR"

sed "s|REPLACE_ME_SERVICE_CIDR|$SERVICE_CIDR|" \\
  resources/06-restate-service-cidr-egress.yaml | kubectl apply -f -
kubectl -n restate get networkpolicy allow-egress-to-service-cidr
kubectl -n restate get policyendpoints
"""
    )
)
story.append(Spacer(1, 7))
story.append(
    data_table(
        ["Traffic", "Port", "Intended boundary"],
        [
            ("Client -> Restate ingress", "8080", "Expose separately only when the customer designs ingress and authentication"),
            ("Human -> admin", "9070", "Use kubectl port-forward and keep the admin endpoint private"),
            ("Restate -> Restate", "5122", "Operator-managed node and metadata traffic"),
            ("Restate -> SDK revision", "9080", "Operator labels plus Service-CIDR policy where pre-DNAT enforcement applies"),
            ("Other workloads -> SDK", "9080", "Denied by the restate-apps ingress policy where enforcement is active"),
        ],
        [62 * mm, 20 * mm, 87 * mm],
    )
)
story.append(P("Trigger and verify a snapshot", "H2Custom"))
story.append(
    code(
        """
kubectl -n restate exec restate-0 -- restatectl snapshots create-snapshot
aws s3 ls "s3://$BUCKET/restate/snapshots/" --recursive | head
"""
    )
)
story.append(Spacer(1, 7))
story.append(
    callout(
        "ACCEPTANCE GATE",
        "Before handoff, please confirm that the manual snapshot succeeds and objects appear in S3. This single test exercises the ServiceAccount annotation, OIDC trust, IAM policy, region, egress path, bucket, and Restate configuration.",
        "green",
    )
)
story.append(PageBreak())

# 9
story.extend(
    section(
        "09 / Acceptance",
        "Validate and hand over",
        "Capture evidence, not only a verbal success. The platform owner should be able to repeat these checks without reconstructing the installation session.",
    )
)
story.append(P("Five-minute health check", "H2Custom"))
story.append(
    code(
        """
kubectl get restatecluster restate -o wide
kubectl get restatecluster restate \\
  -o jsonpath='{range .status.conditions[*]}{.type}{"="}{.status}{"  "}{.message}{"\\n"}{end}'
kubectl -n restate get pods -o wide
kubectl -n restate get pvc
kubectl -n restate get svc,networkpolicy
kubectl -n restate exec restate-0 -- restatectl status
"""
    )
)
story.append(Spacer(1, 7))
story.append(
    data_table(
        ["Evidence to retain", "Acceptance criterion"],
        [
            ("RestateCluster", "status.provisioned=true and Ready=True"),
            ("Placement", "restate-0, restate-1, and restate-2 Ready on different nodes"),
            ("Persistent data", "Three PVCs Bound through restate-gp3; PV/PVC/AZ/EBS mapping recorded"),
            ("Restate health", "restatectl status reports healthy nodes, logs, and partitions"),
            ("Snapshots", "Manual snapshot command and S3 object listing captured"),
            ("Exposure", "svc/restate remains ClusterIP; port 9070 has no public route"),
            ("Network", "CNI enforcement state recorded; policies and policy endpoints inspected"),
            ("Configuration", "No active REPLACE_ME value remains in an applied payload"),
        ],
        [56 * mm, 113 * mm],
    )
)
story.append(Spacer(1, 9))
story.append(P("Operator access", "H2Custom"))
story.append(
    code(
        """
kubectl -n restate port-forward svc/restate 8080:8080 9070:9070
# in a second shell
curl --fail --silent localhost:9070/services | jq
"""
    )
)
story.append(Spacer(1, 7))
story.append(
    callout(
        "HANDOFF RECORD",
        "Record the AWS account and region, EKS cluster and context, namespaces, bucket, role and policy ARNs, image and chart versions, capacity decision, NetworkPolicy enforcement state, snapshot evidence, ingress owner, and data-retention owner.",
        "blue",
    )
)
story.append(PageBreak())

# 10
story.extend(
    section(
        "10 / Optional application step",
        "Optional: add an SDK service when useful",
        "The infrastructure installation is complete without an application. If the customer also wants an SDK-service proof, use a real image and treat the operator-managed revision lifecycle as different from a normal Deployment rollout.",
    )
)
story.append(P("Apply the example skeleton", "H2Custom"))
story.append(
    code(
        """
# Set REPLACE_ME_SERVICE_IMAGE to an image that listens on port 9080.
grep -n 'REPLACE_ME' resources/05-restate-compute.yaml
kubectl apply -f resources/05-restate-compute.yaml
kubectl -n restate-apps get restatedeployments,pods -w
"""
    )
)
story.append(Spacer(1, 8))
story.append(
    data_table(
        ["Requirement", "Why"],
        [
            ("Container listens on 9080", "Restate invokes the SDK endpoint on this port"),
            ("Port is named restate", "The operator uses the named port to construct the registration URL"),
            ("spec.restate.register.cluster is restate", "The revision registers with the installed Restate cluster"),
            ("RestateDeployment becomes Ready", "Confirms image pull, pod health, registration, admin access, and the 9080 path"),
            ("Old revisions are allowed to drain", "Pinned in-flight invocations may still require the previous revision"),
        ],
        [62 * mm, 107 * mm],
    )
)
story.append(Spacer(1, 9))
story.append(
    two_cards(
        "Normal rollout",
        "Change the pod template, review the diff, and apply. The operator creates a versioned ReplicaSet and Service, registers the new revision, and drains the old revision.",
        "Rollback",
        "Reapply a previously known-good pod template. Please allow the old ReplicaSet to drain normally, because it may still own in-flight work.",
    )
)
story.append(Spacer(1, 9))
story.append(
    callout(
        "NETWORK DIAGNOSTIC",
        "Ready SDK pods with a RestateDeployment that remains NotReady often indicate a missing Service-CIDR egress policy. From a Restate pod, compare access to the revision pod IP and its Service ClusterIP on port 9080.",
        "amber",
    )
)
story.append(P("Customer-facing exposure", "H2Custom"))
story.append(P("Keep the operator-managed <b>svc/restate</b> as a ClusterIP because it carries both ingress 8080 and unauthenticated admin 9070. If shared ingress is required, create a separately owned Service or Ingress for <b>8080 only</b>, prefer internal exposure, add authentication, update the allowed network peer, and set the advertised ingress address deliberately."))
story.append(PageBreak())

# 11
story.extend(
    section(
        "11 / Troubleshooting and data safety",
        "Diagnose by layer; preserve recovery options",
        "To keep troubleshooting predictable, finish investigating the current change before making another. A helpful sequence is scheduling and storage, operator reconciliation, Restate status, IAM, and then network paths.",
    )
)
story.append(
    data_table(
        ["Symptom", "First evidence", "Common cause or safe action"],
        [
            ("Pod Pending", "Pod describe, events, node Allocated resources", "Capacity, anti-affinity, taint, EBS CSI, or an unavailable AZ"),
            ("Pods Running, not Ready", "RestateCluster YAML, Restate logs, operator logs", "Provisioning, peer DNS, or config validation; keep provisioning operator-managed"),
            ("Snapshot fails", "ServiceAccount, role trust, pod env, S3 path", "Wrong ARN, bucket, region, IAM policy, OIDC, or private endpoint blocked by egress"),
            ("SDK revision not Ready", "RestateDeployment describe, operator logs, pod IP vs ClusterIP", "Image/port issue or missing Service-CIDR egress rule"),
            ("Admin unreachable", "Service type, port-forward output, policy state", "Use svc/restate through kubectl port-forward and keep 9070 private"),
        ],
        [43 * mm, 60 * mm, 66 * mm],
    )
)
story.append(P("Before removal or other data-affecting changes", "H2Custom"))
story.append(
    code(
        """
kubectl -n restate get pvc -o wide
kubectl get pv \\
  -o jsonpath='{range .items[*]}{.metadata.name}{"  "}'\\
'{.spec.claimRef.namespace}/{.spec.claimRef.name}{"  "}'\\
'{.spec.csi.volumeHandle}{"\\n"}{end}'
kubectl -n restate exec restate-0 -- restatectl snapshots create-snapshot
aws s3 ls "s3://$BUCKET/restate/snapshots/" --recursive | head
"""
    )
)
story.append(Spacer(1, 7))
story.append(
    callout(
        "RECOVERY BOUNDARY",
        "Retained EBS PVs and S3 snapshots protect different failure modes, but neither is an automatic disaster-recovery workflow. Released PVs keep their old claim references and do not bind to replacement PVCs automatically.",
        "red",
    )
)
story.append(P("Safe-change pattern", "H2Custom"))
story.append(bullet("Verify cluster health and a recent snapshot before changing runtime sizing, storage, image, chart, or experimental settings."))
story.append(bullet("Review one change at a time. Pod-template changes can roll all three stateful pods and move partition leadership."))
story.append(bullet("Keep requested storage at its current size or increase it. Existing volume expansion depends on the EBS CSI driver and StorageClass."))
story.append(bullet("For upgrades, validate release compatibility and every experimental/profile-derived setting; changing only the image is not a complete upgrade plan."))
story.append(PageBreak())

# 12
story.extend(
    section(
        "12 / Teardown and source map",
        "A safe order for removal",
        "A manual deployment can be removed safely, but data and cluster-scoped definitions require explicit decisions. This is a boundary summary, not authorization to delete production data.",
    )
)
story.append(
    data_table(
        ["Order", "Action", "Safety note"],
        [
            ("1", "Pause new traffic; snapshot; capture PV/PVC/AZ/EBS mapping", "Complete before deleting a Kubernetes parent"),
            ("2", "Delete every RestateDeployment and wait for finalizers", "Allow finalizers to finish the drain"),
            ("3", "Delete RestateCluster/restate and wait for namespace deletion", "PVCs disappear; Retain should leave EBS volumes"),
            ("4", "Record Released PV and EBS mapping again", "Preserves the link between Kubernetes and billable AWS volumes"),
            ("5", "Uninstall operator; then namespaces and StorageClass", "Retain CRDs until the cluster-wide dependency check"),
            ("6", "Decide retention for EBS, S3, IAM, and OIDC", "OIDC is shared; bucket and volumes may still contain recovery data"),
        ],
        [18 * mm, 79 * mm, 72 * mm],
    )
)
story.append(Spacer(1, 3))
story.append(
    callout(
        "WHAT SURVIVES",
        "With the repository defaults, three EBS volumes, the S3 bucket and objects, IAM role and policy, and the cluster OIDC provider can remain after Kubernetes cleanup. The EKS cluster also remains because this repository leaves it unchanged.",
        "amber",
    )
)
story.append(P("Source map", "H2Custom"))
story.append(
    data_table(
        ["Need", "Repository source"],
        [
            ("Product and ownership overview", "README.md"),
            ("Full deployment gates", "docs/01-prerequisites.md"),
            ("Canonical manual commands", "docs/02-runbook.md"),
            ("Traffic, bootstrap, IAM, and invariants", "docs/00-architecture.md"),
            ("Health, diagnosis, recovery, and teardown", "docs/05-operations.md"),
            ("SDK-service rollout and draining", "docs/03-deploying-services.md"),
            ("Canonical applied assets", "resources/00 through resources/06"),
        ],
        [65 * mm, 104 * mm],
    )
)
story.append(Spacer(1, 9))
story.append(P("Reference baseline", "H2Custom"))
story.append(P(f"This companion was generated from repository commit <b>{args.source_commit}</b> dated {args.source_date}. Commands and versions should be revalidated if used with a different revision."))
story.append(P("Official background: <font color='#007F86'>https://docs.restate.dev/foundations/key-concepts</font><br/>Operator project: <font color='#007F86'>https://github.com/restatedev/restate-operator</font>", "BodySmall"))
story.append(
    P(
        "<b>Source-of-truth note:</b> If this PDF and the checked-out repository disagree, please pause and use the repository revision under change control. Re-run <b>nix-shell --run ./scripts/validate.sh</b> before deployment.",
        "BodySmall",
    )
)

doc.build(story, onFirstPage=draw_cover, onLaterPages=draw_later)
print(OUTPUT)
