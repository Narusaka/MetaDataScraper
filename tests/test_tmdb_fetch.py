import pytest
from unittest.mock import Mock, patch
from src.adapters.tmdb import TMDBAdapter


def test_tmdb_adapter_init():
    """Test TMDB adapter initialization."""
    adapter = TMDBAdapter("test_key", {"http": "proxy"})
    assert adapter.api_key == "test_key"
    assert adapter.proxy == {"http": "proxy"}


@patch('src.adapters.tmdb.requests.Session')
def test_tmdb_search_movie(mock_session):
    """Test movie search."""
    # Mock the session and response
    mock_response = Mock()
    mock_response.json.return_value = {"results": [{"id": 1, "title": "Test Movie"}]}
    mock_session.return_value.get.return_value = mock_response

    adapter = TMDBAdapter("test_key")
    result = adapter.search_movie("Test Movie")

    assert result["results"][0]["title"] == "Test Movie"
    mock_session.return_value.get.assert_called_once()


@patch('src.adapters.tmdb.requests.Session')
def test_tmdb_get_movie_details(mock_session):
    """Test getting movie details."""
    # Mock the session and response
    mock_response = Mock()
    mock_response.json.return_value = {"id": 1, "title": "Test Movie"}
    mock_session.return_value.get.return_value = mock_response

    adapter = TMDBAdapter("test_key")
    result = adapter.get_movie_details(1)

    assert result["title"] == "Test Movie"
    mock_session.return_value.get.assert_called_once()
