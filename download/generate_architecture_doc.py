#!/usr/bin/env python3
"""
Comprehensive Solution Architecture: The "Best of Both Worlds"
Professional PDF document generation via ReportLab + HTML/Playwright cover.
"""

import os
import sys
import hashlib
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, cm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    KeepTogether, CondPageBreak, HRFlowable
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

# ━━ Palette (from palette.cascade) ━━
PAGE_BG       = colors.HexColor('#f5f5f5')
SECTION_BG    = colors.HexColor('#f0efed')
CARD_BG       = colors.HexColor('#eeeeec')
TABLE_STRIPE  = colors.HexColor('#f3f2f0')
HEADER_FILL   = colors.HexColor('#534b34')
COVER_BLOCK   = colors.HexColor('#6d644a')
BORDER        = colors.HexColor('#c5c2b8')
ICON          = colors.HexColor('#ad9243')
ACCENT        = colors.HexColor('#30829e')
ACCENT_2      = colors.HexColor('#4fb84f')
TEXT_PRIMARY   = colors.HexColor('#21201e')
TEXT_MUTED     = colors.HexColor('#8f8d86')
SEM_SUCCESS   = colors.HexColor('#4a7c5b')
SEM_WARNING   = colors.HexColor('#ae8c48')
SEM_ERROR     = colors.HexColor('#9f524b')
SEM_INFO      = colors.HexColor('#446689')

# ━━ Font Registration ━━
# Using Carlito (Calibri-compatible) for body + Liberation Serif for headings
pdfmetrics.registerFont(TTFont('Carlito', '/usr/share/fonts/truetype/english/Carlito-Regular.ttf'))
pdfmetrics.registerFont(TTFont('Carlito-Bold', '/usr/share/fonts/truetype/english/Carlito-Bold.ttf'))
pdfmetrics.registerFont(TTFont('LibSerif', '/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf'))
pdfmetrics.registerFont(TTFont('LibSerif-Bold', '/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuSans', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'))
registerFontFamily('Carlito', normal='Carlito', bold='Carlito-Bold')
registerFontFamily('LibSerif', normal='LibSerif', bold='LibSerif-Bold')
registerFontFamily('DejaVuSans', normal='DejaVuSans', bold='DejaVuSans')

# ━━ Page Geometry ━━
PAGE_W, PAGE_H = A4
LEFT_MARGIN = 1.0 * inch
RIGHT_MARGIN = 1.0 * inch
TOP_MARGIN = 0.85 * inch
BOTTOM_MARGIN = 0.85 * inch
CONTENT_W = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN

# ━━ TocDocTemplate ━━
class TocDocTemplate(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, 'bookmark_name'):
            level = getattr(flowable, 'bookmark_level', 0)
            text = getattr(flowable, 'bookmark_text', '')
            key = getattr(flowable, 'bookmark_key', '')
            self.notify('TOCEntry', (level, text, self.page, key))

# ━━ Styles ━━
styles = getSampleStyleSheet()

toc_h1 = ParagraphStyle(
    'TOCH1', fontName='LibSerif', fontSize=13, leading=22,
    leftIndent=20, spaceBefore=6, spaceAfter=2, textColor=TEXT_PRIMARY
)
toc_h2 = ParagraphStyle(
    'TOCH2', fontName='Carlito', fontSize=11, leading=18,
    leftIndent=40, spaceBefore=2, spaceAfter=2, textColor=TEXT_MUTED
)

h1_style = ParagraphStyle(
    'H1Custom', fontName='LibSerif', fontSize=20, leading=28,
    spaceBefore=18, spaceAfter=10, textColor=ACCENT, alignment=TA_LEFT
)
h2_style = ParagraphStyle(
    'H2Custom', fontName='LibSerif', fontSize=15, leading=22,
    spaceBefore=14, spaceAfter=8, textColor=HEADER_FILL, alignment=TA_LEFT
)
h3_style = ParagraphStyle(
    'H3Custom', fontName='LibSerif', fontSize=12.5, leading=18,
    spaceBefore=10, spaceAfter=6, textColor=COVER_BLOCK, alignment=TA_LEFT
)
body_style = ParagraphStyle(
    'BodyCustom', fontName='Carlito', fontSize=10.5, leading=17,
    spaceBefore=0, spaceAfter=6, textColor=TEXT_PRIMARY, alignment=TA_JUSTIFY
)
body_left = ParagraphStyle(
    'BodyLeft', fontName='Carlito', fontSize=10.5, leading=17,
    spaceBefore=0, spaceAfter=6, textColor=TEXT_PRIMARY, alignment=TA_LEFT
)
bullet_style = ParagraphStyle(
    'BulletCustom', fontName='Carlito', fontSize=10.5, leading=17,
    spaceBefore=2, spaceAfter=4, textColor=TEXT_PRIMARY, alignment=TA_LEFT,
    leftIndent=24, bulletIndent=12
)
callout_style = ParagraphStyle(
    'CalloutCustom', fontName='Carlito', fontSize=10.5, leading=17,
    spaceBefore=4, spaceAfter=4, textColor=SEM_INFO, alignment=TA_LEFT,
    leftIndent=20, borderPadding=6
)
caption_style = ParagraphStyle(
    'CaptionCustom', fontName='Carlito', fontSize=9, leading=14,
    spaceBefore=3, spaceAfter=6, textColor=TEXT_MUTED, alignment=TA_CENTER
)
tbl_header_style = ParagraphStyle(
    'TblHeader', fontName='Carlito', fontSize=10, leading=14,
    textColor=colors.white, alignment=TA_CENTER
)
tbl_cell_style = ParagraphStyle(
    'TblCell', fontName='Carlito', fontSize=9.5, leading=14,
    textColor=TEXT_PRIMARY, alignment=TA_LEFT
)
tbl_cell_center = ParagraphStyle(
    'TblCellCenter', fontName='Carlito', fontSize=9.5, leading=14,
    textColor=TEXT_PRIMARY, alignment=TA_CENTER
)

# ━━ Helper Functions ━━
H1_ORPHAN_THRESHOLD = (PAGE_H - TOP_MARGIN - BOTTOM_MARGIN) * 0.15

def add_heading(text, style, level=0):
    key = 'h_%s' % hashlib.md5(text.encode()).hexdigest()[:8]
    p = Paragraph('<a name="%s"/>%s' % (key, text), style)
    p.bookmark_name = text
    p.bookmark_level = level
    p.bookmark_text = text
    p.bookmark_key = key
    return p

def add_major_section(text):
    return [
        CondPageBreak(H1_ORPHAN_THRESHOLD),
        add_heading(text, h1_style, level=0),
    ]

def add_sub_section(text):
    return [add_heading(text, h2_style, level=1)]

def add_sub_sub_section(text):
    return [add_heading(text, h3_style, level=2)]

def make_table(data, col_ratios, caption_text=None):
    col_widths = [r * CONTENT_W for r in col_ratios]
    # Ensure sum fits
    total = sum(col_widths)
    if total > CONTENT_W:
        scale = CONTENT_W / total
        col_widths = [w * scale for w in col_widths]
    tbl = Table(data, colWidths=col_widths, hAlign='CENTER')
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), ACCENT),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, TABLE_STRIPE]),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements = [Spacer(1, 18), tbl]
    if caption_text:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(caption_text, caption_style))
    elements.append(Spacer(1, 18))
    return elements

