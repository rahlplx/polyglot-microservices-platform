# Context Template: Task Receive
# Auto-injected when a new task is received. Provides classification, routing, and skill mapping.

## Task Classification Decision Tree

Answer these questions in order:

1. **Is the final deliverable a document file?** (report, PDF, DOCX, PPT, XLSX, proposal, manuscript)
   → **YES:** Type 1 (Document Creation) → Route to `pdf`/`docx`/`xlsx`/`ppt` skill

2. **Is the final deliverable a chart/diagram/visualization?** (bar chart, flowchart, mind map, PNG, architecture diagram)
   → **YES:** Type 2 (Data Visualization) → Route to `charts` skill

3. **Is the final deliverable an interactive web page/application?** (dashboard, web app, real-time interface)
   → **YES:** Type 3 (Web Development) → Route to `fullstack-dev` skill

4. **Is the task about processing/transforming data?** (analyze CSV, clean data, calculate statistics)
   → **YES:** Type 4 (Data Processing) → Write Python script

5. **Ambiguous?** → Ask user: "Do you want a document with charts, or an interactive web page?"

## Workflow Routing Map

| Type | gstack Pre-Skills | System Skill | Fallback |
|------|-------------------|-------------|----------|
| Type 1 | /office-hours, /design-consultation, /document-generate | pdf, docx, xlsx, ppt | pdf |
| Type 2 | /design-consultation, /design-shotgun, /design-review | charts | charts |
| Type 3 | /design-html, /design-review, /qa, /review | fullstack-dev | fullstack-dev |
| Type 4 | /investigate, /benchmark, /health | (python script) | python |

## Token Budget Estimation

| Complexity | Steps | Token Budget | Strategy |
|-----------|-------|-------------|----------|
| Simple | 1-2 | <5K | Direct execution |
| Medium | 3-5 | 5K-20K | 1-2 subagents |
| Complex | 6+ | 20K+ | Full parallel orchestration |

## Context Injection Points

For Type 1 (Document):
- Inject: document type, format requirements, font system, template choice
- Pre-skill: `/office-hours` if the document needs design thinking
- Skill: `pdf` for reports, `docx` for Word, `xlsx` for spreadsheets, `ppt` for presentations

For Type 2 (Visualization):
- Inject: chart type, data source, output format (PNG/SVG/interactive)
- Pre-skill: `/design-consultation` for complex visual design
- Skill: `charts` with scene routing (matplotlib/seaborn/ECharts/D3/Mermaid/Playwright+CSS)

For Type 3 (Web Dev):
- Inject: Next.js 16, TypeScript, Tailwind CSS 4, shadcn/ui, Prisma
- Pre-skill: `/design-html` for UI design, `/design-review` for review
- Skill: `fullstack-dev` → Complete tool at end

For Type 4 (Data):
- Inject: input format, output format, transformation rules
- Pre-skill: `/investigate` if the data is messy/unknown
- Skill: Python script with pandas/numpy as needed
