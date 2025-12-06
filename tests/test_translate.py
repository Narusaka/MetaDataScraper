import pytest
from unittest.mock import Mock, patch
from src.core.translator import Translator


def test_translator_init():
    """Test translator initialization."""
    config = {
        "base_url": "http://localhost:8000",
        "api_key": "test",
        "model": "test-model"
    }
    translator = Translator(config)
    assert translator.model_config == config


@patch('src.core.translator.requests.Session')
def test_translate_metadata_no_fields(mock_session):
    """Test translation when no fields need translation."""
    config = {
        "base_url": "http://localhost:8000",
        "api_key": "test",
        "model": "test-model"
    }

    translator = Translator(config)
    data = {
        "title": "Test Movie",
        "title_zh": "测试电影",
        "plot": "Test plot",
        "plot_zh": "测试剧情"
    }

    result = translator.translate_metadata(data)
    assert result == data  # Should return unchanged


@patch('src.core.translator.requests.Session')
def test_translate_metadata_with_fields(mock_session):
    """Test translation with missing Chinese fields."""
    # Mock the LLM response
    mock_response = Mock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"title": "测试电影"}'}}]
    }
    mock_session.return_value.post.return_value = mock_response

    config = {
        "base_url": "http://localhost:8000",
        "api_key": "test",
        "model": "test-model"
    }

    translator = Translator(config)
    data = {
        "title": "Test Movie",
        "plot": "Test plot"
    }

    result = translator.translate_metadata(data)
    assert result["title_zh"] == "测试电影"
    mock_session.return_value.post.assert_called_once()