def callout_box(text):
    """Create a visually distinct callout paragraph with left accent border."""
    return Paragraph(
        '<font color="#30829e"><b>|</b></font>  ' + text,
        callout_style
    )

def body(text):
    return Paragraph(text, body_style)

def bullet(text):
    return Paragraph('<bullet>&bull;</bullet> ' + text, bullet_style)

# ━━ Page Number Footer ━━
def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont('Carlito', 9)
    canvas.setFillColor(TEXT_MUTED)
    page_num = canvas.getPageNumber()
    if page_num > 1:
        canvas.drawCentredString(PAGE_W / 2, 0.5 * inch, str(page_num))
    # Header line
    if page_num > 1:
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(LEFT_MARGIN, PAGE_H - 0.6 * inch, PAGE_W - RIGHT_MARGIN, PAGE_H - 0.6 * inch)
    canvas.restoreState()

# ━━ Build Document ━━
OUTPUT_DIR = '/home/z/my-project/download'
BODY_PDF = os.path.join(OUTPUT_DIR, 'arch_body.pdf')

doc = TocDocTemplate(
    BODY_PDF, pagesize=A4,
    leftMargin=LEFT_MARGIN, rightMargin=RIGHT_MARGIN,
    topMargin=TOP_MARGIN, bottomMargin=BOTTOM_MARGIN
)

story = []

# ━━ Table of Contents ━━
story.append(Paragraph('<b>Table of Contents</b>', ParagraphStyle(
    'TOCTitle', fontName='LibSerif', fontSize=22, leading=30,
    spaceBefore=20, spaceAfter=16, textColor=ACCENT, alignment=TA_LEFT
)))
story.append(Spacer(1, 8))
toc = TableOfContents()
toc.levelStyles = [toc_h1, toc_h2]
story.append(toc)
story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════
# SECTION 1: Goal & Strategic Vision
# ══════════════════════════════════════════════════════════════════════
story.extend(add_major_section('<b>1. Goal &amp; Strategic Vision</b>'))

story.append(body(
    'The core mandate is to design, implement, and maintain a distributed software ecosystem that achieves '
    'the "best of both worlds." We will pair absolute architectural freedom\u2014the ability to use any programming '
    'language, framework, or cloud provider seamlessly\u2014with mathematically rigorous, automated verification '
    'systems designed to prevent, detect, and instantly remediate defects. This is not merely an engineering '
    'endeavor; it is a strategic business initiative designed to safeguard the company\'s operational continuity '
    'and financial agility. The architecture must evolve with the speed of the market while maintaining the '
    'stability required for mission-critical operations, ensuring that technology remains a strategic asset '
    'rather than a strategic liability.'
))

story.extend(add_sub_section('<b>The Business Case: Neutralizing "Technical Extortion"</b>'))

story.append(body(
    'In the modern cloud landscape, relying heavily on proprietary managed services (e.g., AWS DynamoDB, '
    'GCP Spanner, Azure CosmosDB) creates an exceptionally high switching cost. Cloud providers leverage '
    'this "data gravity," operational inertia, and code lock-in to enact steep, non-negotiable price hikes '
    'or deprecate critical services without warning\u2014a scenario often referred to as technical extortion. '
    'When the database, message broker, and edge routing are all inextricably tied to one vendor\'s proprietary '
    'SDKs, the enterprise loses all negotiating power. The cost of migration becomes so prohibitive that the '
    'organization is effectively held hostage, forced to accept whatever pricing or service changes the vendor '
    'imposes, regardless of their impact on the bottom line.'
))

story.append(body(
    'By transforming our infrastructure into a strictly standardized, containerized utility, we grant executive '
    'leadership ultimate negotiation leverage. If a cloud provider increases egress fees by 20% or degrades '
    'service quality, this architecture allows the business to credibly threaten\u2014and execute\u2014a complete '
    'migration to a competitor in a matter of weeks, not years. This is not a theoretical advantage; it is a '
    'direct financial safeguard. The ability to migrate rapidly transforms the vendor relationship from a '
    'dependency into a competitive bidding process, where providers must continuously earn the business through '
    'competitive pricing and superior service quality rather than relying on lock-in as a retention mechanism.'
))

story.append(body(
    'Furthermore, it future-proofs the organization against aging technology stacks. The half-life of software '
    'frameworks is shrinking rapidly. As new, more efficient languages or runtimes emerge (e.g., the shift from '
    'Node.js to Rust for memory-safe concurrency), they can be integrated surgically without rewriting the entire '
    'platform. The system evolves iteratively, component by component, entirely avoiding the massive capital '
    'expenditure of "Version 2.0" platform rewrites. This incremental evolution model ensures that the '
    'organization never faces the painful choice between maintaining an increasingly obsolete codebase and '
    'undertaking a risky, multi-year ground-up rebuild that disrupts ongoing operations.'
))

