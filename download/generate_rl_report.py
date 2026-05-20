#!/usr/bin/env python3
"""Generate RL Feedback Loop PDF Report."""

import sys, os
PDF_SKILL_DIR = "/home/z/my-project/skills/pdf"
_scripts = os.path.join(PDF_SKILL_DIR, "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    KeepTogether, CondPageBreak, PageBreak, HRFlowable
)

# ━━ Palette ━━
PAGE_BG       = colors.HexColor('#f5f5f4')
SECTION_BG    = colors.HexColor('#f2f2f0')
CARD_BG       = colors.HexColor('#efeeec')
TABLE_STRIPE  = colors.HexColor('#f4f3f1')
HEADER_FILL   = colors.HexColor('#716952')
COVER_BLOCK   = colors.HexColor('#827a62')
BORDER        = colors.HexColor('#d9d3c3')
ICON          = colors.HexColor('#a59156')
ACCENT        = colors.HexColor('#1c7796')
ACCENT_2      = colors.HexColor('#45c445')
TEXT_PRIMARY   = colors.HexColor('#23221f')
TEXT_MUTED     = colors.HexColor('#8c8a82')
SEM_SUCCESS   = colors.HexColor('#3c7d52')
SEM_WARNING   = colors.HexColor('#8e7542')
SEM_ERROR     = colors.HexColor('#904841')
SEM_INFO      = colors.HexColor('#47739f')

# ━━ Fonts ━━
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('Carlito', '/usr/share/fonts/truetype/english/Carlito-Regular.ttf'))
pdfmetrics.registerFont(TTFont('Carlito-Bold', '/usr/share/fonts/truetype/english/Carlito-Bold.ttf'))
pdfmetrics.registerFont(TTFont('Carlito-Italic', '/usr/share/fonts/truetype/english/Carlito-Italic.ttf'))
pdfmetrics.registerFont(TTFont('LiberationSerif', '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf'))
pdfmetrics.registerFont(TTFont('LiberationSerif-Bold', '/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf'))
pdfmetrics.registerFont(TTFont('LiberationSerif-Italic', '/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf'))

# ━━ Styles ━━
styles = getSampleStyleSheet()

style_title = ParagraphStyle(
    'RlTitle', parent=styles['Title'],
    fontName='LiberationSerif-Bold', fontSize=24, leading=30,
    textColor=TEXT_PRIMARY, alignment=TA_CENTER, spaceAfter=6
)
style_subtitle = ParagraphStyle(
    'RlSubtitle', parent=styles['Normal'],
    fontName='Carlito', fontSize=12, leading=16,
    textColor=TEXT_MUTED, alignment=TA_CENTER, spaceAfter=20
)
style_h1 = ParagraphStyle(
    'RlH1', parent=styles['Heading1'],
    fontName='LiberationSerif-Bold', fontSize=18, leading=22,
    textColor=ACCENT, spaceBefore=20, spaceAfter=10
)
style_h2 = ParagraphStyle(
    'RlH2', parent=styles['Heading2'],
    fontName='LiberationSerif-Bold', fontSize=14, leading=18,
    textColor=HEADER_FILL, spaceBefore=14, spaceAfter=8
)
style_h3 = ParagraphStyle(
    'RlH3', parent=styles['Heading3'],
    fontName='Carlito-Bold', fontSize=12, leading=16,
    textColor=TEXT_PRIMARY, spaceBefore=10, spaceAfter=6
)
style_body = ParagraphStyle(
    'RlBody', parent=styles['Normal'],
    fontName='Carlito', fontSize=10, leading=14,
    textColor=TEXT_PRIMARY, alignment=TA_JUSTIFY, spaceAfter=6
)
style_body_muted = ParagraphStyle(
    'RlBodyMuted', parent=style_body,
    textColor=TEXT_MUTED, fontSize=9
)
style_callout = ParagraphStyle(
    'RlCallout', parent=style_body,
    fontName='Carlito-Italic', fontSize=10, leading=14,
    textColor=SEM_WARNING, leftIndent=20, spaceAfter=8
)
style_critical = ParagraphStyle(
    'RlCritical', parent=style_body,
    fontName='Carlito-Bold', fontSize=10, leading=14,
    textColor=SEM_ERROR
)
style_code = ParagraphStyle(
    'RlCode', parent=style_body,
    fontName='Carlito', fontSize=8, leading=11,
    textColor=TEXT_PRIMARY, backColor=CARD_BG,
    leftIndent=12, rightIndent=12, spaceBefore=4, spaceAfter=4,
    borderPadding=4
)

