"""全局测试夹具"""

import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def _disable_api_key():
    """测试时清空 API_KEY，跳过认证校验"""
    original = settings.api_key
    settings.api_key = ""
    yield
    settings.api_key = original
