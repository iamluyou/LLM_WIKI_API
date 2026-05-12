"""测试 language_guard 和 language 规则"""

import pytest
from app.safety.language_guard import detect_script_family, content_matches_target_language
from app.prompts.language import language_rule


class TestDetectScriptFamily:
    def test_chinese(self):
        assert detect_script_family("这是一段中文文本") == "cjk"

    def test_english(self):
        assert detect_script_family("This is English text") == "latin"

    def test_arabic(self):
        assert detect_script_family("هذا نص عربي") == "arabic"

    def test_cyrillic(self):
        assert detect_script_family("Это русский текст") == "cyrillic"

    def test_mixed_cjk_dominant(self):
        assert detect_script_family("这段文本里有很多中文和少量English") == "cjk"

    def test_mixed_latin_dominant(self):
        assert detect_script_family("Some English with 少量中文") == "latin"

    def test_empty_returns_other(self):
        assert detect_script_family("   ") == "other"

    def test_numbers_only_returns_other(self):
        assert detect_script_family("12345") == "other"


class TestContentMatchesTargetLanguage:
    def test_chinese_content_chinese_target(self):
        content = "---\ntitle: 测试\n---\n这是一段中文内容"
        assert content_matches_target_language(content, "Chinese") is True

    def test_english_content_chinese_target(self):
        content = "---\ntitle: Test\n---\nThis is English content"
        assert content_matches_target_language(content, "Chinese") is False

    def test_english_content_english_target(self):
        content = "---\ntitle: Test\n---\nThis is English content"
        assert content_matches_target_language(content, "English") is True

    def test_strips_code_blocks(self):
        content = "---\n---\n中文文本\n```python\nprint('hello')\n```\n更多中文"
        assert content_matches_target_language(content, "Chinese") is True

    def test_strips_math_blocks(self):
        content = "---\n---\n中文文本\n$$E=mc^2$$\n更多中文"
        assert content_matches_target_language(content, "Chinese") is True

    def test_empty_body_passes(self):
        content = "---\ntitle: Test\n---\n"
        assert content_matches_target_language(content, "Chinese") is True

    def test_unknown_target_passes(self):
        content = "---\n---\nWhatever language"
        assert content_matches_target_language(content, "Klingon") is True


class TestLanguageRule:
    def test_chinese(self):
        rule = language_rule(target_lang="Chinese")
        assert "Chinese (中文)" in rule
        assert "MANDATORY OUTPUT LANGUAGE" in rule

    def test_english(self):
        rule = language_rule(target_lang="English")
        assert "English" in rule

    def test_unknown_language_uses_raw(self):
        rule = language_rule(target_lang="Klingon")
        assert "Klingon" in rule

    def test_case_insensitive(self):
        rule = language_rule(target_lang="chinese")
        assert "Chinese (中文)" in rule