story.extend(add_sub_section('<b>Stakeholders</b>'))
story.append(body(
    'Executive Sponsors, VP of Engineering, Lead Architects, QA Leads, FinOps (Cloud Cost Management), '
    'Security &amp; Compliance Officers. These stakeholders represent the cross-functional leadership necessary '
    'to ensure that the architecture is not only technically sound but also aligned with business objectives, '
    'financial constraints, regulatory requirements, and operational realities. Their ongoing engagement is '
    'critical throughout every phase of implementation to ensure accountability and strategic coherence.'
))

story.extend(add_sub_section('<b>Success Criteria</b>'))

# Success Criteria Table
sc_data = [
    [Paragraph('<b>Criterion</b>', tbl_header_style),
     Paragraph('<b>Target</b>', tbl_header_style),
     Paragraph('<b>Measurement</b>', tbl_header_style)],
    [Paragraph('Language Agility', tbl_cell_style),
     Paragraph('Swap core microservice in one two-week sprint', tbl_cell_style),
     Paragraph('Zero consumer contract changes, zero dropped requests during deployment', tbl_cell_style)],
    [Paragraph('Defect Eradication', tbl_cell_style),
     Paragraph('95% reduction in cross-service integration and serialization errors', tbl_cell_style),
     Paragraph('Pre-commit boundary validation via Pact contract testing', tbl_cell_style)],
    [Paragraph('Cloud Portability', tbl_cell_style),
     Paragraph('Full infrastructure spin-up in alternative environment', tbl_cell_style),
     Paragraph('Cutover in &lt; 4 hours, zero dropped user sessions, absolute data consistency', tbl_cell_style)],
]
story.extend(make_table(sc_data, [0.20, 0.40, 0.40], 'Table 1: Success Criteria Matrix'))

# ══════════════════════════════════════════════════════════════════════
# SECTION 2: Key Functional and Nonfunctional Requirements
# ══════════════════════════════════════════════════════════════════════
story.extend(add_major_section('<b>2. Key Functional and Nonfunctional Requirements</b>'))

story.append(body(
    'To realize this vision, the system must adhere to a strict set of foundational rules. These requirements '
    'act as the architectural constitution; any deviation during implementation compromises the goal of absolute '
    'neutrality and resilience. They form the non-negotiable guardrails within which every design decision, '
    'technology selection, and implementation detail must operate. Adherence to these requirements is not optional '
    'and must be verified through automated compliance checks at every stage of the software delivery lifecycle.'
))

story.extend(add_sub_section('<b>2.1 Functional Requirements (FRs)</b>'))

story.extend(add_sub_sub_section('<b>FR-1: Pluggable Architecture via Anti-Corruption Layers (ACL)</b>'))
story.append(body(
    'All system capabilities must be exposed via standardized interfaces. Legacy systems or external SaaS APIs '
    '(which are outside our control) are notoriously volatile and poorly documented. They must be wrapped in an '
    'ACL so the core domain logic remains untainted by external structural changes. The Anti-Corruption Layer '
    'serves as a protective boundary that translates, validates, and sanitizes all data crossing into or out of '
    'the core domain, ensuring that the business logic never depends on the shape, format, or semantics of '
    'external systems. This isolation is critical because external APIs change without notice, often in ways that '
    'would cascade through tightly-coupled systems and cause unpredictable failures across multiple services.'
))
story.append(callout_box(
    '<b>Concrete Example:</b> When intercepting a deeply nested, poorly typed Salesforce JSON payload, the ACL '
    'sidecar instantly intercepts the request, validates it against a known schema, discards irrelevant data, and '
    'translates it into a clean, strictly-typed internal Protobuf definition before it ever touches our core '
    'microservices. If Salesforce changes its API version next month, only the ACL mapping updates; the core '
    'system is entirely blind to the change, preventing cascading failures.'
))

story.extend(add_sub_sub_section('<b>FR-2: Automated Recovery &amp; Resilience Patterns</b>'))
story.append(body(
    'In a distributed system, partial failure is not a possibility; it is a mathematical inevitability. Networks '
    'drop packets, disks fail, and downstream APIs experience latency spikes. The system must autonomously detect '
    'failures and revert to a stable state without human intervention. Each resilience pattern addresses a specific '
    'failure mode, and together they form a comprehensive defense-in-depth strategy that ensures the system '
    'degrades gracefully under stress rather than collapsing catastrophically.'
))

story.append(bullet(
    '<b>Circuit Breakers:</b> If a downstream payment API times out or returns HTTP 500s consecutively, the '
    'circuit breaker "trips." This prevents our servers from exhausting connection threads waiting for a response '
    'that will never arrive. The system instantly returns a cached, default, or localized error response, '
    'protecting the rest of the ecosystem from traffic jams and resource exhaustion.'
))
story.append(bullet(
    '<b>Bulkheads:</b> Resource exhaustion must be mathematically isolated so one failing service doesn\'t crash '
    'the entire underlying node. We will enforce strict CPU and Memory quotas at the pod level (e.g., ensuring a '
    'memory leak in an asynchronous image processing worker cannot starve the critical authentication service '
    'running on the same cluster). Each service operates within rigidly defined resource boundaries that prevent '
    'any single component from monopolizing shared infrastructure.'
))
story.append(bullet(
    '<b>Idempotency &amp; Retry Jitter:</b> Every mutating API endpoint (POST, PUT, DELETE) must utilize '
    'idempotency keys. If a client drops their network connection on a train and retries a "Charge Credit Card" '
    'request three times, the system mathematically guarantees the transaction only processes exactly once. '
    'Furthermore, automated retries must use exponential backoff with jitter to prevent "thundering herd" scenarios '
    'where thousands of clients simultaneously retry a failed request, accidentally DDOSing the recovered server.'
))

story.extend(add_sub_sub_section('<b>FR-3: Unified Agnostic Gateway &amp; Strict Service mTLS</b>'))
story.append(body(
    'A single, highly optimized routing layer must handle authentication (JWT validation, OAuth token exchange), '
    'distributed rate limiting, and request forwarding, acting as the foundation for a Zero Trust network '
    'architecture. Internally, this is reinforced by enforcing mutual TLS (mTLS) across all service-to-service '
    'communications, ensuring that even if the perimeter is breached, lateral network traversal is '
    'cryptographically blocked. Every request, whether external from the internet or internal between microservices, '
    'must be authenticated and authorized at this edge boundary. This prevents the dangerous anti-pattern of '
    'duplicating complex security logic across 50 different polyglot microservices. By centralizing edge logic '
    'into one auditable bottleneck, we ensure security patches (e.g., updating a cipher suite) happen in one place, '
    'instantly protecting the entire ecosystem.'
))

