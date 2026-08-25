from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from pypdf import PdfReader

from .config import Settings


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedArtifact:
    filename: str
    artifact_type: str
    text: str


SAFE_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".sql", ".r", ".jl",
    ".yaml", ".yml", ".toml", ".json", ".ipynb", ".xml", ".csv",
}
IGNORED_PARTS = {".git", "node_modules", "vendor", "dist", "build", "coverage", "__pycache__", ".venv", "venv"}
IGNORED_NAMES = {
    ".env", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock",
    "cargo.lock", "composer.lock",
}
SECRET_PATTERNS = (
    re.compile(r"(^|[._-])(secret|credential|credentials|private|token|apikey|api_key)([._-]|$)", re.I),
    re.compile(r"\.(pem|key|p12|pfx|jks|keystore)$", re.I),
)
SECRET_CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I),
    re.compile(r"(?im)^\s*(api[_-]?key|secret|token|password|credential)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{12,}"),
    re.compile(r"\b(?:AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9_]{30,})\b"),
)


def sanitize_filename(name: str) -> str:
    value = PurePosixPath(name.replace("\\", "/")).name
    value = re.sub(r"[^A-Za-z0-9._ -]", "_", value).strip(" .")
    return value[:180] or "upload"


def parse_markdown(data: bytes, filename: str) -> ParsedArtifact:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError("Markdown must be valid UTF-8 text.") from exc
    if not text.strip():
        raise ParseError("Markdown file is empty.")
    if any(pattern.search(text) for pattern in SECRET_CONTENT_PATTERNS):
        raise ParseError("Markdown appears to contain a credential or private key and was not ingested.")
    return ParsedArtifact(sanitize_filename(filename), "markdown", text)


def parse_pdf(data: bytes, filename: str, settings: Settings | None = None) -> ParsedArtifact:
    settings = settings or Settings()
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError("Encrypted PDFs are not supported.")
        if len(reader.pages) > settings.max_pdf_pages:
            raise ParseError(f"PDF has too many pages (limit {settings.max_pdf_pages}).")
        pages = []
        text_bytes = 0
        for index, page in enumerate(reader.pages, start=1):
            content = page.extract_text() or ""
            if content.strip():
                text_bytes += len(content.encode("utf-8"))
                if text_bytes > settings.max_pdf_text_bytes:
                    raise ParseError("PDF contains too much extracted text for this prototype.")
                pages.append(f"[Page {index}]\n{content.strip()}")
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("PDF is unreadable or invalid.") from exc
    text = "\n\n".join(pages)
    if not text.strip():
        raise ParseError("No extractable text found. Scanned PDFs need OCR, which is outside this MVP.")
    if any(pattern.search(text) for pattern in SECRET_CONTENT_PATTERNS):
        raise ParseError("PDF appears to contain a credential or private key and was not ingested.")
    return ParsedArtifact(sanitize_filename(filename), "pdf", text)


def _is_safe_zip_path(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not path.is_absolute() and ".." not in path.parts and not re.match(r"^[A-Za-z]:", normalized)


def _include_repo_file(path: PurePosixPath) -> bool:
    lowered_parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    if lowered_parts & IGNORED_PARTS or name in IGNORED_NAMES:
        return False
    if any(pattern.search(name) for pattern in SECRET_PATTERNS):
        return False
    return path.suffix.casefold() in SAFE_EXTENSIONS


def parse_repository_zip(data: bytes, filename: str, settings: Settings) -> ParsedArtifact:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ParseError("ZIP archive is unreadable or invalid.") from exc

    infos = archive.infolist()
    if len(infos) > settings.max_zip_files:
        raise ParseError(f"ZIP contains too many entries (limit {settings.max_zip_files}).")
    declared_bytes = sum(info.file_size for info in infos if not info.is_dir())
    if declared_bytes > settings.max_zip_declared_bytes:
        raise ParseError("ZIP declared uncompressed content exceeds the safety limit.")
    for info in infos:
        if not _is_safe_zip_path(info.filename):
            raise ParseError(f"Unsafe ZIP path rejected: {info.filename}")

    candidates = [
        info for info in infos
        if not info.is_dir()
        and info.file_size <= settings.max_zip_member_bytes
        and (info.file_size <= 4096 or info.file_size / max(1, info.compress_size) <= settings.max_zip_compression_ratio)
        and _include_repo_file(PurePosixPath(info.filename.replace("\\", "/")))
    ]
    candidates.sort(key=lambda info: (0 if PurePosixPath(info.filename).name.casefold().startswith("readme") else 1, info.filename.casefold()))
    sections: list[str] = []
    total = 0
    for info in candidates:
        remaining = settings.max_zip_text_bytes - total
        if remaining <= 0:
            break
        read_limit = min(settings.max_zip_member_bytes, remaining)
        with archive.open(info) as member:
            raw = member.read(read_limit + 1)
        if len(raw) > read_limit:
            raw = raw[:read_limit]
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in SECRET_CONTENT_PATTERNS):
            continue
        encoded = text.encode("utf-8")[:remaining]
        text = encoded.decode("utf-8", errors="ignore")
        total += len(text.encode("utf-8"))
        sections.append(f"[Repository file: {info.filename}]\n{text}")
    if not sections:
        raise ParseError("ZIP contains no safe, supported text files.")
    return ParsedArtifact(sanitize_filename(filename), "repository_zip", "\n\n".join(sections))


def parse_upload(data: bytes, filename: str, settings: Settings) -> ParsedArtifact:
    if len(data) > settings.max_upload_bytes:
        raise ParseError(f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit.")
    suffix = PurePosixPath(filename.casefold()).suffix
    if suffix == ".pdf":
        return parse_pdf(data, filename, settings)
    if suffix in {".md", ".markdown"}:
        return parse_markdown(data, filename)
    if suffix == ".zip":
        return parse_repository_zip(data, filename, settings)
    raise ParseError("Unsupported format. Upload PDF, Markdown, or repository ZIP files.")