# ━━ Helper ━━
def make_table(headers, rows, col_widths=None):
    """Create a styled table."""
    avail_w = A4[0] - 2*inch
    if col_widths is None:
        n = len(headers)
        col_widths = [avail_w / n] * n

    data = [headers] + rows
    data = [[Paragraph(str(c), style_body) for c in row] for row in data]
    data[0] = [Paragraph(str(c), ParagraphStyle('TH', parent=style_body, fontName='Carlito-Bold', textColor=colors.white)) for c in headers]

    t = Table(data, colWidths=col_widths, hAlign='CENTER')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_FILL),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, TABLE_STRIPE]),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    return t


def sev_color(s):
    return {
        'critical': SEM_ERROR,
        'high': SEM_WARNING,
        'medium': SEM_INFO,
        'low': SEM_SUCCESS,
    }.get(s.lower(), TEXT_MUTED)


# ━━ Document ━━
output_path = '/home/z/my-project/download/RL_Feedback_Loop_Report.pdf'
doc = SimpleDocTemplate(
    output_path,
    pagesize=A4,
    leftMargin=inch, rightMargin=inch,
    topMargin=0.8*inch, bottomMargin=0.8*inch,
    title='RL Feedback Loop - Stress-Test-Gated Knowledge Report',
    author='Z.ai',
    creator='Z.ai Agentic Automation',
)

story = []

# ━━ Title ━━
story.append(Spacer(1, 30))
story.append(Paragraph('RL Feedback Loop', style_title))
story.append(Paragraph('Stress-Test-Gated Knowledge Report', ParagraphStyle(
    'SubTitle2', parent=style_subtitle, fontSize=16, leading=20, textColor=ACCENT
)))
story.append(Spacer(1, 6))
story.append(Paragraph('Polyglot Microservices Platform | Gap Analysis + Reinforcement Learning', style_subtitle))
story.append(Spacer(1, 6))
story.append(HRFlowable(width='80%', thickness=2, color=ACCENT, spaceAfter=20))

# ━━ Executive Summary ━━
story.append(Paragraph('1. Executive Summary', style_h1))
story.append(Paragraph(
    'This report presents the findings from a comprehensive Reinforcement Learning (RL) feedback loop '
    'analysis conducted on the polyglot microservices platform. The analysis compares our own 13-violation '
    'audit (V-1 through V-13) against 18 findings identified by an external AI reviewer (Gemini Code Assist) '
    'across 5 pull requests. The RL system is designed to ingest findings, verify fixes through a 3-tier '
    'stress-testing pipeline, and only promote battle-tested solutions to the permanent knowledge base. '
    'This ensures that future code reviews benefit from hard-won lessons without incorporating unverified '
    'or theoretically-correct-but-untested fixes.',
    style_body
))
story.append(Paragraph(
    'The gap analysis reveals a significant blind spot: 16 out of 18 external findings were missed by our '
    'own audit. The dominant failure modes are category blind spots (9 gaps, 56%) where entire categories '
    'of issues were not reviewed, and pattern recognition failures (7 gaps, 44%) where the issue pattern '
    'was not recognized even within reviewed files. This report quantifies these gaps, explains the root '
    'causes, and proposes concrete improvements to the audit process that will be absorbed into the RL '
    'knowledge base once stress-tested.',
    style_body
))