story.extend(add_sub_section('<b>2.2 Nonfunctional Requirements (NFRs)</b>'))

story.extend(add_sub_sub_section('<b>NFR-1: Absolute Technology Neutrality</b>'))
story.append(body(
    'There is a strict, zero-tolerance prohibition on the usage of proprietary cloud-specific SDKs or managed '
    'services that manipulate standard open protocols. This principle is foundational to every architectural '
    'decision and must be enforced through code review, automated linting, and dependency scanning. Any deviation '
    'from this principle, however small or seemingly convenient, creates a coupling point that undermines the '
    'entire portability strategy. The cost of short-term convenience is long-term vendor dependency, and the '
    'organization must resist the temptation to use proprietary features that offer marginal productivity gains '
    'at the expense of strategic flexibility.'
))

nf_data = [
    [Paragraph('<b>Category</b>', tbl_header_style),
     Paragraph('<b>Use (Agnostic Standard)</b>', tbl_header_style),
     Paragraph('<b>Avoid (Proprietary Lock-in)</b>', tbl_header_style)],
    [Paragraph('Database', tbl_cell_style),
     Paragraph('Standard PostgreSQL drivers and ANSI SQL syntax', tbl_cell_style),
     Paragraph('AWS Aurora-specific features or DynamoDB query language', tbl_cell_style)],
    [Paragraph('Event Streaming', tbl_cell_style),
     Paragraph('Apache Kafka or NATS', tbl_cell_style),
     Paragraph('AWS SQS/SNS, Azure Service Bus, GCP Pub/Sub', tbl_cell_style)],
    [Paragraph('Container Orchestration', tbl_cell_style),
     Paragraph('Vanilla Kubernetes API primitives', tbl_cell_style),
     Paragraph('AWS App Mesh, Azure Service Fabric, Google Autopilot', tbl_cell_style)],
    [Paragraph('Object Storage', tbl_cell_style),
     Paragraph('S3-compatible APIs (MinIO, Rclone)', tbl_cell_style),
     Paragraph('Provider-specific storage SDKs with proprietary extensions', tbl_cell_style)],
]
story.extend(make_table(nf_data, [0.18, 0.41, 0.41], 'Table 2: Technology Neutrality Standards'))

story.extend(add_sub_sub_section('<b>NFR-2: Reliability &amp; Bug Prevention</b>'))
story.append(body(
    'Target an aggressive 99.99% availability SLO (allowing for less than 53 minutes of downtime per year). '
    'This requires the strict enforcement of type safety, boundary validation, and contract adherence at all '
    'system boundaries before code is ever merged into the main branch. "Testing in production" is strictly '
    'prohibited. Every deployment must be preceded by comprehensive automated verification that proves the '
    'system meets its reliability targets under realistic load conditions. The cost of achieving this level of '
    'reliability is paid in engineering discipline and automated tooling, not in post-incident firefighting and '
    'emergency patches that disrupt operations and erode customer trust.'
))

story.extend(add_sub_sub_section('<b>NFR-3: Observability &amp; Telemetry</b>'))
story.append(body(
    '100% distributed tracing coverage across all components. We adhere strictly to W3C Trace Context standards, '
    'ensuring a single user request can be tracked across a Node.js API gateway, a Python Machine Learning model, '
    'and a Rust database writer simultaneously, providing a unified waterfall chart of latency regardless of the '
    'underlying language. This end-to-end traceability is essential for diagnosing performance regressions, '
    'identifying bottlenecks in cross-service workflows, and providing evidence-based capacity planning. Without '
    'complete tracing coverage, the organization operates in a state of partial blindness, unable to correlate '
    'symptoms across service boundaries or understand the true user experience.'
))

# Implementation timeline table for Section 2
tl_data = [
    [Paragraph('<b>Phase</b>', tbl_header_style),
     Paragraph('<b>Timeline</b>', tbl_header_style),
     Paragraph('<b>Stakeholders</b>', tbl_header_style),
     Paragraph('<b>Success Criteria</b>', tbl_header_style)],
    [Paragraph('Discovery, Definition, and Tooling Selection', tbl_cell_style),
     Paragraph('Weeks 1-3', tbl_cell_center),
     Paragraph('Product Managers, Business Analysts, System Architects, Security Leads', tbl_cell_style),
     Paragraph('Executive sign-off on agnostic API schema repository, standardized IaC repository, comprehensive NFR matrix', tbl_cell_style)],
]
story.extend(make_table(tl_data, [0.22, 0.12, 0.30, 0.36], 'Table 3: Phase 1 Implementation Timeline'))

# ══════════════════════════════════════════════════════════════════════
# SECTION 3: Architectural and Integration Strategy
# ══════════════════════════════════════════════════════════════════════
story.extend(add_major_section('<b>3. Architectural and Integration Strategy</b>'))

story.append(body(
    'To achieve true neutrality, we must ruthlessly decouple the business logic from the delivery mechanism '
    '(HTTP/gRPC) and the persistence layer (Databases). We cannot allow framework-specific boilerplate to '
    'infect the core algorithms that generate business value. The architectural strategy is built on three '
    'foundational pillars: Hexagonal Isolation for domain purity, Agnostic Contracts for type-safe communication, '
    'and Event-Driven Decoupling for asynchronous resilience. Together, these pillars ensure that every component '
    'of the system can be modified, replaced, or migrated independently without causing cascading changes across '
    'the ecosystem.'
))

