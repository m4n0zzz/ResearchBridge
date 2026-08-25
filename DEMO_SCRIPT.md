# ResearchBridge — 3-minute demo

## 0:00 — The problem and promise

Open the app. Say:

“University research is siloed by department and format. ResearchBridge turns papers and repositories into one evidence-backed graph. The differentiator is that every connection is traceable to exact source text.”

Point to the three promises in the header: source evidence, confidence, provenance.

## 0:20 — Load real parsed formats

Click **Load synthetic demo data**.

Say:

“These four artifacts are clearly labeled synthetic. The loader still sends a generated text PDF, two Markdown papers, and a repository ZIP through the real safe parsers. The repository contains a `.env` and dependency folder specifically to demonstrate that they are excluded.”

The graph refreshes immediately.

## 0:50 — Evidence, not graph decoration

Click a graph edge such as `USES_DATASET`, then a topic or dataset node.

Say:

“This is not just a colorful graph. The detail drawer shows confidence, the source artifact, location, and exact excerpt. Model output that cannot point back into the source is rejected before persistence.”

## 1:20 — Collaboration Radar

Open the top Collaboration Radar result.

Say:

“The Computer Science team has a classifier but explicitly lacks field data. Agriculture has a labeled field dataset but explicitly says it lacks machine-learning capability. Shared topic plus different groups plus complementary assets creates this deterministic opportunity.”

## 1:50 — Overlap Radar

Open the CropPrep/independent-study overlap result.

Say:

“This independent study has high semantic similarity and explicitly shares both FieldLeaf-2026 and resize normalization with the repository. ResearchBridge calls it potential overlap—a review signal, never plagiarism or misconduct.”

## 2:15 — Ask the graph

Search: **Who could collaborate on crop-disease research and why?**

Say:

“With a Gemini key, the question is embedded, matched to documents and entities, expanded through graph paths, and answered by Gemini only from retrieved evidence. This machine has no supplied key, so the app honestly labels the extractive local fallback.”

## 2:40 — Production path

Say:

“The prototype has real AIProvider and GraphStore boundaries. Production swaps Gemini Developer API for Vertex AI, SQLite JSON vectors for indexed AlloyDB vector columns, and this same container for Cloud Run. I am not claiming those GCP services are running today.”

End on the graph with both Radars visible.
