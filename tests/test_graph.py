import pytest
from src.app.graph import MediaMetadataGraph
from src.app.state import GraphState


def test_graph_creation():
    """Test that the graph can be created."""
    config = {
        "tmdb": {"api_key": "test"},
        "omdb": {"api_key": "test"},
        "model": {
            "base_url": "http://localhost:8000",
            "api_key": "test",
            "model": "test"
        }
    }

    graph_builder = MediaMetadataGraph(config)
    workflow = graph_builder.create_graph()

    assert workflow is not None


def test_parse_input_node():
    """Test input parsing."""
    config = {
        "tmdb": {"api_key": "test"},
        "omdb": {"api_key": "test"},
        "model": {"base_url": "http://localhost:8000", "api_key": "test", "model": "test"}
    }

    graph_builder = MediaMetadataGraph(config)
    state = GraphState(
        input={"media_type": "movie", "query": "test"},
        search={}, source_data={}, normalized={}, artwork={}, nfo={}, output={}, errors={}
    )

    result = graph_builder.parse_input_node(state)
    assert result["input"]["media_type"] == "movie"
    assert result["input"]["query"] == "test"
