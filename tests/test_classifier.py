"""Tests for keyword classifier."""
from briefing.config import InterestsConfig
from briefing.filters.classifier import _compile_keyword_patterns, classify_text


def _patterns(d):
    return _compile_keyword_patterns(d)


def test_word_boundary_match():
    pats = _patterns({"agent": ["agent"]})
    assert classify_text("LLM-based agent for tool use", pats) == ["agent"]
    assert classify_text("management style", pats) == []   # no false "manage[ment]"


def test_case_insensitive_and_hyphen():
    pats = _patterns({"vlm": ["VLM", "vision-language"]})
    assert classify_text("a strong VLM", pats) == ["vlm"]
    assert classify_text("vision-language model", pats) == ["vlm"]


def test_multiple_topics():
    pats = _patterns({
        "rag": ["RAG", "retrieval-augmented"],
        "agent": ["agent"],
        "memory": ["long-term memory"],
    })
    text = "An agent with long-term memory using retrieval-augmented generation"
    assert set(classify_text(text, pats)) == {"rag", "agent", "memory"}
