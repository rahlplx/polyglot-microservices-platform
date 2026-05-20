#!/usr/bin/env python3
"""
NLP Intelligent Router — Embeddings-based Intent Classification & Auto-Trigger

Uses sentence-transformers to compute semantic similarity between user queries
and predefined intent embeddings. Routes tasks to certified workflows with
confidence scores and automatic fallback chains.

Architecture:
  User Query → Embed → Compare with Intent Embeddings → Classify → Route → Trigger

Intents are mapped to:
  - Task types (Type 1-4)
  - gstack skills
  - System skills
  - Context templates
  - Failover chains
"""

import json
import os
import sys
import hashlib
import numpy as np
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = "/home/z/my-project"
ENGINE_DIR = f"{PROJECT_ROOT}/.claude/engine"
CONTEXT_DIR = f"{PROJECT_ROOT}/.claude/context"
CACHE_DIR = f"{PROJECT_ROOT}/.claude/.embedding-cache"

# ─── Intent Definitions ───────────────────────────────────────
# Each intent has: name, task_type, trigger_patterns, gstack_skills,
# system_skill, fallback, context_template, confidence_threshold
INTENTS = {
    "document_creation": {
        "name": "Document Creation",
        "task_type": "Type 1",
        "trigger_patterns": [
            "generate a document", "create a report", "write a PRD", "make a PDF",
            "create a proposal", "write a manuscript", "generate a white paper",
            "create a spreadsheet", "make a presentation", "write an article",
            "draft a document", "produce a report", "compile documentation",
            "build a docx file", "generate xlsx", "create pptx slides",
            "write requirements document", "produce analysis report",
            "architecture document", "solution architecture pdf",
            "vendor-agnostic design document", "technology-agnostic report",
            "quality assurance document", "cloud portability report",
            "comprehensive solution architecture", "best of both worlds document"
        ],
        "gstack_skills": ["/office-hours", "/design-consultation", "/document-generate", "/document-release", "/make-pdf"],
        "system_skill": "pdf",
        "fallback_skill": "pdf",
        "context_template": "document_context",
        "confidence_threshold": 0.55
    },
    "data_visualization": {
        "name": "Data Visualization",
        "task_type": "Type 2",
        "trigger_patterns": [
            "create a chart", "generate a graph", "draw a diagram", "make a flowchart",
            "create a mind map", "visualize data", "plot a graph", "build a dashboard chart",
            "architecture diagram", "deployment diagram", "route map",
            "generate a bar chart", "create a line chart", "make a pie chart",
            "draw a scatter plot", "create a heatmap", "generate a radar chart",
            "knowledge graph", "tree diagram", "org chart", "sequence diagram",
            "ER diagram", "class diagram", "Gantt chart"
        ],
        "gstack_skills": ["/design-consultation", "/design-shotgun", "/design-review"],
        "system_skill": "charts",
        "fallback_skill": "charts",
        "context_template": "visualization_context",
        "confidence_threshold": 0.55
    },
    "web_development": {
        "name": "Web Development",
        "task_type": "Type 3",
        "trigger_patterns": [
            "build a webpage", "create a web app", "develop a dashboard",
            "make an interactive page", "build a frontend", "create a Next.js app",
            "develop a website", "build a UI", "create a web interface",
            "develop a real-time dashboard", "build a management system",
            "create a landing page", "build a full-stack application",
            "interactive data dashboard webpage", "online application"
        ],
        "gstack_skills": ["/design-consultation", "/design-html", "/design-review", "/qa", "/ship", "/review"],
        "system_skill": "fullstack-dev",
        "fallback_skill": "fullstack-dev",
        "context_template": "webdev_context",
        "confidence_threshold": 0.55
    },
    "data_processing": {
        "name": "Data Processing",
        "task_type": "Type 4",
        "trigger_patterns": [
            "process data", "analyze this data", "transform data", "calculate statistics",
            "parse a file", "clean data", "run calculations", "process a CSV",
            "analyze a spreadsheet", "compute metrics", "extract insights from data",
            "data pipeline", "ETL process", "batch processing"
        ],
        "gstack_skills": ["/investigate", "/benchmark", "/health"],
        "system_skill": "",
        "fallback_skill": "python_script",
        "context_template": "data_context",
        "confidence_threshold": 0.50
    },
    "code_review": {
        "name": "Code Review",
        "task_type": "Type_Code",
        "trigger_patterns": [
            "review my code", "check this PR", "review the code before merging",
            "code review", "PR review", "find bugs in this code",
            "adversarial code review", "edge case hunting"
        ],
        "gstack_skills": ["/review", "/codex"],
        "system_skill": "",
        "fallback_skill": "/review",
        "context_template": "execution_context",
        "confidence_threshold": 0.60
    },
    "qa_testing": {
        "name": "QA & Testing",
        "task_type": "Type_QA",
        "trigger_patterns": [
            "run QA", "test this application", "find bugs", "quality assurance",
            "verify the fix", "regression test", "performance benchmark",
            "security audit", "OWASP check", "STRIDE analysis"
        ],
        "gstack_skills": ["/qa", "/qa-only", "/benchmark", "/cso", "/investigate"],
        "system_skill": "",
        "fallback_skill": "/qa",
        "context_template": "execution_context",
        "confidence_threshold": 0.55
    },
    "ship_deploy": {
        "name": "Ship & Deploy",
        "task_type": "Type_Ship",
        "trigger_patterns": [
            "ship this code", "create a PR", "deploy to production",
            "merge and deploy", "canary deployment", "release this version",
            "push to staging", "land this PR"
        ],
        "gstack_skills": ["/ship", "/land-and-deploy", "/canary", "/landing-report"],
        "system_skill": "",
        "fallback_skill": "/ship",
        "context_template": "execution_context",
        "confidence_threshold": 0.60
    },
    "design_consultation": {
        "name": "Design Consultation",
        "task_type": "Type_Design",
        "trigger_patterns": [
            "design consultation", "build a design system", "design review",
            "visual audit", "design exploration", "multiple design variants",
            "UI review", "UX review", "design feedback"
        ],
        "gstack_skills": ["/design-consultation", "/design-shotgun", "/design-review", "/design-html"],
        "system_skill": "",
        "fallback_skill": "/design-consultation",
        "context_template": "execution_context",
        "confidence_threshold": 0.55
    }
}