# ━━ Key Metrics ━━
story.append(Paragraph('2. Key Metrics', style_h1))
metrics_data = [
    ['Total Findings Ingested', '31', '13 our + 18 external'],
    ['Our Violations (V-1 to V-13)', '13', 'Self-audit findings'],
    ['External Findings (G1 to G18)', '18', 'Gemini Code Assist'],
    ['Gaps (We Missed)', '16 / 18', '89% miss rate'],
    ['Category Blind Spots', '9', 'Infra/K8s/Security not reviewed'],
    ['Pattern Unrecognized', '7', 'Known categories, missed patterns'],
    ['TIER 1 (Static) Passed', '25', 'File exists + fix applied'],
    ['TIER 2 (Functional) Passed', '9', 'Test coverage exists'],
    ['TIER 3 (Stress) Passed', '0', 'No stress tests run yet'],
    ['Promoted to Knowledge Base', '0', 'Stress-test gate blocks promotion'],
]
story.append(make_table(
    ['Metric', 'Value', 'Notes'],
    metrics_data,
    [2.2*inch, 1.2*inch, 3.0*inch]
))
story.append(Spacer(1, 10))
story.append(Paragraph(
    '<b>Critical insight:</b> The RL knowledge base is currently empty because zero findings have passed '
    'the TIER 3 stress-test gate. This is by design. The promotion policy requires a minimum confidence '
    'of 0.95 and a completed stress test. Without this gate, the system would promote fixes that look '
    'correct in theory but may fail under load, edge cases, or specific runtime conditions. The '
    'stress-test gate ensures that only solutions validated in real-world conditions are used for future '
    'pattern matching and automated fix suggestions.',
    style_callout
))

# ━━ Gap Analysis ━━
story.append(Paragraph('3. Gap Analysis: What We Missed', style_h1))
story.append(Paragraph(
    'The gap analysis compares every external finding against our own audit results. A "gap" is defined '
    'as an external finding for which we had no overlapping finding in our own 13-violation audit. Out of '
    '18 external findings, 16 represent gaps, meaning we only caught 2 of the 18 issues that Gemini Code '
    'Assist identified (an 89% miss rate). Even for the 2 findings with partial overlap (V-2 overlaps G9, '
    'V-8 overlaps G4), our findings identified related but different issues in the same files rather than '
    'the specific problems the external reviewer caught.',
    style_body
))

story.append(Paragraph('3.1 Gap Reasons Breakdown', style_h2))
story.append(Paragraph(
    'The gaps are classified into two root causes. Category blind spots occur when an entire category '
    'of files or issues was outside our audit scope. Pattern unrecognized gaps occur when we reviewed '
    'the same file but failed to identify the specific problem pattern. Understanding this distinction '
    'is essential for improving the audit process because each root cause requires a different corrective '
    'action.',
    style_body
))
gap_reasons = [
    ['Category Blind Spot', '9', '56%', 'K8s manifests, security configs, CI/CD'],
    ['Pattern Unrecognized', '7', '44%', 'Money validation, datetime, credentials'],
]
story.append(make_table(
    ['Gap Reason', 'Count', 'Percentage', 'Examples'],
    gap_reasons,
    [1.6*inch, 0.8*inch, 0.8*inch, 3.2*inch]
))

# ━━ Category Blind Spots ━━
story.append(Paragraph('3.2 Category Blind Spots (9 gaps)', style_h2))
story.append(Paragraph(
    'Category blind spots represent the largest failure mode in our audit. These occur when entire '
    'categories of files were not included in our review scope. Our original audit focused primarily on '
    'application code (Python services, Go services, TypeScript services) and architectural compliance '
    '(hexagonal architecture, SPIFFE annotations). We did not deeply review Kubernetes infrastructure '
    'manifests, security configurations (secrets, NetworkPolicies), or CI/CD pipeline definitions. This '
    'is a critical oversight for a platform that claims to be production-ready, because infrastructure '
    'misconfigurations can be just as catastrophic as application bugs.',
    style_body
))

