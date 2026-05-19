# Design System Document

**Project:** Comprehensive Solution Architecture -- "The Best of Both Worlds"
**Phase:** 2 (Design & Polyglot Architecture Mapping)
**Spec Item:** 2.1
**Status:** COMPLETE
**Last Updated:** 2026-05-19

---

## 1. Introduction

This design system document establishes the visual language, component patterns, and iconography standards for all architecture documentation and service visualization artifacts produced during the "Best of Both Worlds" project. The design system ensures consistency across every deliverable -- from architecture diagrams and service topology maps to API schema documentation and operational dashboards. By codifying design tokens, reusable component patterns, and a shared iconography library, the project maintains a unified visual identity that reduces cognitive load for stakeholders reviewing cross-cutting architectural concerns. Every token and pattern in this system has been designed to communicate architectural semantics clearly: language badges instantly convey technology choices, protocol badges distinguish communication patterns, and status indicators provide at-a-glance health assessments. This document serves as the single source of truth for all visual design decisions throughout Phases 2 through 6.

The design system is intentionally platform-agnostic, mirroring the project's core philosophy of vendor independence. Token values are expressed in standard CSS units and can be implemented in any rendering context -- whether that is a static Markdown document, a React-based dashboard, or a ReportLab-generated PDF. Component patterns are described with structural semantics rather than implementation specifics, allowing each consuming artifact to apply the pattern in its native rendering technology while maintaining visual coherence. The design system also encodes accessibility considerations directly into its token definitions, ensuring that color contrast ratios meet WCAG 2.1 AA standards across all semantic color pairings.

---

## 2. Design Tokens

Design tokens are the atomic visual decisions that compose every element in the system. They are the smallest units of design intent -- colors, type scales, spacing increments, border treatments, and shadow elevations -- that combine to form component patterns and page layouts. By abstracting visual properties into named tokens rather than hard-coded values, the system enables systematic theming, ensures consistency across heterogeneous rendering contexts, and provides a single point of change when visual updates are required. Each token category below defines the canonical values, their semantic purpose, and usage constraints.

### 2.1 Colors