story.extend(add_sub_section('<b>3.1 Hexagonal Isolation (Ports and Adapters)</b>'))
story.append(body(
    'The core domain of every service (whether written in Go, Rust, Java, or Python) will have absolutely zero '
    'knowledge of how it is being accessed from the internet, or where it is storing its state. It will communicate '
    'exclusively through abstract "Ports" (interfaces). "Adapters" will handle the translation to the outside '
    'world. This architectural pattern, also known as Hexagonal Architecture or the Ports and Adapters pattern, '
    'creates a hard boundary between the business logic and all external concerns, ensuring that the domain model '
    'remains pure, testable, and completely independent of infrastructure decisions.'
))
story.append(callout_box(
    '<b>Strategic Benefit:</b> If the business mandates a swap from a PostgreSQL relational database to a MongoDB '
    'document store due to shifting data requirements, the engineering team only writes a new MongoDbAdapter. The '
    'core domain logic\u2014where the complex business rules, pricing algorithms, and validation constraints live\u2014'
    'remains completely untouched, unaware of the database shift, and requires zero regression testing.'
))

story.extend(add_sub_section('<b>3.2 Agnostic Contracts as the Single Source of Truth</b>'))
story.append(body(
    'Microservices will never share databases (the "Shared Database Integration" anti-pattern is explicitly banned). '
    'They will communicate exclusively via strongly-typed, version-controlled contracts. This ensures that each '
    'service owns its data and exposes it only through well-defined APIs, preventing the tight coupling that occurs '
    'when multiple services read from and write to the same database tables. The contract-first approach guarantees '
    'that any change to a service\'s interface is explicitly versioned and communicated, allowing consumers to adapt '
    'at their own pace without unexpected breakage.'
))

contract_data = [
    [Paragraph('<b>Communication Type</b>', tbl_header_style),
     Paragraph('<b>Protocol</b>', tbl_header_style),
     Paragraph('<b>Use Case</b>', tbl_header_style),
     Paragraph('<b>Key Benefit</b>', tbl_header_style)],
    [Paragraph('Internal Cross-Service', tbl_cell_style),
     Paragraph('gRPC (Protocol Buffers)', tbl_cell_center),
     Paragraph('Highly compressed, low-latency calls between microservices', tbl_cell_style),
     Paragraph('Mathematical type-safety across languages', tbl_cell_style)],
    [Paragraph('External / Third-Party', tbl_cell_style),
     Paragraph('OpenAPI 3.1 (JSON/REST)', tbl_cell_center),
     Paragraph('Third-party integrations and Frontend UI consumption', tbl_cell_style),
     Paragraph('Broad compatibility, human-readable contracts', tbl_cell_style)],
]
story.extend(make_table(contract_data, [0.20, 0.20, 0.30, 0.30], 'Table 4: Communication Protocol Standards'))

story.extend(add_sub_section('<b>3.3 Automated Boilerplate Generation</b>'))
story.append(body(
    'Because different programming languages parse data differently, the integration layer is where 80% of '
    'serialization bugs and API mismatches breed. By defining infrastructure and API schemas first in a central '
    'Schema Registry repository (a "Schema-First Design" approach), we will use tools like Buf and OpenAPI '
    'Generator to automatically generate client/server boilerplates, DTOs (Data Transfer Objects), routing logic, '
    'and data validation middleware. This approach eliminates an entire class of human error from the development '
    'process, ensuring that the serialization and deserialization code that bridges services is always correct, '
    'always up-to-date, and always consistent with the canonical schema definition.'
))
story.append(callout_box(
    '<b>The Rule:</b> Humans write the schema; machines write the networking code. This eliminates human '
    'serialization errors entirely, drastically accelerating development speed while ensuring mathematically '
    'perfect contract adherence.'
))

story.extend(add_sub_section('<b>3.4 Event-Driven Decoupling via CloudEvents</b>'))
story.append(body(
    'Asynchronous, background processes (like sending emails, processing video, or updating search indexes) will '
    'use standard message brokers (e.g., Kafka). We will adopt the CNCF CloudEvents specification for all message '
    'envelopes, paired with a central Schema Registry (e.g., Avro or Protobuf definitions) to mathematically '
    'validate all async event payloads before they are published to the broker. Coupled with strict Dead Letter '
    'Queue (DLQ) policies, if an event fails to process after defined retries, it is safely parked for manual or '
    'automated auditing without blocking the main event stream. This ensures that the outer payload formats are '
    'universally neutral, standardizing how event headers (trace IDs, timestamps, origin sources, payload schemas) '
    'are parsed, regardless of whether the consuming microservice is written in C# or Node.js. The CloudEvents '
    'specification provides a consistent envelope format that decouples event producers from consumers, enabling '
    'independent evolution and deployment of each service.'
))

# Section 3 timeline
s3_tl_data = [
    [Paragraph('<b>Phase</b>', tbl_header_style),
     Paragraph('<b>Timeline</b>', tbl_header_style),
     Paragraph('<b>Stakeholders</b>', tbl_header_style),
     Paragraph('<b>Success Criteria</b>', tbl_header_style)],
    [Paragraph('Core Architecture, Hexagonal Templates &amp; Contract Definition', tbl_cell_style),
     Paragraph('Weeks 3-6', tbl_cell_center),
     Paragraph('Lead Developers, Enterprise Architects, Principal Engineers', tbl_cell_style),
     Paragraph('Automated generation of cross-language client stubs from central Protobuf repo on PR merge, auto-published to internal registries', tbl_cell_style)],
]
story.extend(make_table(s3_tl_data, [0.22, 0.12, 0.30, 0.36], 'Table 5: Phase 2 Implementation Timeline'))

# ══════════════════════════════════════════════════════════════════════
# SECTION 4: Quality Assurance Measures
# ══════════════════════════════════════════════════════════════════════
story.extend(add_major_section('<b>4. Quality Assurance Measures (Testing, Automation, Verification)</b>'))

story.append(body(
    'This phase represents the core of our "Robust Assurance" strategy. We will move aggressively beyond fragile, '
    'manual QA processes and standard unit testing to implement deterministic, system-wide verification. Under '
    'this doctrine, if we cannot prove the code works mathematically and contractually, it is physically blocked '
    'from deployment. The QA strategy operates on a fundamental principle: verification must be automated, '
    'comprehensive, and executed at the earliest possible point in the development lifecycle. Human judgment is '
    'reserved for test design and strategy, not for repetitive manual execution that is inherently error-prone '
    'and inconsistent.'
))