cat_blind = [
    ['G2', 'CRITICAL', 'kafka.yaml', 'emptyDir causes data loss in StatefulSets'],
    ['G5', 'HIGH', 'networkpolicy.yaml', 'Broad 10.0.0.0/8 CIDR violates least privilege'],
    ['G6', 'HIGH', 'app-of-apps.yaml', 'Hardcoded placeholder repoURL'],
    ['G7', 'HIGH', 'debezium.yaml', 'Recreate strategy causes downtime'],
    ['G8', 'HIGH', 'debezium.yaml', 'readOnlyRootFilesystem: false'],
    ['G10', 'MEDIUM', 'kustomization.yaml', 'envFrom only applied to gateway'],
    ['G14', 'CRITICAL', 'grafana.yaml', 'Hardcoded admin password in Secret'],
    ['G16', 'HIGH', 'app-of-apps.yaml', 'ApplicationSet path points to YAML, not kustomize dirs'],
    ['G17', 'MEDIUM', 'grafana-dashboards-config.yaml', 'Duplicated dashboard JSON'],
]
story.append(make_table(
    ['ID', 'Severity', 'File', 'Issue'],
    cat_blind,
    [0.5*inch, 0.8*inch, 1.8*inch, 3.3*inch]
))

# ━━ Pattern Unrecognized ━━
story.append(Paragraph('3.3 Pattern Unrecognized (7 gaps)', style_h2))
story.append(Paragraph(
    'Pattern unrecognized gaps are arguably more concerning than category blind spots because they '
    'represent failures within files we actually reviewed. In these cases, we examined the same code '
    'but did not recognize the specific problem pattern. For example, we flagged datetime.utcnow() '
    'deprecation (V-2) but missed datetime.fromtimestamp() without timezone (G9) in the same analytics '
    'service. We identified the hexagonal architecture violation in the catalog service (V-13) but '
    'missed the Money price conversion bug (G1) and the nanos validation error (G3) in the same service. '
    'These gaps suggest that our review process was too focused on architectural compliance at the '
    'expense of correctness and edge-case validation.',
    style_body
))

pat_unrec = [
    ['G1', 'CRITICAL', 'CatalogController.ts', 'Money price conversion: 29.99 becomes units:2999'],
    ['G3', 'CRITICAL', 'Money.ts', 'Nanos validation prevents negative values'],
    ['G9', 'HIGH', 'grpc_handler.py', 'fromtimestamp() without tz parameter'],
    ['G11', 'MEDIUM', 'aggregation_service.py', 'Docstring says nearest-rank, code uses interpolation'],
    ['G12', 'MEDIUM', 'types.proto', 'Nanos comment incorrect for negative values'],
    ['G13', 'MEDIUM', 'container.ts', 'protoPath identical in all env branches'],
    ['G15', 'HIGH', 'postgres_repo.py', 'Hardcoded DB credentials in connection string'],
]
story.append(make_table(
    ['ID', 'Severity', 'File', 'Issue'],
    pat_unrec,
    [0.5*inch, 0.8*inch, 1.8*inch, 3.3*inch]
))

# ━━ Verification Tier Status ━━
story.append(Paragraph('4. Verification Tier Status', style_h1))
story.append(Paragraph(
    'The RL feedback loop uses a 3-tier verification model to ensure that only stress-tested solutions '
    'are promoted to the knowledge base. TIER 1 (Static) checks whether the fix exists in the codebase '
    'by verifying that the target file has been modified. TIER 2 (Functional) checks whether test '
    'coverage exists for the fixed component. TIER 3 (Stress) requires load testing, chaos testing, '
    'and edge-case validation under realistic conditions. This tier is the critical gate that prevents '
    'theoretical but untested fixes from being incorporated into the learning system.',
    style_body
))

