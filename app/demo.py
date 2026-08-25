from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .models import ExtractedGraph


@dataclass(frozen=True)
class DemoArtifact:
    filename: str
    data: bytes
    extraction: ExtractedGraph


def _pdf_bytes(lines: list[str]) -> bytes:
    target = io.BytesIO()
    pdf = canvas.Canvas(target, pagesize=letter, pageCompression=0)
    y = 740
    for line in lines:
        pdf.drawString(54, y, line)
        y -= 22
    pdf.save()
    return target.getvalue()


def _repo_bytes() -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("cropprep/README.md", """# CropPrep
CropPrep is software from the Vision Systems Lab for reproducible crop-disease image preprocessing.
It uses the FieldLeaf-2026 dataset and applies resize normalization before crop-disease classification.
Maintainer: Priya Shah. The tool emits quality reports but does not train a classifier.
""")
        archive.writestr("cropprep/preprocess.py", """def normalize_crop_image(image):
    # Resize normalization for FieldLeaf-2026 crop-disease images.
    return image.resize((224, 224))
""")
        archive.writestr("cropprep/.env", "API_TOKEN=synthetic-secret-that-must-never-be-ingested")
        archive.writestr("cropprep/node_modules/ignored.js", "generated dependency content")
    return target.getvalue()


def _ev(quote: str, location: str = "body") -> list[dict]:
    return [{"quote": quote, "location": location}]