story.extend(add_sub_section('<b>4.1 Consumer-Driven Contract Testing (Pact)</b>'))
story.append(body(
    'Standard end-to-end (E2E) tests are notoriously fragile, slow, and expensive to maintain, often requiring '
    'the orchestration of 50+ microservices just to test one simple interaction. Instead, we will use Contract '
    'testing via frameworks like Pact. Consumers (e.g., the Web Frontend or a downstream service) explicitly '
    'define the exact data shape and HTTP status codes they expect from a Provider API. These expectations '
    'generate a "Contract." If a provider service team changes their API in a way that breaks a consumer\'s '
    'expected contract (e.g., renaming userId to user_id), the CI pipeline fails the Provider\'s build immediately, '
    'before the bug ever reaches a staging environment. This completely eliminates the "it worked on my machine" '
    'class of integration bugs and provides a rapid feedback loop that catches breaking changes at the source, '
    'not downstream where they are exponentially more expensive to fix.'
))

story.extend(add_sub_section('<b>4.2 Property-Based &amp; Fuzz Testing</b>'))
story.append(body(
    'Instead of writing tests with hardcoded, human-biased inputs (e.g., assert(calculateTax(100) == 10)), which '
    'only prove the code works for the number 100, we will use property-based testing frameworks (like Hypothesis '
    'in Python or proptest in Rust). The developer defines the invariants (e.g., "tax must never be negative"). '
    'The system then generates thousands of randomized, edge-case inputs\u2014including malformed UTF-8 strings, '
    'massive negative integers, floating-point anomalies, and 10MB byte payloads. This mathematically proves '
    'functions maintain their invariants and don\'t crash under unexpected memory loads or malicious payloads, '
    'bridging the gap toward formal software verification. Property-based testing is particularly effective at '
    'uncovering edge cases that human testers would never think to check, because human intuition is inherently '
    'biased toward "reasonable" inputs that don\'t stress boundary conditions.'
))

story.extend(add_sub_section('<b>4.3 Automated Mutation Testing</b>'))
story.append(body(
    'Standard code coverage metrics (e.g., achieving 85% test coverage) are often a vanity metric. They mask '
    'poorly written assertions that execute code but don\'t actually verify the logical outcome. We will introduce '
    'automated mutation testing (e.g., Stryker or PIT). The system actively sabotages the application source code '
    'during the CI run (e.g., changing if (x &gt; y) to if (x &gt;= y), mutating return variables, or swapping '
    'mathematical operators). It then runs the test suite. If the unit tests still pass despite the broken code, '
    'the test suite has failed (a "surviving mutant"). A surviving mutant proves our tests are weak and the PR is '
    'blocked until the developer writes stricter assertions. Mutation testing transforms code coverage from a '
    'quantity metric into a quality metric, ensuring that tests actually verify behavior rather than merely '
    'executing code paths.'
))

story.extend(add_sub_section('<b>4.4 Shift-Left Static Analysis &amp; Security Scanning</b>'))
story.append(body(
    'We will enforce strict linting, Abstract Syntax Tree (AST) parsing, and DevSecOps tools (CodeQL, SonarQube, '
    'Biome/Ruff) directly at the pre-commit hook level using tools like Husky or Lefthook. This process strictly '
    'adheres to the SLSA (Supply chain Levels for Software Artifacts) framework, generating automated Software '
    'Bills of Materials (SBOMs) to ensure zero third-party dependencies introduce malicious payloads. Code with '
    'critical security vulnerabilities (like potential SQL injection vectors), hardcoded secrets, or cyclomatic '
    'complexity violations cannot even be committed to the developer\'s local machine, ensuring the central '
    'repository remains pristine. By shifting these checks to the earliest possible point in the development '
    'lifecycle, we prevent defects from ever entering the codebase rather than detecting them after they have '
    'already been merged, reviewed, and potentially deployed.'
))

# QA timeline
qa_tl_data = [
    [Paragraph('<b>Phase</b>', tbl_header_style),
     Paragraph('<b>Timeline</b>', tbl_header_style),
     Paragraph('<b>Stakeholders</b>', tbl_header_style),
     Paragraph('<b>Success Criteria</b>', tbl_header_style)],
    [Paragraph('CI/CD Quality Gate Integration &amp; Fuzzing Implementation', tbl_cell_style),
     Paragraph('Weeks 5-8 (ongoing)', tbl_cell_center),
     Paragraph('QA Automation Engineers, DevSecOps, Platform Engineers', tbl_cell_style),
     Paragraph('CI auto-blocks PRs lowering mutation score, introducing CodeQL vulnerabilities, or violating Pact contracts; 90% mutation score floor over 6 months', tbl_cell_style)],
]
story.extend(make_table(qa_tl_data, [0.22, 0.12, 0.30, 0.36], 'Table 6: Phase 3 Implementation Timeline'))

# ══════════════════════════════════════════════════════════════════════
# SECTION 5: Deployment & Programmatic Cloud Portability
# ══════════════════════════════════════════════════════════════════════
story.extend(add_major_section('<b>5. Deployment &amp; Programmatic Cloud Portability</b>'))

story.append(body(
    'Deployments must be entirely abstracted away from the underlying cloud provider (AWS, GCP, Azure, Oracle, '
    'or bare-metal VPS). We will implement a Programmatic Cloud Shift mechanism. It transforms disaster recovery '
    'from a frantic manual process into a routine, automated script, guaranteeing a Recovery Point Objective (RPO) '
    'of near-zero and a Recovery Time Objective (RTO) of under 4 hours even during a total regional provider '
    'outage. It acts as a strategic fail-safe, triggered either by automated FinOps alerts (e.g., AWS compute '
    'costs exceeding a defined baseline budget) or catastrophic regional cloud outages. The key insight is that '
    'cloud portability is not merely a disaster recovery feature; it is a strategic negotiating tool that '
    'fundamentally changes the power dynamic between the enterprise and its cloud providers.'
))