tier_data = [
    ['TIER 1 (Static)', '25 / 31', '81%', 'Fix exists in codebase'],
    ['TIER 2 (Functional)', '9 / 31', '29%', 'Test coverage exists'],
    ['TIER 3 (Stress)', '0 / 31', '0%', 'Load/chaos/edge-case validated'],
    ['Promoted to Knowledge', '0 / 31', '0%', 'Stress-test gate passed'],
]
story.append(make_table(
    ['Tier', 'Passed', 'Rate', 'Description'],
    tier_data,
    [1.4*inch, 0.9*inch, 0.7*inch, 3.4*inch]
))
story.append(Spacer(1, 10))
story.append(Paragraph(
    '<b>Why TIER 3 is empty:</b> No findings have been stress-tested yet. This is a deliberate design '
    'choice. The promotion policy requires min_tier=3, require_stress_test=True, and min_confidence=0.95. '
    'In a CI/CD environment, TIER 3 verification would be automated via integration tests, load tests '
    '(e.g., k6, Locust), chaos engineering (e.g., Litmus, Chaos Mesh), and canary deployments. The '
    'current gap means the RL knowledge base will remain empty until these tests are implemented and '
    'passing. This is preferable to promoting unverified fixes that could introduce regressions or '
    'fail under production conditions.',
    style_callout
))

# ━━ Stress-Test Gating Policy ━━
story.append(Paragraph('5. Stress-Test Gating Policy', style_h1))
story.append(Paragraph(
    'The core principle of the RL feedback loop is that only stress-tested solutions are promoted to the '
    'knowledge base. This section documents the gating policy and explains why each requirement exists. '
    'The policy is intentionally conservative because the knowledge base will be used for automated '
    'pattern matching and fix suggestions in future code reviews. A single incorrect promoted solution '
    'could cause the system to suggest harmful changes, making the policy stricter than typical CI/CD '
    'gates that only need to verify the current change.',
    style_body
))

policy_data = [
    ['min_tier', '3', 'Only stress-tested fixes are promoted'],
    ['require_stress_test', 'True', 'Must pass load, chaos, and edge-case validation'],
    ['require_no_regressions', 'True', 'No failed verification at same or higher tier'],
    ['min_confidence', '0.95', 'Minimum 95% confidence score for promotion'],
]
story.append(make_table(
    ['Parameter', 'Value', 'Rationale'],
    policy_data,
    [1.6*inch, 1.0*inch, 3.8*inch]
))

story.append(Paragraph('5.1 Why Not Promote TIER 1 or TIER 2 Solutions?', style_h2))
story.append(Paragraph(
    'It may be tempting to promote solutions that have passed TIER 1 (static verification) or TIER 2 '
    '(functional tests). However, doing so would violate the fundamental design principle of the RL '
    'system: learn only from battle-tested solutions. A TIER 1 pass only means the fix exists in the '
    'codebase, not that it works correctly. A TIER 2 pass means unit tests exist, but unit tests often '
    'test the happy path and miss edge cases, race conditions, and production-specific failure modes. '
    'Consider the G2 finding (emptyDir in Kafka StatefulSets): the fix (using volumeClaimTemplates) '
    'passes TIER 1 because the code exists, but only a stress test that actually reschedules a Kafka '
    'pod and verifies data persistence would confirm the fix works. Without TIER 3, we cannot be '
    'confident that the fix handles all real-world scenarios.',
    style_body
))

# ━━ Root Cause Analysis ━━
story.append(Paragraph('6. Root Cause Analysis: Why We Missed These Errors', style_h1))
story.append(Paragraph(
    'Understanding why our audit missed 89% of external findings is essential for improving the process. '
    'The root causes fall into three categories, each requiring a different corrective action and each '
    'feeding back into the RL knowledge base once the corrective actions are stress-tested.',
    style_body
))

