"""Run one real Gemini extraction + embedding request without persisting content."""
from .ai import AIProviderError, GeminiProvider
from .config import get_settings


def main() -> None:
    settings = get_settings()
    text = "Smoke Test Paper\nAsha Lee studies water-quality prediction using linear regression."
    candidates = list(dict.fromkeys((settings.gemini_model, "gemini-3.5-flash-lite", "gemini-3.6-flash")))
    failures = []
    for model in candidates:
        try:
            provider = GeminiProvider(settings.gemini_api_key, model, settings.gemini_embedding_model)
            graph = provider.extract(text, "smoke.md", "markdown")
            embedding = provider.embed([graph.document.summary])[0]
            print(f"OK model={model} title={graph.document.title!r} embedding_dimensions={len(embedding)}")
            if model != settings.gemini_model:
                print(f"Set GEMINI_MODEL={model} in .env because the configured model did not pass.")
            return
        except AIProviderError as exc:
            failures.append(f"{model}: {exc}")
    raise SystemExit("No Flash candidate passed the smoke test. " + " | ".join(failures))


if __name__ == "__main__":
    main()