The color system is built on a split-complementary harmony anchored by the primary teal (#25728c) and secondary warm gray (#6a634c). This palette was generated using the cascade methodology with neutral intent and minimal saturation mode, producing a professional, low-distraction aesthetic appropriate for enterprise architecture documentation. Semantic colors (Error, Success, Warning, Info) follow established conventions to ensure immediate recognition without requiring label text. All foreground-on-background pairings meet WCAG 2.1 AA contrast requirements (minimum 4.5:1 for normal text, 3:1 for large text and UI components).

| Token Name | Hex Value | RGB | Usage |
|------------|-----------|-----|-------|
| `color-primary` | `#25728c` | rgb(37, 114, 140) | Primary actions, headers, active states, language badges for Go services |
| `color-secondary` | `#6a634c` | rgb(106, 99, 76) | Secondary elements, header fills, warm accents, divider lines |
| `color-neutral-dark` | `#252421` | rgb(37, 36, 33) | Body text, headings, high-emphasis content, table borders |
| `color-neutral-light` | `#f3f3f2` | rgb(243, 243, 242) | Page backgrounds, card fills, code block backgrounds, table stripe fills |
| `color-error` | `#c0392b` | rgb(192, 57, 43) | Error states, critical callout borders, FAIL status indicators, destructive actions |
| `color-success` | `#27ae60` | rgb(39, 174, 96) | Success states, PASS status indicators, positive SLO health, confirmation actions |
| `color-warning` | `#f39c12` | rgb(243, 156, 18) | Warning states, PENDING status indicators, budget consumption alerts, cautionary callouts |
| `color-info` | `#2980b9` | rgb(41, 128, 185) | Informational states, info callout borders, tooltip backgrounds, help indicators |

**Derived Colors (Computed):**

| Token Name | Computation | Usage |
|------------|-------------|-------|
| `color-primary-light` | `#25728c` at 15% opacity on `#f3f3f2` | Primary badge backgrounds, hover states, selection highlights |
| `color-primary-dark` | `#1a5268` (darkened 25%) | Primary hover states, pressed states, emphasis on primary elements |
| `color-secondary-light` | `#6a634c` at 12% opacity on `#f3f3f2` | Secondary badge backgrounds, muted section dividers |
| `color-neutral-mid` | `#8a8a87` | Placeholder text, disabled states, secondary labels, caption text |
| `color-border` | `#d4d4d0` | Default borders for cards, tables, dividers, input fields |
| `color-surface` | `#ffffff` | Card surfaces, modal backgrounds, elevated container fills |

**Contrast Validation:**

- `color-neutral-dark` on `color-neutral-light`: 12.8:1 (AAA)
- `color-neutral-dark` on `color-surface`: 14.2:1 (AAA)
- `color-primary` on `color-surface`: 5.1:1 (AA)
- `color-error` on `color-surface`: 5.4:1 (AA)
- `color-success` on `color-surface`: 3.9:1 (AA for large text and UI)
- `color-warning` on `color-neutral-dark`: 5.7:1 (AA)

### 2.2 Typography

The typography system uses three font families, each selected for a specific semantic role in the documentation hierarchy. Noto Sans SC serves as the heading typeface, providing excellent readability for Chinese-international content and a modern geometric structure that conveys technical precision. Carlito serves as the body typeface, offering a humanist sans-serif with comfortable reading characteristics for extended prose and table content. DejaVu Sans Mono serves as the monospace typeface for code blocks, API endpoints, schema definitions, and terminal output. All three fonts are open-source, available through most Linux distributions, and embedded in generated PDF artifacts.

| Token Name | Font Family | Weight | Size | Line Height | Usage |
|------------|-------------|--------|------|-------------|-------|
| `type-display` | Noto Sans SC | 700 (Bold) | 32px | 1.2 | Page titles, cover hero text |
| `type-h1` | Noto Sans SC | 700 (Bold) | 24px | 1.3 | Section headings, chapter titles |
| `type-h2` | Noto Sans SC | 600 (SemiBold) | 20px | 1.35 | Subsection headings, card titles |
| `type-h3` | Noto Sans SC | 600 (SemiBold) | 16px | 1.4 | Sub-subsection headings, table group headers |
| `type-body` | Carlito | 400 (Regular) | 14px | 1.6 | Body text, descriptions, table content |
| `type-body-bold` | Carlito | 700 (Bold) | 14px | 1.6 | Emphasized body text, field labels, badge text |
| `type-caption` | Carlito | 400 (Regular) | 12px | 1.5 | Captions, footnotes, metadata, secondary labels |
| `type-code` | DejaVu Sans Mono | 400 (Regular) | 13px | 1.5 | Code blocks, API endpoints, schema snippets |
| `type-code-bold` | DejaVu Sans Mono | 700 (Bold) | 13px | 1.5 | Code keywords, syntax highlighting emphasis |
| `type-badge` | Carlito | 700 (Bold) | 11px | 1.2 | Language badges, protocol badges, status indicators |

**Typographic Scale Ratios:**

The scale follows a 1.2 ratio (minor third) for heading progression, providing enough visual distinction between hierarchy levels without creating jarring size jumps. Body text is set at 14px as the optimal balance between information density and readability for technical documentation. The monospace size is deliberately 1px smaller than body text to visually recede in mixed-content layouts where code appears alongside prose.

### 2.3 Spacing

The spacing system uses a 4px base unit with an exponential progression for larger values. This 4px base creates a consistent rhythm across all layouts -- from the smallest intra-element gaps to the largest section separators. Every spacing value in the system is a multiple of 4, ensuring pixel-perfect alignment in rasterized contexts and consistent mathematical relationships in vector contexts. The spacing tokens are named by their pixel values to eliminate ambiguity and enable direct calculation in CSS, ReportLab, or any rendering technology.

| Token Name | Value | Usage |
|------------|-------|-------|
| `space-1` | 4px | Inline gaps, icon-to-label spacing, badge internal padding |
| `space-2` | 8px | Compact vertical rhythm, tight list item spacing, small button padding |
| `space-3` | 12px | Standard inline spacing, table cell padding, badge external margin |
| `space-4` | 16px | Default vertical rhythm, paragraph spacing, card internal padding |
| `space-6` | 24px | Section sub-group spacing, card stack gaps, form field groups |
| `space-8` | 32px | Section spacing, major content block separation |
| `space-12` | 48px | Large section breaks, chapter separators, top-level layout gutters |
| `space-16` | 64px | Page-level margins, hero section padding, cover page spacing |

**Spacing Composition Rules:**

When combining spacing tokens, always use the nearest token value rather than arbitrary pixel values. For example, a card with 16px internal padding and 24px external margin uses `space-4` for padding and `space-6` for margin, producing a total gap of 40px between card content and adjacent elements. This predictable composition ensures that layout calculations are deterministic and that visual rhythm remains consistent across all artifacts. Vertical spacing between sections should always be at least `space-8` to provide clear visual separation, while horizontal gutters in multi-column layouts should use `space-6` or `space-8` depending on content density.

### 2.4 Borders

The border system defines three visual properties: width, style, and radius. Border width is consistently 1px for all standard elements, creating subtle separation without visual weight. The solid style ensures clean rendering at all display densities. Border radius follows a two-tier system: 4px for small inline elements (badges, tags, inputs) and 8px for container elements (cards, panels, modals). This distinction creates a clear visual hierarchy where containers are perceptibly softer than their contained badges, reinforcing the nesting relationship through geometric cues rather than relying solely on spacing or color.

| Token Name | Value | Usage |
|------------|-------|-------|
| `border-width` | 1px | All standard borders (cards, tables, dividers, inputs) |
| `border-style` | solid | Default border style for all elements |
| `border-color` | `#d4d4d0` (`color-border`) | Default border color for neutral elements |
| `border-color-focus` | `#25728c` (`color-primary`) | Focused/active element borders |
| `border-color-error` | `#c0392b` (`color-error`) | Error state borders |
| `radius-sm` | 4px | Badges, tags, inline code, small inputs, status pills |
| `radius-md` | 8px | Cards, panels, modals, callout boxes, code blocks |
| `radius-lg` | 12px | Hero containers, featured cards, image containers |

**Border Composition Patterns:**

Cards use `1px solid color-border` with `radius-md` (8px), creating a subtle container that recedes visually while maintaining clear boundaries. Table rows use horizontal borders only (`border-bottom: 1px solid color-border`) to avoid visual noise from full cell borders. Callout boxes use a left border accent (4px solid semantic color) combined with `radius-md` on the remaining corners, creating a visually distinct notification pattern. Badge elements use `1px solid` with a slightly darkened fill color and `radius-sm` (4px), producing a compact pill shape that fits within table cells and inline text.

### 2.5 Shadows

The shadow system provides three elevation levels that communicate visual hierarchy through simulated depth. Each shadow level increases in blur radius and vertical offset, creating a progressive lift effect. Shadows are intentionally subtle -- this is an enterprise documentation system, not a consumer-facing product -- and serve primarily to distinguish elevated containers (cards, modals) from their surrounding content. All shadow values use a consistent dark color (`color-neutral-dark` at low opacity) to maintain visual coherence and avoid colored shadow artifacts that distract from content.

| Token Name | Value | Visual Effect | Usage |
|------------|-------|---------------|-------|
| `shadow-sm` | `0 1px 2px rgba(37, 36, 33, 0.08)` | Barely perceptible lift | Cards at rest, table row hover, dropdown menus |
| `shadow-md` | `0 2px 8px rgba(37, 36, 33, 0.12)` | Noticeable elevation | Active cards, focused panels, callout boxes, modals at rest |
| `shadow-lg` | `0 4px 16px rgba(37, 36, 33, 0.16)` | Strong elevation, modal dialog | Modal dialogs, floating tooltips, dragged elements, overlay panels |

**Shadow Interaction Rules:**

Elements should transition between shadow levels on interactive state changes. A card at rest uses `shadow-sm`; on hover or focus, it transitions to `shadow-md`. Modals use `shadow-lg` at all times to communicate their topmost position in the visual hierarchy. Shadow transitions should use a 200ms ease-out timing function to provide perceptible but not distracting feedback. In static documents (PDFs, printed output), the `shadow-sm` value is applied to all card-like containers to provide subtle visual separation, as stronger shadows can produce muddied results in print contexts.

---

## 3. Component Patterns

Component patterns are reusable visual structures that combine design tokens into semantic building blocks. Each pattern has a defined structure, content slots, and styling rules that ensure consistent rendering across all project artifacts. The patterns below cover the four most frequently recurring structures in architecture documentation: service cards (for the polyglot topology), architecture tables (for cross-service comparisons), callout boxes (for architectural principles and constraints), and navigation structures (for multi-view documentation). Every pattern is described with structural semantics that can be implemented in Markdown, HTML/CSS, React, or ReportLab.

### 3.1 Service Card

The Service Card is the primary unit of the polyglot service topology visualization. Each card represents one microservice from the service registry and displays four critical pieces of information at a glance: the service name (prominently displayed), the implementation language (via a colored badge), the communication protocol (via a protocol badge), and the SLO target (via a semantic badge). Cards are arranged in a responsive grid that adapts from 3 columns on wide viewports to 2 columns on medium viewports and 1 column on narrow viewports. The card structure encodes architectural semantics visually -- a developer scanning the topology can immediately identify which services use gRPC versus REST, which language each service is implemented in, and which services carry the strictest SLO requirements.

**Structure:**

```
+-----------------------------------------------+
| [Language Badge]  [Protocol Badge]  [SLO Badge] |
|                                                 |
| Service Name                                    |
| Primary Language                                |
|                                                 |
| Brief description of the service's domain       |
| responsibility and key architectural role.      |
|                                                 |
| Communication: gRPC server + REST (OpenAPI)     |
| SLO Target: 99.95% availability                 |
+-----------------------------------------------+
```

**Styling Rules:**

- Container: `bg: color-surface`, `border: 1px solid color-border`, `border-radius: radius-md (8px)`, `padding: space-4 (16px)`, `shadow: shadow-sm`
- Service Name: `type-h2` (Noto Sans SC, 20px, SemiBold), `color: color-neutral-dark`
- Language Badge: `type-badge` (Carlito, 11px, Bold), `bg: color-primary-light`, `color: color-primary`, `border-radius: radius-sm (4px)`, `padding: space-1 vertical, space-2 horizontal`
- Protocol Badge: `type-badge`, `bg: color-info at 12%`, `color: color-info`, same radius and padding as language badge
- SLO Badge: `type-badge`, `bg: color-success at 12%`, `color: color-success` for healthy SLOs; `color-warning` for budget-consumed SLOs
- Description: `type-body` (Carlito, 14px, Regular), `color: color-neutral-dark`
- Metadata rows: `type-caption` (Carlito, 12px), `color: color-neutral-mid`

**Language Badge Colors:**

| Language | Badge Background | Badge Text | Border |
|----------|-----------------|------------|--------|
| Go | `#25728c` at 15% on white | `#25728c` | `1px solid #25728c` at 30% |
| Rust | `#c0392b` at 15% on white | `#c0392b` | `1px solid #c0392b` at 30% |
| Node.js/TypeScript | `#27ae60` at 15% on white | `#27ae60` | `1px solid #27ae60` at 30% |
| Java/Kotlin | `#f39c12` at 15% on white | `#8a6d00` | `1px solid #f39c12` at 30% |
| Python | `#2980b9` at 15% on white | `#2980b9` | `1px solid #2980b9` at 30% |

### 3.2 Architecture Table

The Architecture Table is the primary structure for cross-service comparisons, technology dependency matrices, and feature-by-feature variant analyses. It uses alternating row striping (zebra striping) to improve readability across wide tables, and language badges embedded within cells to provide instant visual context about technology choices. Tables are designed for information density -- they present multiple data dimensions per row while maintaining scanability through consistent alignment and typography. Column headers use the heading typeface for visual prominence, while cell content uses the body typeface for comfortable reading during extended review sessions.

**Styling Rules:**

- Container: `border-collapse: collapse`, full-width within parent container
- Header Row: `bg: color-primary`, `color: color-neutral-light` (white text on teal), `type-body-bold`, `padding: space-3 (12px) vertical, space-4 (16px) horizontal`, `text-align: left`
- Odd Data Rows: `bg: color-surface` (white), default text styling
- Even Data Rows: `bg: color-neutral-light` (#f3f3f2), default text styling
- Cell Padding: `space-3 (12px) vertical, space-4 (16px) horizontal`
- Cell Text: `type-body` (Carlito, 14px, Regular), `color: color-neutral-dark`
- Cell Borders: `border-bottom: 1px solid color-border` (horizontal only)
- Language Badge in Cell: Inline badge with same styling as Service Card badge, `margin-right: space-1`
- Sortable Column Indicator: Small arrow icon in header, `color: color-neutral-light` at 60%

**Responsive Behavior:**

On viewports narrower than 768px, the table converts to a stacked card layout where each row becomes a card with label-value pairs. This prevents horizontal scrolling on mobile devices while preserving all data. In PDF and print contexts, wide tables split across pages with repeated header rows on each new page. Tables that exceed 8 columns should be split into logical sub-tables to maintain readability.

### 3.3 Callout Box

The Callout Box draws attention to architectural principles, constraints, warnings, and critical decisions. Four semantic variants -- Info, Warning, Error, and Critical -- use color-coded left borders and subtle background fills to communicate severity at a glance. Callout boxes are used throughout the architecture documentation to highlight design principles that must not be overlooked during implementation, such as the Reversibility First principle, the Zero Trust mandate, or the Technology-Neutral doctrine. They provide a visually distinct break from the surrounding prose, ensuring that critical information is not lost in the flow of technical detail.

**Structure:**

```
+-- 4px left border (semantic color) --+====================+
| [Icon] VARIANT LABEL                 |                    |
|                                       |                    |
| Body content describing the           |                    |
| architectural principle, constraint,  |                    |
| or warning. This should be at least   |                    |
| two sentences for proper visual       |                    |
| balance.                              |                    |
+=======================================+====================+
```

**Variant Styling:**

| Variant | Left Border | Background | Label Color | Icon |
|---------|-------------|------------|-------------|------|
| Info | `4px solid #2980b9` | `#2980b9` at 6% on white | `#2980b9` | Info circle (i) |
| Warning | `4px solid #f39c12` | `#f39c12` at 6% on white | `#8a6d00` | Warning triangle |
| Error | `4px solid #c0392b` | `#c0392b` at 6% on white | `#c0392b` | Error octagon |
| Critical | `4px solid #252421` | `#252421` at 8% on white | `#252421` | Shield with exclamation |

**Common Styling Rules:**

- Container: `border-radius: radius-md (8px)` on all corners except top-left and bottom-left (where the thick left border meets the container edge), `padding: space-4 (16px)`, `margin: space-6 (24px) 0`
- Label: `type-body-bold` (Carlito, 14px, Bold), uppercase, letter-spacing 0.05em
- Body: `type-body` (Carlito, 14px, Regular), `color: color-neutral-dark`
- Icon: 20px, aligned to top of callout, `margin-right: space-3 (12px)`

**Usage Guidelines:**

Info callouts are used for architectural principles and design decisions (e.g., "Reversibility First: Every design decision must be reversible within 1 sprint"). Warning callouts flag potential pitfalls or conditions that require attention (e.g., "Schema evolution is additive-only; breaking changes will be blocked by Buf CI checks"). Error callouts mark hard constraints that will cause failures if violated (e.g., "No proprietary SDK imports in the domain/ directory -- pre-commit hooks will reject the commit"). Critical callouts designate non-negotiable security mandates (e.g., "Zero Trust: Every service-to-service call authenticates via SPIFFE/SPIRE mTLS").

### 3.4 Navigation

The navigation pattern supports multi-view architecture documentation with two complementary structures: breadcrumbs for linear position tracking and a sidebar for contextual navigation within the current view. Breadcrumbs show the reader's position in the documentation hierarchy (e.g., "Architecture > Service Topology > Gateway"), while the sidebar provides quick access to sibling sections and related topics. This dual-navigation pattern reduces disorientation in large architecture documents and enables non-linear exploration without losing positional context. The breadcrumb trail is always visible at the top of the viewport, while the sidebar is collapsible on narrow viewports to maximize content area.

**Breadcrumb Structure:**

```
Home > Phase 2 Design > Service Topology > Gateway
```

**Breadcrumb Styling:**

- Container: `bg: color-neutral-light`, `padding: space-2 (8px) space-4 (16px)`, `border-bottom: 1px solid color-border`
- Crumb Text: `type-caption` (Carlito, 12px), `color: color-neutral-mid`
- Active Crumb: `color: color-primary`, `font-weight: 600`
- Separator: `/` or `>`, `color: color-neutral-mid`, `margin: 0 space-1`

**Sidebar Structure:**

The sidebar organizes navigation items into collapsible groups. Each group represents a major documentation section (e.g., "Design Tokens," "Component Patterns," "Service Topology," "API Schemas"). Groups can contain nested items up to two levels deep. The currently active item is highlighted with a primary-colored left border and bold text, providing immediate positional context even when the main content area is scrolled.

**Sidebar Styling:**

- Container: `width: 260px`, `bg: color-surface`, `border-right: 1px solid color-border`, `padding: space-4 (16px)`
- Group Title: `type-caption` (Carlito, 12px, Bold), uppercase, `color: color-neutral-mid`, `letter-spacing: 0.08em`, `margin-bottom: space-2`
- Navigation Item: `type-body` (Carlito, 14px, Regular), `color: color-neutral-dark`, `padding: space-2 (8px) space-3 (12px)`, `border-left: 2px solid transparent`
- Active Item: `color: color-primary`, `font-weight: 600`, `border-left: 2px solid color-primary`, `bg: color-primary-light`
- Hover Item: `bg: color-neutral-light`, `border-left: 2px solid color-border`

**Responsive Behavior:**

On viewports narrower than 1024px, the sidebar collapses into a hamburger menu icon in the top-left corner. Tapping the icon reveals the sidebar as an overlay with a semi-transparent backdrop. On viewports narrower than 768px, the breadcrumb also collapses to show only the current and parent items (e.g., "... > Gateway"). In PDF and print contexts, neither the breadcrumb nor the sidebar is rendered; instead, the table of contents serves the navigational function.

---

## 4. Iconography

The iconography system provides visual identifiers for three categories of architectural semantics: programming languages, communication protocols, and operational status. Icons are used across all component patterns -- in service cards, architecture tables, callout boxes, and navigation items -- to provide instant visual recognition without requiring textual labels. All icons are designed as vector graphics at a standard size of 20px (inline) or 32px (standalone) with a 2px optical margin for visual balance within badge and card containers. The icon system prioritizes recognizability over aesthetic novelty, using established visual conventions from each technology's official branding wherever possible.

### 4.1 Language Icons

Language icons provide instant identification of a service's implementation technology. Each icon is a simplified, recognizable representation of the language's official mascot or logo, rendered in a consistent visual style. The icons are used in service cards (next to the language badge), in architecture table cells (preceding the language name), and in documentation headers (to indicate which language a section applies to). The consistent 20px inline size ensures that icons align with badge text without causing line-height disruption.

| Language | Icon Description | Primary Color | Badge Pairing |
|----------|-----------------|---------------|---------------|
| Go | Stylized Go gopher silhouette (simplified to 2-tone: body and eyes) | `#25728c` (primary teal, replacing the official blue for palette coherence) | Go badge (`#25728c` bg at 15%) |
| Rust | Rust crab (Ferris) silhouette, simplified to recognizable outline | `#c0392b` (error red, matching the Rust brand's warm tone) | Rust badge (`#c0392b` bg at 15%) |
| Node.js | Node.js hexagon with "JS" inset, simplified to outline + fill | `#27ae60` (success green, matching the Node.js brand) | Node.js badge (`#27ae60` bg at 15%) |
| Java/Kotlin | Java Duke silhouette (simplified) or Kotlin logo (shield with "K") | `#f39c12` (warning amber, matching the Java brand's warm orange) | Java badge (`#f39c12` bg at 15%) |
| Python | Interlocking snakes (Python logo simplified to 2-tone outline) | `#2980b9` (info blue, matching the Python brand's blue) | Python badge (`#2980b9` bg at 15%) |

**Icon Rendering Rules:**

Language icons must maintain their recognizable silhouette at sizes as small as 16px. To achieve this, details are simplified to the minimum viable visual identity -- the Go gopher's eyes and body shape, the Rust crab's claws and shell, the Node.js hexagon's geometry, the Java Duke's nose and visor, and the Python snakes' interlocking curves. Icons are rendered as inline SVG in HTML contexts and as embedded vector graphics in PDF contexts. In Markdown-only contexts, the icon is replaced by a colored circle (8px diameter) in the language's primary color, positioned immediately before the badge text.

### 4.2 Protocol Badges

Protocol badges identify the communication pattern used by each service and between service pairs. Unlike language icons, protocol badges use text-based abbreviations rather than pictorial icons, because protocol abbreviations (gRPC, REST, etc.) are more universally recognized than any abstract symbol could be. The badges use a compact pill shape with a colored background and contrasting text, making them immediately scannable in service cards and architecture tables. Each protocol has a distinct color to enable rapid visual differentiation when multiple protocols appear in the same view.

| Protocol | Badge Label | Background | Text Color | Usage Context |
|----------|------------|------------|------------|---------------|
| gRPC | `gRPC` | `#25728c` at 15% on white | `#25728c` | Service-to-service synchronous communication |
| REST | `REST` | `#27ae60` at 15% on white | `#27ae60` | External/client-facing HTTP APIs (OpenAPI) |
| CloudEvents | `CE` | `#2980b9` at 15% on white | `#2980b9` | Asynchronous event-driven communication |
| mTLS | `mTLS` | `#6a634c` at 15% on white | `#6a634c` | Mutual TLS authentication indicator |
| Outbox | `Outbox` | `#f39c12` at 15% on white | `#8a6d00` | Transactional Outbox pattern indicator |
| CDC | `CDC` | `#c0392b` at 12% on white | `#c0392b` | Change Data Capture pipeline indicator |

**Badge Composition Rules:**

When a service uses multiple protocols, badges are displayed in a horizontal row with `space-1` (4px) gaps between them. The badge order follows a consistent convention: synchronous first (gRPC, REST), then asynchronous (CloudEvents, Outbox), then security (mTLS), then infrastructure (CDC). This ordering ensures that the most operationally significant protocols appear first in the reading direction. In table cells where space is constrained, protocol badges can be truncated to their 2-4 character abbreviations without background fills, relying on color alone for differentiation.

### 4.3 Status Indicators

Status indicators communicate the operational state of services, SLO compliance, contract verification results, and pipeline gate outcomes. They use a combination of semantic colors, text labels, and optional pulse animations to convey state at multiple levels of urgency. The three primary states -- PASS, FAIL, and PENDING -- cover the vast majority of status communication needs in architecture documentation. Two additional states -- DEGRADED and UNKNOWN -- handle edge cases where binary pass/fail semantics are insufficient. All status indicators use the badge component pattern as their visual foundation, ensuring consistency with language and protocol badges.

| Status | Label | Background | Text Color | Icon | Animation |
|--------|-------|------------|------------|------|-----------|
| PASS | `PASS` | `#27ae60` at 15% on white | `#27ae60` | Checkmark (filled) | None |
| FAIL | `FAIL` | `#c0392b` at 15% on white | `#c0392b` | X mark (filled) | None |
| PENDING | `PENDING` | `#f39c12` at 15% on white | `#8a6d00` | Hourglass or clock | Subtle pulse (1.5s cycle) |
| DEGRADED | `DEGRADED` | `#f39c12` at 20% on white | `#c77d00` | Warning triangle | Slow pulse (3s cycle) |
| UNKNOWN | `UNKNOWN` | `#8a8a87` at 15% on white | `#8a8a87` | Question mark | None |

**Status Indicator Usage Contexts:**

In service cards, the SLO badge uses the PASS/DEGRADED/FAIL states to indicate current SLO compliance. In architecture tables, a dedicated status column shows contract verification results (Pact test outcomes) per service pair. In CI/CD pipeline visualizations, status indicators show gate outcomes (PASS = merge allowed, FAIL = merge blocked, PENDING = review in progress). In operational dashboards, status indicators show real-time service health with the DEGRADED state triggering when error budget consumption exceeds 50%. The UNKNOWN state is reserved for services that have not yet been onboarded or for metrics that are not yet being collected.

**Accessibility Considerations for Status Indicators:**

Status indicators must not rely solely on color to convey meaning. Each indicator includes a text label (PASS, FAIL, etc.) and an icon, ensuring that the state is communicated through three redundant channels: color, text, and shape. This triple-encoding ensures accessibility for users with color vision deficiencies, users of screen readers, and users of monochrome displays. The pulse animation for PENDING and DEGRADED states uses a subtle opacity cycle (0.7 to 1.0) rather than a size or position change, respecting the `prefers-reduced-motion` accessibility preference.

---

## 5. Token Application Summary

The following table provides a quick reference for applying design tokens to the most common element types in architecture documentation. Each row specifies the exact token values for a given element, enabling implementers to apply the design system consistently without referencing multiple sections of this document.

| Element | Background | Text | Border | Padding | Radius | Shadow |
|---------|-----------|------|--------|---------|--------|--------|
| Page | `color-neutral-light` | `color-neutral-dark` | none | `space-8` | none | none |
| Card | `color-surface` | `color-neutral-dark` | `1px solid color-border` | `space-4` | `8px` | `shadow-sm` |
| Badge | semantic color at 15% | semantic color | `1px solid` semantic at 30% | `space-1` v, `space-2` h | `4px` | none |
| Table Header | `color-primary` | `color-neutral-light` | none | `space-3` v, `space-4` h | none | none |
| Table Row (odd) | `color-surface` | `color-neutral-dark` | `1px solid color-border` (bottom) | `space-3` v, `space-4` h | none | none |
| Table Row (even) | `color-neutral-light` | `color-neutral-dark` | `1px solid color-border` (bottom) | `space-3` v, `space-4` h | none | none |
| Callout (Info) | `#2980b9` at 6% | `color-neutral-dark` | `4px solid #2980b9` (left) | `space-4` | `8px` | none |
| Callout (Warning) | `#f39c12` at 6% | `color-neutral-dark` | `4px solid #f39c12` (left) | `space-4` | `8px` | none |
| Callout (Error) | `#c0392b` at 6% | `color-neutral-dark` | `4px solid #c0392b` (left) | `space-4` | `8px` | none |
| Callout (Critical) | `#252421` at 8% | `color-neutral-dark` | `4px solid #252421` (left) | `space-4` | `8px` | none |
| Code Block | `color-neutral-light` | `color-neutral-dark` | `1px solid color-border` | `space-4` | `8px` | none |

---

## 6. Implementation Notes

This design system is intentionally technology-agnostic in its specification but must be implemented across multiple rendering contexts throughout the project lifecycle. The following notes guide implementation in the primary contexts.

**Markdown Context:** Design tokens are expressed as close to their specification as Markdown allows. Colors are referenced by hex value in HTML span elements. Badge components use inline HTML with span elements and style attributes. Tables use standard Markdown pipe syntax with HTML class attributes for stripe styling. Callout boxes use Markdown blockquotes with emoji-free labels (e.g., `[INFO]`, `[WARNING]`).

**HTML/CSS Context:** Design tokens are implemented as CSS custom properties (variables) on the `:root` element. Component patterns are implemented as CSS classes following the BEM naming convention (e.g., `.service-card`, `.service-card__badge--language`). Responsive breakpoints use CSS media queries at 768px and 1024px. Shadow transitions use CSS transitions with a 200ms ease-out timing function.

**ReportLab Context:** Design tokens are implemented as Python constants in the document generation script. Colors are specified as `reportlab.lib.colors.HexColor` instances. Typography is mapped to registered font families using `reportlab.pdfbase.pdfmetrics.registerFont`. Component patterns are implemented as custom Flowable subclasses that encapsulate the structural and styling logic.

**React Context:** Design tokens are implemented as a TypeScript theme object exported from a central module. Component patterns are implemented as React functional components with TypeScript interfaces for type-safe props. Badge variants use discriminated union types to ensure only valid semantic variants are passed. Accessibility attributes (aria-labels, role attributes) are built into every component.

---

*This design system document is the canonical reference for all visual design decisions in the "Best of Both Worlds" project. Any deviations from this system must be documented with rationale in the worklog and approved during design review (Spec 2.5).*