def build_demo_artifacts() -> list[DemoArtifact]:
    cs_lines = [
        "Field-Robust Crop Disease Classification",
        "Maya Rao, Department of Computer Science",
        "This study investigates crop-disease classification using a convolutional neural network.",
        "The model reaches strong validation accuracy on small curated images.",
        "The project lacks a high-quality labeled field dataset collected across real farms.",
        "A cross-department dataset partnership is needed before field evaluation.",
    ]
    cs_text_quotes = cs_lines
    cs_graph = ExtractedGraph.model_validate({
        "document": {"title": cs_lines[0], "summary": "A Computer Science study of convolutional neural networks for crop-disease classification that lacks field data."},
        "entities": [
            {"local_id": "doc", "type": "DOCUMENT", "name": cs_lines[0], "canonical_name": cs_lines[0], "description": "Synthetic Computer Science paper.", "confidence": 1, "evidence": _ev(cs_lines[0], "page 1")},
            {"local_id": "maya", "type": "RESEARCHER", "name": "Maya Rao", "canonical_name": "maya rao", "description": "Researcher in Computer Science.", "confidence": .99, "evidence": _ev(cs_lines[1], "page 1")},
            {"local_id": "cs", "type": "DEPARTMENT", "name": "Department of Computer Science", "canonical_name": "department of computer science", "description": "University department.", "confidence": .99, "evidence": _ev(cs_lines[1], "page 1")},
            {"local_id": "topic", "type": "TOPIC", "name": "Crop-disease classification", "canonical_name": "crop-disease classification", "description": "Classification of diseases in crop images.", "confidence": .98, "evidence": _ev(cs_lines[2], "page 1")},
            {"local_id": "cnn", "type": "METHOD", "name": "Convolutional neural network", "canonical_name": "convolutional neural network", "description": "Image classification method.", "confidence": .98, "evidence": _ev(cs_lines[2], "page 1")},
        ],
        "relationships": [
            {"source_local_id": "doc", "target_local_id": "maya", "type": "AUTHORED_BY", "confidence": .99, "evidence": _ev(cs_lines[1], "page 1")},
            {"source_local_id": "maya", "target_local_id": "cs", "type": "AFFILIATED_WITH", "confidence": .99, "evidence": _ev(cs_lines[1], "page 1")},
            {"source_local_id": "doc", "target_local_id": "topic", "type": "STUDIES", "confidence": .98, "evidence": _ev(cs_lines[2], "page 1")},
            {"source_local_id": "doc", "target_local_id": "cnn", "type": "USES_METHOD", "confidence": .98, "evidence": _ev(cs_lines[2], "page 1")},
        ],
    })

    agriculture_text = """# FieldLeaf-2026: A Labeled Crop Disease Dataset
Daniel Kim, Department of Agriculture

FieldLeaf-2026 is a labeled field dataset for crop-disease classification.
Agronomists collected 18,400 leaf images across 31 farms and assigned expert disease labels.
The project uses manual expert labeling and publishes a documented train/test split.
Our team has limited machine-learning capability and has not developed a robust classifier.
We seek collaboration with computer vision researchers.
"""
    ag_graph = ExtractedGraph.model_validate({
        "document": {"title": "FieldLeaf-2026: A Labeled Crop Disease Dataset", "summary": "An Agriculture dataset paper with labeled field images and limited machine-learning capacity."},
        "entities": [
            {"local_id": "doc", "type": "DOCUMENT", "name": "FieldLeaf-2026: A Labeled Crop Disease Dataset", "canonical_name": "fieldleaf-2026 paper", "description": "Synthetic Agriculture paper.", "confidence": 1, "evidence": _ev("FieldLeaf-2026: A Labeled Crop Disease Dataset", "heading")},
            {"local_id": "daniel", "type": "RESEARCHER", "name": "Daniel Kim", "canonical_name": "daniel kim", "description": "Agriculture researcher.", "confidence": .99, "evidence": _ev("Daniel Kim, Department of Agriculture", "line 2")},
            {"local_id": "ag", "type": "DEPARTMENT", "name": "Department of Agriculture", "canonical_name": "department of agriculture", "description": "University department.", "confidence": .99, "evidence": _ev("Daniel Kim, Department of Agriculture", "line 2")},
            {"local_id": "topic", "type": "TOPIC", "name": "Crop-disease classification", "canonical_name": "crop-disease classification", "description": "Classification of diseases in crop images.", "confidence": .97, "evidence": _ev("FieldLeaf-2026 is a labeled field dataset for crop-disease classification.", "paragraph 1")},
            {"local_id": "dataset", "type": "DATASET", "name": "FieldLeaf-2026", "canonical_name": "fieldleaf-2026", "description": "18,400 labeled leaf images from 31 farms.", "confidence": .99, "evidence": _ev("Agronomists collected 18,400 leaf images across 31 farms and assigned expert disease labels.", "paragraph 2")},
            {"local_id": "labeling", "type": "METHOD", "name": "Manual expert labeling", "canonical_name": "manual expert labeling", "description": "Agronomist-assigned disease labels.", "confidence": .98, "evidence": _ev("The project uses manual expert labeling and publishes a documented train/test split.", "paragraph 3")},
        ],
        "relationships": [
            {"source_local_id": "doc", "target_local_id": "daniel", "type": "AUTHORED_BY", "confidence": .99, "evidence": _ev("Daniel Kim, Department of Agriculture", "line 2")},
            {"source_local_id": "daniel", "target_local_id": "ag", "type": "AFFILIATED_WITH", "confidence": .99, "evidence": _ev("Daniel Kim, Department of Agriculture", "line 2")},
            {"source_local_id": "doc", "target_local_id": "topic", "type": "STUDIES", "confidence": .97, "evidence": _ev("FieldLeaf-2026 is a labeled field dataset for crop-disease classification.", "paragraph 1")},
            {"source_local_id": "doc", "target_local_id": "dataset", "type": "USES_DATASET", "confidence": .99, "evidence": _ev("Agronomists collected 18,400 leaf images across 31 farms and assigned expert disease labels.", "paragraph 2")},
            {"source_local_id": "doc", "target_local_id": "labeling", "type": "USES_METHOD", "confidence": .98, "evidence": _ev("The project uses manual expert labeling and publishes a documented train/test split.", "paragraph 3")},
        ],
    })

    repo_readme = "CropPrep is software from the Vision Systems Lab for reproducible crop-disease image preprocessing."
    repo_dataset = "It uses the FieldLeaf-2026 dataset and applies resize normalization before crop-disease classification."
    repo_maintainer = "Maintainer: Priya Shah. The tool emits quality reports but does not train a classifier."
    repo_graph = ExtractedGraph.model_validate({
        "document": {"title": "CropPrep Repository", "summary": "A synthetic preprocessing repository using FieldLeaf-2026 and resize normalization."},
        "entities": [
            {"local_id": "doc", "type": "DOCUMENT", "name": "CropPrep Repository", "canonical_name": "cropprep repository", "description": "Synthetic code repository.", "confidence": 1, "evidence": _ev("# CropPrep", "cropprep/README.md")},
            {"local_id": "priya", "type": "RESEARCHER", "name": "Priya Shah", "canonical_name": "priya shah", "description": "CropPrep maintainer.", "confidence": .99, "evidence": _ev(repo_maintainer, "cropprep/README.md")},
            {"local_id": "lab", "type": "DEPARTMENT", "name": "Vision Systems Lab", "canonical_name": "vision systems lab", "description": "Research lab producing CropPrep.", "confidence": .95, "evidence": _ev(repo_readme, "cropprep/README.md")},
            {"local_id": "topic", "type": "TOPIC", "name": "Crop-disease classification", "canonical_name": "crop-disease classification", "description": "Classification of diseases in crop images.", "confidence": .96, "evidence": _ev(repo_dataset, "cropprep/README.md")},
            {"local_id": "dataset", "type": "DATASET", "name": "FieldLeaf-2026", "canonical_name": "fieldleaf-2026", "description": "Labeled crop image dataset.", "confidence": .98, "evidence": _ev(repo_dataset, "cropprep/README.md")},
            {"local_id": "method", "type": "METHOD", "name": "Resize normalization", "canonical_name": "resize normalization", "description": "Image preprocessing method.", "confidence": .98, "evidence": _ev(repo_dataset, "cropprep/README.md")},
            {"local_id": "software", "type": "SOFTWARE", "name": "CropPrep", "canonical_name": "cropprep", "description": "Reproducible crop image preprocessing software.", "confidence": .99, "evidence": _ev(repo_readme, "cropprep/README.md")},
        ],
        "relationships": [
            {"source_local_id": "doc", "target_local_id": "priya", "type": "AUTHORED_BY", "confidence": .96, "evidence": _ev(repo_maintainer, "cropprep/README.md")},
            {"source_local_id": "priya", "target_local_id": "lab", "type": "AFFILIATED_WITH", "confidence": .91, "evidence": _ev(repo_readme, "cropprep/README.md")},
            {"source_local_id": "doc", "target_local_id": "topic", "type": "STUDIES", "confidence": .96, "evidence": _ev(repo_dataset, "cropprep/README.md")},
            {"source_local_id": "doc", "target_local_id": "dataset", "type": "USES_DATASET", "confidence": .98, "evidence": _ev(repo_dataset, "cropprep/README.md")},
            {"source_local_id": "doc", "target_local_id": "method", "type": "USES_METHOD", "confidence": .98, "evidence": _ev(repo_dataset, "cropprep/README.md")},
            {"source_local_id": "doc", "target_local_id": "software", "type": "IMPLEMENTS", "confidence": .99, "evidence": _ev(repo_readme, "cropprep/README.md")},
        ],
    })

    overlap_text = """# Reproducible Crop-Disease Image Preparation with FieldLeaf-2026
Elena Torres, Department of Data Science

We study crop-disease classification using the FieldLeaf-2026 dataset.
Our pipeline applies resize normalization to 224 by 224 pixels before classification.
We evaluate the documented FieldLeaf-2026 train/test split and publish preprocessing quality reports.
This independent study focuses on preprocessing reproducibility, not model architecture.
"""
    overlap_graph = ExtractedGraph.model_validate({
        "document": {"title": "Reproducible Crop-Disease Image Preparation with FieldLeaf-2026", "summary": "An independent study using the same dataset and resize normalization as CropPrep."},
        "entities": [
            {"local_id": "doc", "type": "DOCUMENT", "name": "Reproducible Crop-Disease Image Preparation with FieldLeaf-2026", "canonical_name": "reproducible fieldleaf image preparation", "description": "Synthetic overlap study.", "confidence": 1, "evidence": _ev("Reproducible Crop-Disease Image Preparation with FieldLeaf-2026", "heading")},
            {"local_id": "elena", "type": "RESEARCHER", "name": "Elena Torres", "canonical_name": "elena torres", "description": "Data Science researcher.", "confidence": .99, "evidence": _ev("Elena Torres, Department of Data Science", "line 2")},
            {"local_id": "ds", "type": "DEPARTMENT", "name": "Department of Data Science", "canonical_name": "department of data science", "description": "University department.", "confidence": .99, "evidence": _ev("Elena Torres, Department of Data Science", "line 2")},
            {"local_id": "topic", "type": "TOPIC", "name": "Crop-disease classification", "canonical_name": "crop-disease classification", "description": "Classification of diseases in crop images.", "confidence": .98, "evidence": _ev("We study crop-disease classification using the FieldLeaf-2026 dataset.", "paragraph 1")},
            {"local_id": "dataset", "type": "DATASET", "name": "FieldLeaf-2026", "canonical_name": "fieldleaf-2026", "description": "Labeled crop image dataset.", "confidence": .99, "evidence": _ev("We study crop-disease classification using the FieldLeaf-2026 dataset.", "paragraph 1")},
            {"local_id": "method", "type": "METHOD", "name": "Resize normalization", "canonical_name": "resize normalization", "description": "Image resizing before classification.", "confidence": .99, "evidence": _ev("Our pipeline applies resize normalization to 224 by 224 pixels before classification.", "paragraph 2")},
        ],
        "relationships": [
            {"source_local_id": "doc", "target_local_id": "elena", "type": "AUTHORED_BY", "confidence": .99, "evidence": _ev("Elena Torres, Department of Data Science", "line 2")},
            {"source_local_id": "elena", "target_local_id": "ds", "type": "AFFILIATED_WITH", "confidence": .99, "evidence": _ev("Elena Torres, Department of Data Science", "line 2")},
            {"source_local_id": "doc", "target_local_id": "topic", "type": "STUDIES", "confidence": .98, "evidence": _ev("We study crop-disease classification using the FieldLeaf-2026 dataset.", "paragraph 1")},
            {"source_local_id": "doc", "target_local_id": "dataset", "type": "USES_DATASET", "confidence": .99, "evidence": _ev("We study crop-disease classification using the FieldLeaf-2026 dataset.", "paragraph 1")},
            {"source_local_id": "doc", "target_local_id": "method", "type": "USES_METHOD", "confidence": .99, "evidence": _ev("Our pipeline applies resize normalization to 224 by 224 pixels before classification.", "paragraph 2")},
        ],
    })

    return [
        DemoArtifact("synthetic_cs_crop_study.pdf", _pdf_bytes(cs_lines), cs_graph),
        DemoArtifact("synthetic_agriculture_dataset.md", agriculture_text.encode(), ag_graph),
        DemoArtifact("synthetic_cropprep_repository.zip", _repo_bytes(), repo_graph),
        DemoArtifact("synthetic_overlap_study.md", overlap_text.encode(), overlap_graph),
    ]