story.extend(add_sub_section('<b>5.1 Universal Compute Substrate</b>'))
story.append(body(
    'All applications will be packaged via Open Container Initiative (OCI) standards (Docker/containerd) and '
    'orchestrated exclusively via vanilla Kubernetes API primitives. We will actively prohibit the use of '
    'proprietary managed features (like AWS App Mesh, Azure Service Fabric, or Google Autopilot-specific '
    'annotations) that inject cloud-specific logic into our cluster manifests, ensuring seamless, copy-paste '
    'cluster migration. By restricting ourselves to the standard Kubernetes API surface, we guarantee that any '
    'Kubernetes-compliant cluster, regardless of provider, can run our workloads without modification. This is the '
    'foundational layer of portability: if the compute substrate is provider-agnostic, every layer built on top '
    'of it inherits that portability automatically.'
))

story.extend(add_sub_section('<b>5.2 Infrastructure as Code (IaC) Abstraction</b>'))
story.append(body(
    'We will utilize declarative IaC tools like Terraform or Crossplane. By swapping the "Provider module" in '
    'the CI/CD pipeline, the system can autonomously provision identical VPCs, subnets, routing tables, load '
    'balancers, and K8s clusters on a completely new cloud provider within minutes from a cold start, guaranteeing '
    'infrastructure parity. The IaC abstraction layer is the mechanism that translates our infrastructure definitions '
    'into provider-specific API calls, ensuring that a single set of declarative configurations can be applied '
    'across any supported cloud platform. This eliminates the risk of configuration drift between environments and '
    'ensures that disaster recovery infrastructure is always identical to production infrastructure.'
))

story.extend(add_sub_section('<b>5.3 Overcoming Data Gravity (State Migration)</b>'))
story.append(body(
    'The hardest part of cloud portability is safely moving the stateful data while the application is live, '
    'without dropping user transactions. Data gravity\u2014the tendency for data to attract applications and '
    'services that depend on it\u2014is the primary force that locks organizations into specific cloud providers. '
    'Overcoming data gravity requires a carefully orchestrated replication strategy that maintains data consistency '
    'across providers while minimizing the cutover window during which the organization is exposed to risk.'
))

data_mig_data = [
    [Paragraph('<b>Data Type</b>', tbl_header_style),
     Paragraph('<b>Mechanism</b>', tbl_header_style),
     Paragraph('<b>Key Detail</b>', tbl_header_style)],
    [Paragraph('Relational Databases', tbl_cell_style),
     Paragraph('Asynchronous logical replication (PostgreSQL pglogical) or CDC streaming via Debezium', tbl_cell_style),
     Paragraph('Continuous replication pipeline with sub-second lag between primary and standby read-replica', tbl_cell_style)],
    [Paragraph('Object Storage', tbl_cell_style),
     Paragraph('S3-compatible APIs with Rclone or MinIO active-active bucket replication', tbl_cell_style),
     Paragraph('Continuous async sync of binary objects (blobs, images, documents) ensuring cryptographic parity', tbl_cell_style)],
]
story.extend(make_table(data_mig_data, [0.18, 0.40, 0.42], 'Table 7: State Migration Strategies'))

story.extend(add_sub_section('<b>5.4 Automated Traffic Shifting (The "Flip" Switch)</b>'))
story.append(body(
    'A programmatic migration pipeline will utilize Global DNS Load Balancing (e.g., Cloudflare or Route53) and '
    'BGP Anycast routing. The cutover sequence is strictly verified and fully automated. This pipeline represents '
    'the culmination of the entire portability strategy: every architectural decision, every abstraction layer, and '
    'every tooling choice leads to this moment\u2014the ability to programmatically shift the entire production '
    'workload from one cloud provider to another with zero downtime and zero data loss.'
))

flip_data = [
    [Paragraph('<b>Step</b>', tbl_header_style),
     Paragraph('<b>Action</b>', tbl_header_style),
     Paragraph('<b>Verification Gate</b>', tbl_header_style)],
    [Paragraph('1', tbl_cell_center),
     Paragraph('Cloud B fully provisioned via Terraform', tbl_cell_style),
     Paragraph('All health checks pass', tbl_cell_style)],
    [Paragraph('2', tbl_cell_center),
     Paragraph('CDC streaming confirms database replication', tbl_cell_style),
     Paragraph('Replication lag under 1 second', tbl_cell_style)],
    [Paragraph('3', tbl_cell_center),
     Paragraph('Automated checksum validations confirm data integrity', tbl_cell_style),
     Paragraph('Cryptographic parity across both databases', tbl_cell_style)],
    [Paragraph('4', tbl_cell_center),
     Paragraph('Cloud A databases locked to read-only mode; final transaction logs flushed to Cloud B', tbl_cell_style),
     Paragraph('Zero split-brain data corruption risk', tbl_cell_style)],
    [Paragraph('5', tbl_cell_center),
     Paragraph('DNS update: Canary migration routing 5% traffic to Cloud B', tbl_cell_style),
     Paragraph('OTel metrics monitor error rates for 5 minutes', tbl_cell_style)],
    [Paragraph('6', tbl_cell_center),
     Paragraph('Automated escalation: 50% then 100% traffic to Cloud B', tbl_cell_style),
     Paragraph('Stable error rates throughout escalation', tbl_cell_style)],
    [Paragraph('7', tbl_cell_center),
     Paragraph('Cloud A safely spun down after validation period', tbl_cell_style),
     Paragraph('Complete migration verified', tbl_cell_style)],
]
story.extend(make_table(flip_data, [0.08, 0.47, 0.45], 'Table 8: Automated Traffic Shifting Cutover Sequence'))

# Section 5 timeline
s5_tl_data = [
    [Paragraph('<b>Phase</b>', tbl_header_style),
     Paragraph('<b>Timeline</b>', tbl_header_style),
     Paragraph('<b>Stakeholders</b>', tbl_header_style),
     Paragraph('<b>Success Criteria</b>', tbl_header_style)],
    [Paragraph('Infrastructure as Code &amp; Portability Engineering Game Days', tbl_cell_style),
     Paragraph('Weeks 7-10', tbl_cell_center),
     Paragraph('DevOps Engineers, Release Managers, Cloud Architects, FinOps', tbl_cell_style),
     Paragraph('Chaos Engineering Game Day: zero-downtime migration of fully loaded staging from AWS to generic VPS via single GitHub Actions pipeline in &lt; 4 hours', tbl_cell_style)],
]
story.extend(make_table(s5_tl_data, [0.22, 0.12, 0.30, 0.36], 'Table 9: Phase 4 Implementation Timeline'))