story.append(Paragraph('6.1 Audit Scope Too Narrow', style_h2))
story.append(Paragraph(
    'Our original 13-violation audit was scoped primarily to application code and architectural compliance. '
    'We did not include a dedicated infrastructure review track for Kubernetes manifests, security '
    'configurations, or deployment strategies. This explains 9 of the 16 gaps (56%). The corrective action '
    'is to add a mandatory Infrastructure Review expert role to the multi-expert audit, with a specific '
    'checklist covering: (1) StatefulSet storage configuration (emptyDir vs PVC), (2) Security context '
    '(readOnlyRootFilesystem, runAsNonRoot), (3) NetworkPolicy CIDR specificity, (4) Secret management '
    '(no hardcoded credentials), (5) Deployment strategy (Recreate vs RollingUpdate with justification), '
    'and (6) Kustomize overlay completeness.',
    style_body
))

story.append(Paragraph('6.2 Insufficient Depth in Reviewed Files', style_h2))
story.append(Paragraph(
    'For the 7 pattern-unrecognized gaps, we reviewed the same files but did not go deep enough. Our '
    'review identified architectural issues (hexagonal violations, missing SPIFFE annotations) but missed '
    'correctness issues (Money conversion bug, nanos validation, datetime timezone). This suggests our '
    'review bias toward architecture over correctness. The corrective action is to add a Correctness '
    'Review expert role that specifically checks: (1) Value object validation completeness (especially '
    'negative/edge cases), (2) Date/time handling (all paths using timezone-aware objects), (3) Monetary '
    'calculation correctness (decimal precision, sign handling), (4) Credential management (no hardcoded '
    'secrets), and (5) Docstring-implementation consistency.',
    style_body
))

story.append(Paragraph('6.3 No Cross-File Pattern Detection', style_h2))
story.append(Paragraph(
    'Several of the missed issues follow patterns that span multiple files. The nanos validation error '
    '(G3 in Money.ts, G12 in types.proto) appears in both the TypeScript domain model and the Protobuf '
    'schema definition. The datetime timezone issue (V-1 through V-3, G9) appears across multiple '
    'services and in different forms (utcnow() vs fromtimestamp()). Our audit caught some instances '
    'but not all because we reviewed files individually rather than checking for pattern consistency '
    'across the entire codebase. The corrective action is to implement a cross-file pattern scanner '
    'that identifies issue patterns once found and searches for the same pattern across all services, '
    'regardless of language.',
    style_body
))

# ━━ Improvement Actions ━━
story.append(Paragraph('7. Improvement Actions for the RL System', style_h1))
story.append(Paragraph(
    'Based on the root cause analysis, the following improvement actions will be implemented and then '
    'stress-tested before being promoted to the RL knowledge base. Each action includes a measurable '
    'success criterion and the verification method that will be used at TIER 3.',
    style_body
))

actions_data = [
    ['IA-1', 'Add Infrastructure Review expert to multi-expert audit', 'Zero category blind spots in next audit', 'Re-audit with new expert, verify no gaps'],
    ['IA-2', 'Add Correctness Review expert for value objects and date/time', 'Catch all Money/datetime/credential issues', 'Regression test suite with edge cases'],
    ['IA-3', 'Build cross-file pattern scanner for issue propagation', 'Find all instances of a pattern across services', 'Run scanner, verify 100% pattern coverage'],
    ['IA-4', 'Create stress test suite for all promoted knowledge items', '100% of knowledge items pass TIER 3', 'Execute stress tests, verify all pass'],
    ['IA-5', 'Implement automated RL feedback on every PR review', 'RL system learns from every PR, not just manual audits', 'PR-triggered verification pipeline'],
]
story.append(make_table(
    ['ID', 'Action', 'Success Criterion', 'TIER 3 Verification'],
    actions_data,
    [0.5*inch, 2.2*inch, 1.8*inch, 1.9*inch]
))

