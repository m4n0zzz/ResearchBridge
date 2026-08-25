from __future__ import annotations

import io
import zipfile

import pytest

from app.parsers import ParseError, parse_markdown, parse_pdf, parse_repository_zip
from conftest import make_pdf


def zip_bytes(files: dict[str, str]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return target.getvalue()


def test_markdown_parsing_utf8():
    artifact = parse_markdown("# Café research".encode(), "résumé.md")
    assert artifact.artifact_type == "markdown"
    assert "Café research" in artifact.text
    assert artifact.filename.endswith(".md")


def test_pdf_ingestion_extracts_text():
    artifact = parse_pdf(make_pdf("Evidence-backed crop research"), "paper.pdf")
    assert artifact.artifact_type == "pdf"
    assert "Evidence-backed crop research" in artifact.text


def test_empty_pdf_has_helpful_ocr_error():
    with pytest.raises(ParseError, match="OCR"):
        parse_pdf(make_pdf(""), "scan.pdf")


def test_safe_repository_zip_prioritizes_and_combines_text(settings):
    data = zip_bytes({"repo/src/model.py": "print('model')", "repo/README.md": "# Research repository"})
    artifact = parse_repository_zip(data, "repo.zip", settings)
    assert artifact.artifact_type == "repository_zip"
    assert artifact.text.index("README.md") < artifact.text.index("model.py")


@pytest.mark.parametrize("path", ["../escape.md", "repo/../../escape.py", "C:/escape.md", "/root/escape.md"])
def test_zip_traversal_rejected(path, settings):
    with pytest.raises(ParseError, match="Unsafe ZIP path"):
        parse_repository_zip(zip_bytes({path: "bad"}), "hostile.zip", settings)


def test_secret_dependency_generated_and_binary_files_excluded(settings):
    data = zip_bytes({
        "repo/README.md": "safe readme",
        "repo/.env": "TOKEN=do-not-read",
        "repo/api_key.txt": "super-secret",
        "repo/private.pem": "private-key",
        "repo/node_modules/x.js": "dependency",
        "repo/dist/bundle.js": "generated",
        "repo/package-lock.json": "lock",
        "repo/image.png": "binary-ish",
    })
    artifact = parse_repository_zip(data, "repo.zip", settings)
    assert "safe readme" in artifact.text
    for forbidden in ("do-not-read", "super-secret", "private-key", "dependency", "generated", "binary-ish"):
        assert forbidden not in artifact.text


def test_oversized_zip_member_is_never_read(settings):
    strict = settings.model_copy(update={"max_zip_member_bytes": 32, "max_zip_declared_bytes": 4096})
    data = zip_bytes({"repo/README.md": "safe", "repo/large.py": "x" * 200})
    artifact = parse_repository_zip(data, "repo.zip", strict)
    assert "safe" in artifact.text
    assert "large.py" not in artifact.text


def test_secret_content_in_ordinarily_named_repo_file_is_excluded(settings):
    data = zip_bytes({"repo/README.md": "safe", "repo/config.py": "api_key = 'abcdefghijklmnop123456'"})
    artifact = parse_repository_zip(data, "repo.zip", settings)
    assert "safe" in artifact.text
    assert "abcdefghijklmnop123456" not in artifact.text


def test_pdf_page_limit_is_enforced(settings):
    strict = settings.model_copy(update={"max_pdf_pages": 0})
    with pytest.raises(ParseError, match="too many pages"):
        parse_pdf(make_pdf("one page"), "paper.pdf", strict)