# ══════════════════════════════════════════════════════════════════════
# SECTION 6: Monitoring and Feedback Loops
# ══════════════════════════════════════════════════════════════════════
story.extend(add_major_section('<b>6. Monitoring and Feedback Loops</b>'))

story.append(body(
    'To maintain strict technology neutrality, we cannot rely on proprietary APM (Application Performance '
    'Monitoring) agents\u2014like Datadog\'s proprietary language tracers or AWS X-Ray\'s SDKs. Embedding these '
    'SDKs deeply couples the application code to the vendor, requiring massive, error-prone refactoring efforts '
    'if the business decides to switch monitoring tools to save costs. The monitoring strategy must itself be '
    'portable, ensuring that the observability infrastructure can be migrated or replaced as easily as the '
    'application infrastructure. This means adopting open standards for all telemetry data and using vendor-neutral '
    'collection and routing mechanisms that decouple instrumentation from analysis.'
))

story.extend(add_sub_section('<b>6.1 OpenTelemetry (OTel) Standardization</b>'))
story.append(body(
    'We will standardize strictly on the CNCF OpenTelemetry protocol for all metrics, logs, and distributed '
    'traces (MELT). OTel provides universally agnostic instrumentation libraries for every major language. '
    'Applications send their telemetry data to an agnostic OTel Collector sidecar running in the cluster. This '
    'collector can then fan-out the data to any backend analysis tool (Prometheus, Jaeger, DataDog, New Relic, '
    'Splunk) via configuration files, without changing a single line of application source code. This architectural '
    'decision ensures that the choice of observability backend becomes a configuration decision rather than a code '
    'decision, enabling the organization to evaluate, switch, or multi-home monitoring tools without any '
    'application-level changes.'
))

story.extend(add_sub_section('<b>6.2 Distributed Tracing &amp; W3C Context</b>'))
story.append(body(
    'Every HTTP request or asynchronous Event message entering the API gateway receives a globally unique '
    'trace_id. This ID is injected into the HTTP headers or gRPC metadata and passed across all language, '
    'network, and cloud boundaries. This enables engineers to pinpoint microsecond latency issues spanning a '
    'Go API gateway, a Python ML processing service, and a Rust core logic engine on a single unified timeline '
    'graph, instantly identifying bottlenecks. The W3C Trace Context standard ensures that trace context '
    'propagation works consistently across all implementations and languages, eliminating the proprietary '
    'header formats that create vendor-specific observability silos. When a latency incident occurs at 3 AM, '
    'engineers need a single, unified trace that shows the complete request journey\u2014not separate dashboards '
    'for each language runtime that must be mentally correlated.'
))

story.extend(add_sub_section('<b>6.3 Automated Feedback Loops &amp; Unit Economics Tracking</b>'))

story.extend(add_sub_sub_section('<b>Alerting based on RED/USE Methodologies</b>'))
story.append(body(
    'Prometheus evaluates OTel metrics strictly based on the RED method (Rate, Errors, Duration) for APIs, and '
    'the USE method (Utilization, Saturation, Errors) for underlying hardware. Furthermore, by tagging OTel '
    'metrics with tenant or endpoint IDs, we can establish Unit Economics Tracking\u2014calculating the exact cloud '
    'compute cost per transaction. If a new deployment drastically increases the cost-to-serve, an automated '
    'FinOps alert is triggered. It triggers PagerDuty alerts only if defined Service Level Objectives (SLOs) are '
    'actively breached (e.g., "99th percentile latency exceeds 200ms for 5 consecutive minutes"). This drastically '
    'reduces alert fatigue caused by non-actionable CPU spikes, ensuring on-call engineers only wake up for real '
    'user impact. The combination of RED/USE alerting with unit economics creates a feedback loop that connects '
    'technical performance metrics directly to business outcomes, enabling data-driven decisions about when to '
    'optimize, when to scale, and when to migrate.'
))

story.extend(add_sub_sub_section('<b>Self-Healing via GitOps Reconciliation</b>'))
story.append(body(
    'Kubernetes natively handles process-level crashes (e.g., instantly restarting OOM-killed pods). However, '
    'for infrastructure configuration management, a GitOps controller (like ArgoCD or Flux) runs constantly inside '
    'the cluster. If manual, unauthorized changes are made to the live cluster (e.g., a developer SSHing in and '
    'changing a deployment replica count\u2014known as configuration drift), the GitOps agent instantly detects the '
    'mathematical mismatch between the live cluster state and the Git repository\'s declared state. It autonomously '
    'deletes the unauthorized change and reverts the cluster back to the safe, version-controlled state in seconds, '
    'guaranteeing production is always a perfect reflection of Git. This self-healing mechanism ensures that '
    'production configuration is immutable by default, with all changes flowing through the GitOps pipeline where '
    'they are tracked, reviewed, and auditable. The principle is clear: if it isn\'t in Git, it doesn\'t exist in '
    'production.'
))

# Monitoring timeline
s6_tl_data = [
    [Paragraph('<b>Phase</b>', tbl_header_style),
     Paragraph('<b>Timeline</b>', tbl_header_style),
     Paragraph('<b>Stakeholders</b>', tbl_header_style),
     Paragraph('<b>Success Criteria</b>', tbl_header_style)],
    [Paragraph('Observability Rollout, Dashboards &amp; Tuning', tbl_cell_style),
     Paragraph('Weeks 8-11', tbl_cell_center),
     Paragraph('Site Reliability Engineers (SRE), Support Teams, Developers', tbl_cell_style),
     Paragraph('MTTD critical bug &lt; 1 minute; full cross-service trace visibility; GitOps reverts simulated config drift within 30 seconds', tbl_cell_style)],
]
story.extend(make_table(s6_tl_data, [0.22, 0.12, 0.30, 0.36], 'Table 10: Phase 5 Implementation Timeline'))

# ━━ Build ━━
doc.multiBuild(story, onLaterPages=add_page_number, onFirstPage=add_page_number)
print(f"Body PDF generated: {BODY_PDF}")