class NLPIntelligentRouter:
    """Embeddings-based NLP router with intent classification and auto-trigger."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", use_cache: bool = True):
        self.model_name = model_name
        self.use_cache = use_cache
        self.model = None
        self.intent_embeddings = {}
        self._ensure_cache_dir()

    def _ensure_cache_dir(self):
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _get_cache_path(self, text: str) -> str:
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        return os.path.join(CACHE_DIR, f"{h}.npy")

    def load_model(self):
        """Lazy-load the sentence-transformers model."""
        if self.model is None:
            print(f"[NLP-Router] Loading model: {self.model_name}...", file=sys.stderr)
            self.model = SentenceTransformer(self.model_name)
            print(f"[NLP-Router] Model loaded. Dimensions: {self.model.get_sentence_embedding_dimension()}", file=sys.stderr)

    def _embed(self, text: str) -> np.ndarray:
        """Get embedding for a single text, with caching."""
        if self.use_cache:
            cache_path = self._get_cache_path(text)
            if os.path.exists(cache_path):
                return np.load(cache_path)

        self.load_model()
        embedding = self.model.encode(text, normalize_embeddings=True)

        if self.use_cache:
            np.save(self._get_cache_path(text), embedding)

        return embedding

    def precompute_intent_embeddings(self):
        """Precompute and cache embeddings for all intent trigger patterns."""
        self.load_model()
        print("[NLP-Router] Precomputing intent embeddings...", file=sys.stderr)

        for intent_key, intent_data in INTENTS.items():
            patterns = intent_data["trigger_patterns"]
            embeddings = self.model.encode(patterns, normalize_embeddings=True)
            # Store mean embedding as the intent centroid
            centroid = np.mean(embeddings, axis=0)
            centroid = centroid / np.linalg.norm(centroid)  # re-normalize
            self.intent_embeddings[intent_key] = {
                "centroid": centroid,
                "all_embeddings": embeddings,
                "patterns": patterns
            }

        # Save precomputed embeddings
        save_path = os.path.join(CACHE_DIR, "intent_embeddings.npz")
        save_data = {}
        for key, val in self.intent_embeddings.items():
            save_data[f"{key}_centroid"] = val["centroid"]
            save_data[f"{key}_all"] = val["all_embeddings"]
        np.savez(save_path, **save_data)
        print(f"[NLP-Router] Intent embeddings saved to {save_path}", file=sys.stderr)

    def load_precomputed(self):
        """Load precomputed intent embeddings from cache."""
        save_path = os.path.join(CACHE_DIR, "intent_embeddings.npz")
        if not os.path.exists(save_path):
            self.precompute_intent_embeddings()
            return

        data = np.load(save_path, allow_pickle=True)
        for intent_key in INTENTS:
            centroid_key = f"{intent_key}_centroid"
            all_key = f"{intent_key}_all"
            if centroid_key in data:
                self.intent_embeddings[intent_key] = {
                    "centroid": data[centroid_key],
                    "all_embeddings": data[all_key] if all_key in data else None,
                    "patterns": INTENTS[intent_key]["trigger_patterns"]
                }
        print(f"[NLP-Router] Loaded {len(self.intent_embeddings)} intent embeddings from cache", file=sys.stderr)

    def classify(self, query: str, top_k: int = 3) -> list:
        """
        Classify a user query into intents with confidence scores.

        Returns list of (intent_key, confidence, intent_data) sorted by confidence descending.
        Uses both centroid similarity and max pattern similarity for robustness.
        """
        if not self.intent_embeddings:
            self.load_precomputed()

        query_embedding = self._embed(query)
        results = []

        for intent_key, intent_emb in self.intent_embeddings.items():
            centroid = intent_emb["centroid"]

            # Method 1: Cosine similarity with centroid
            centroid_sim = float(np.dot(query_embedding, centroid))

            # Method 2: Max similarity with individual patterns (more robust for short queries)
            if intent_emb["all_embeddings"] is not None:
                pattern_sims = np.dot(intent_emb["all_embeddings"], query_embedding)
                max_pattern_sim = float(np.max(pattern_sims))
            else:
                max_pattern_sim = centroid_sim

            # Weighted combination: centroid provides stability, max_pattern provides precision
            combined_score = 0.4 * centroid_sim + 0.6 * max_pattern_sim

            intent_data = INTENTS[intent_key]
            threshold = intent_data.get("confidence_threshold", 0.55)

            results.append({
                "intent": intent_key,
                "name": intent_data["name"],
                "task_type": intent_data["task_type"],
                "confidence": round(combined_score, 4),
                "centroid_similarity": round(centroid_sim, 4),
                "max_pattern_similarity": round(max_pattern_sim, 4),
                "above_threshold": combined_score >= threshold,
                "gstack_skills": intent_data["gstack_skills"],
                "system_skill": intent_data["system_skill"],
                "fallback_skill": intent_data["fallback_skill"],
                "context_template": intent_data["context_template"]
            })

        # Sort by confidence descending
        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:top_k]

    def route(self, query: str) -> dict:
        """
        Route a user query to the best matching workflow.

        Returns the routing decision with:
          - primary intent (highest confidence above threshold)
          - alternative intents (other candidates)
          - recommended skills and context
          - failover plan if confidence is low
        """
        candidates = self.classify(query, top_k=3)

        if not candidates:
            return {
                "status": "no_match",
                "query": query,
                "primary": None,
                "alternatives": [],
                "action": "default_to_type1",
                "message": "No intent matched. Defaulting to Type 1 (Document Creation)."
            }

        primary = candidates[0]

        # High confidence: route directly
        if primary["above_threshold"] and primary["confidence"] >= 0.70:
            return {
                "status": "high_confidence",
                "query": query,
                "primary": primary,
                "alternatives": candidates[1:],
                "action": "route_directly",
                "message": f"High confidence match: {primary['name']} ({primary['confidence']:.1%})"
            }

        # Medium confidence: route with alternatives noted
        if primary["above_threshold"]:
            return {
                "status": "medium_confidence",
                "query": query,
                "primary": primary,
                "alternatives": candidates[1:],
                "action": "route_with_caution",
                "message": f"Medium confidence match: {primary['name']} ({primary['confidence']:.1%}). Alternatives: {[a['name'] for a in candidates[1:]]}"
            }

        # Low confidence: ask for clarification
        return {
            "status": "low_confidence",
            "query": query,
            "primary": primary,
            "alternatives": candidates[1:],
            "action": "ask_user_for_clarification",
            "message": f"Low confidence in classification. Best guess: {primary['name']} ({primary['confidence']:.1%}). Please clarify: Do you want a document, a chart, a web page, or data processing?"
        }


def main():
    """CLI interface for the NLP Intelligent Router."""
    if len(sys.argv) < 2:
        print("Usage: python3 nlp_router.py <query>")
        print("       python3 nlp_router.py --precompute")
        print("       python3 nlp_router.py --test")
        sys.exit(1)

    command = sys.argv[1]
    router = NLPIntelligentRouter()

    if command == "--precompute":
        router.precompute_intent_embeddings()
        print("Intent embeddings precomputed and cached.")
        return

    if command == "--test":
        test_queries = [
            "generate a PDF report about cloud architecture",
            "create a bar chart showing performance metrics",
            "build an interactive web dashboard for monitoring",
            "analyze this CSV file and compute statistics",
            "review my pull request for security issues",
            "run quality assurance on the deployment",
            "ship this feature branch to production",
            "design a new UI component system",
            "comprehensive solution architecture the best of both worlds",
            "vendor-agnostic design with zero vendor lock-in"
        ]
        router.load_precomputed()
        print("\n" + "=" * 70)
        print("  NLP INTELLIGENT ROUTER — TEST SUITE")
        print("=" * 70)
        for query in test_queries:
            result = router.route(query)
            p = result["primary"]
            print(f"\n  Query: \"{query}\"")
            print(f"  → {result['status'].upper()}: {p['name']} ({p['confidence']:.1%})")
            print(f"    Type: {p['task_type']} | Skill: {p['system_skill'] or p['gstack_skills'][0]}")
            print(f"    Action: {result['action']}")
        print("\n" + "=" * 70)
        return

    # Normal routing
    query = " ".join(sys.argv[1:])
    router.load_precomputed()
    result = router.route(query)

    # Output as JSON for programmatic consumption
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
