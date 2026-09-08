from datetime import UTC, datetime

from postify.application.content.process_content import ProcessContent
from postify.domain.content.models import AnalysisInput, AnalyzedTopic, BatchAnalysis

NOW = datetime(2026, 9, 5, tzinfo=UTC)

class Attempt:
    id = 7; attempt_no = 1; source_url = ""; title = "Материал"; source_text = "Исходный текст"

class Repository:
    def __init__(self): self.saved = None; self.completed = []
    def active_media_paths(self): return set()
    def claim(self, **kwargs): assert kwargs["batch_size"] == 2; return (Attempt(),)
    def save_extracted(self, attempt_id, article): assert (attempt_id, article.text) == (7, "Исходный текст")
    def fail_attempt(self, *args, **kwargs): raise AssertionError("unexpected failure")
    def save_analysis_and_create_packages(self, batch, *, articles, generation_snapshot, now, context):
        self.saved = (batch, articles, generation_snapshot)
        return (type("Draft", (), {"package_id": 11, "article": articles[7], "media_query": None})(),)
    def complete_package(self, package_id, *, media, status, now): self.completed.append((package_id, media, status))
    def fail_package(self, *args, **kwargs): raise AssertionError("unexpected media failure")

class Analyzer:
    model = "test-model"; provider = "codex"; prompt_version = "v1"
    def analyze(self, inputs, package_limit, brief=None):
        assert tuple(inputs) == (AnalysisInput(7, "", "Материал", "Исходный текст"),)
        assert package_limit == 1
        return BatchAnalysis((AnalyzedTopic(7, "Краткий анализ", 100, "Готовый пост", None),), (7,), 1)

def test_processes_source_text_directly_and_always_creates_review_package():
    repository = Repository()
    result = ProcessContent(repository, Analyzer(), batch_size=2, generation_snapshot={"topic": "Новости"}, clock=lambda: NOW).execute()
    assert result.packages_created == 1
    assert repository.completed == [(11, None, "awaiting_review")]
    assert repository.saved[2] == {"topic": "Новости", "provider": "codex", "model": "test-model", "prompt_version": "v1"}
