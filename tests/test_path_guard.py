"""单元测试：路径穿越防护"""

import pytest
from app.safety.path_guard import is_safe_ingest_path, sanitize_path


class TestIsSafeIngestPath:
    def test_valid_wiki_path(self):
        assert is_safe_ingest_path("wiki/entities/test.md") is True
        assert is_safe_ingest_path("wiki/concepts/chain-of-thought.md") is True
        assert is_safe_ingest_path("wiki/index.md") is True

    def test_reject_absolute_path(self):
        assert is_safe_ingest_path("/etc/passwd") is False
        assert is_safe_ingest_path("C:\\Windows\\System32") is False

    def test_reject_path_traversal(self):
        assert is_safe_ingest_path("wiki/../../../etc/passwd") is False
        assert is_safe_ingest_path("wiki/entities/../../secret.md") is False

    def test_reject_non_wiki_prefix(self):
        assert is_safe_ingest_path("raw/sources/test.md") is False
        assert is_safe_ingest_path("etc/passwd") is False

    def test_reject_empty_path(self):
        assert is_safe_ingest_path("") is False

    def test_reject_control_chars(self):
        assert is_safe_ingest_path("wiki/test\x00.md") is False

    def test_reject_windows_device_names(self):
        assert is_safe_ingest_path("wiki/CON.md") is False
        assert is_safe_ingest_path("wiki/entities/AUX.md") is False

    def test_reject_windows_invalid_chars(self):
        assert is_safe_ingest_path('wiki/entities/test<.md') is False
        assert is_safe_ingest_path('wiki/entities/test|.md') is False

    def test_reject_unc_path(self):
        assert is_safe_ingest_path("\\\\server\\share") is False


class TestSanitizePath:
    def test_strip_wiki_prefix(self):
        assert sanitize_path("wiki/entities/test.md") == "entities/test.md"

    def test_no_wiki_prefix(self):
        assert sanitize_path("entities/test.md") == "entities/test.md"

    def test_backslash_normalization(self):
        assert sanitize_path("wiki\\entities\\test.md") == "entities/test.md"