# ━━ Remaining Unfixed ━━
story.append(Paragraph('8. Remaining Unfixed Findings', style_h1))
story.append(Paragraph(
    'As of this report, 3 findings from the external review remain unfixed or only partially fixed on '
    'the main branch. These represent immediate action items that must be resolved before the next '
    'phase of development begins. Each unfixed finding is documented below with the specific remediation '
    'required.',
    style_body
))

story.append(Paragraph('8.1 G16: ApplicationSet Path Misconfiguration (UNFIXED)', style_h3))
story.append(Paragraph(
    'The ArgoCD ApplicationSet in app-of-apps.yaml points to individual YAML files rather than kustomize '
    'directories. This will cause deployment failures because ArgoCD cannot perform a Kustomize build '
    'on a single YAML file. The fix requires creating kustomize directories for each service application '
    'and updating the ApplicationSet generator paths to point to these directories. This is a high-severity '
    'finding because it affects the entire GitOps deployment pipeline and will prevent any service from '
    'being deployed via ArgoCD until resolved.',
    style_body
))

story.append(Paragraph('8.2 G17: Duplicated Grafana Dashboard JSON (UNFIXED)', style_h3))
story.append(Paragraph(
    'The Grafana dashboard JSON content exists in two places: inline in the grafana-dashboards-config.yaml '
    'ConfigMap and as separate files in the grafana-dashboards/ directory. This duplication creates a '
    'maintenance burden and a risk of the files becoming out of sync. The recommended fix is to use a '
    'Kustomize configMapGenerator with a files key to build the ConfigMap from the source JSON files at '
    'build time, establishing the JSON files as the single source of truth.',
    style_body
))

story.append(Paragraph('8.3 G18: DNS Outage Chaos Experiment (PARTIALLY FIXED)', style_h3))
story.append(Paragraph(
    'The experiment_dns_outage function in chaos-experiments.sh applies an incorrect NetworkPolicy that '
    'allows DNS egress, then includes a comment acknowledging the mistake, deletes the policy, and applies '
    'the correct one. While the end result is correct, the initial wrong policy application and subsequent '
    'deletion creates confusion and increases the risk of someone copying the wrong pattern. The fix is '
    'to remove the initial incorrect policy entirely and directly apply the correct default-deny egress policy.',
    style_body
))

# ━━ Conclusion ━━
story.append(Paragraph('9. Path to Knowledge Base Population', style_h1))
story.append(Paragraph(
    'The RL feedback loop is correctly designed but currently empty because no fixes have passed the '
    'TIER 3 stress-test gate. To populate the knowledge base with battle-tested solutions, the following '
    'steps are required in order: (1) Fix the remaining 3 unfixed findings (G16, G17, G18), (2) Implement '
    'stress test suites for each service covering the identified issue patterns, (3) Execute the stress '
    'tests and record TIER 3 results for each finding, (4) Promote passing findings to the knowledge base, '
    'and (5) Validate that the knowledge base correctly identifies similar patterns in new code. This '
    'process ensures that the RL system only learns from solutions that have been verified under realistic '
    'conditions, preventing the propagation of theoretical but untested fixes that could cause harm in '
    'production environments.',
    style_body
))
story.append(Paragraph(
    'The ultimate goal is an autonomous improvement cycle where every code review, every PR comment, '
    'and every production incident feeds back into the RL system. Over time, this creates a compounding '
    'advantage: the system becomes progressively better at catching issues because it has a larger base '
    'of stress-tested knowledge to draw from. The key constraint is that only stress-tested solutions '
    'are admitted, ensuring that the knowledge base grows in quality as well as quantity.',
    style_body
))

# ━━ Build PDF ━━
doc.build(story)
print(f'PDF generated: {output_path}')

import os
size = os.path.getsize(output_path)
print(f'Size: {size} bytes')
