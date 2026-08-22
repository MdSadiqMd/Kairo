from __future__ import annotations

from kairo_ml.rag.chunker import Chunk
from kairo_ml.rag.contextualize import TemplateContextualizer
from kairo_ml.rag.rerank import HeuristicReranker


def _chunk(chunk_id: str, text: str, path: tuple[str, ...]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        doc_id="d",
        doc_title="Router Design",
        heading_path=path,
    )


def test_template_contextualizer_includes_title_and_path() -> None:
    chunk = _chunk("d::0", "The router hashes a stable prefix key.", ("Router Design", "Routing"))
    context = TemplateContextualizer().contextualize(chunk)
    assert "Document: Router Design" in context
    assert "Section: Router Design > Routing" in context
    assert "Summary:" in context


def test_template_contextualizer_handles_no_heading() -> None:
    chunk = _chunk("d::0", "Body only.", ())
    context = TemplateContextualizer().contextualize(chunk)
    assert "Section:" not in context
    assert "Document: Router Design" in context


def test_heuristic_reranker_orders_by_term_coverage() -> None:
    candidates = [
        _chunk("c1", "unrelated content about baking bread and flour", ()),
        _chunk("c2", "consistent hashing routes prefixes to the same replica cache", ()),
    ]
    ranked = HeuristicReranker().rerank("consistent hashing replica cache", candidates, top_k=2)
    assert ranked[0][0].chunk_id == "c2"
    assert ranked[0][1] > ranked[1][1]


def test_heuristic_reranker_respects_top_k() -> None:
    candidates = [_chunk(f"c{i}", f"term{i} routing cache", ()) for i in range(5)]
    ranked = HeuristicReranker().rerank("routing cache", candidates, top_k=2)
    assert len(ranked) == 2
