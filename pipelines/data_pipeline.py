"""PDF -> chunk -> embed -> pgvector (or the zero-Docker numpy store) + build the policy
knowledge graph. Idempotent — chunks are deduped by content hash; re-running is safe.

    python -m pipelines.data_pipeline ingest --source ./data/policies/ --domain claims \
        --rebuild-graph
    python -m pipelines.data_pipeline verify --domain claims
    python -m pipelines.data_pipeline purge  --domain claims

Everything here reads only the rendered PDFs — never testdata/seeds/*.yaml. A production
deployment points --source at real policy documents this code has never seen.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import pdfplumber
import pypdf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.core.settings import Settings, get_settings  # noqa: E402
from app.rag.embeddings import embed_texts  # noqa: E402
from app.rag.graph_builder import (  # noqa: E402
    build_edges_from_annexure_table,
    build_edges_from_chunks,
)
from app.rag.graph_store import PolicyGraphStore  # noqa: E402
from app.rag.vector_store import Chunk, get_vector_store  # noqa: E402

GRAPH_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "domains" / "claims" / "graph_schema.yaml"
)

CLAUSE_MARKER = re.compile(r"\[Clause ([A-Z]{2}-\d+\.\d+)\]")
HANDBOOK_MARKER = re.compile(r"Related to clause ([A-Z]{2}-\d+\.\d+)")

MAX_CHUNK_CHARS = 3200  # ~800 tokens at ~4 chars/token
CHUNK_OVERLAP_CHARS = 480  # ~120 tokens


def _extract_pdf_text(pdf_path: Path) -> str:
    reader = pypdf.PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _split_oversized(text: str) -> list[str]:
    """Recursive-ish character split for any chunk that exceeds the token budget. None of
    this project's clause paragraphs are anywhere near the limit, but real policy wording
    could be, so the split logic is real rather than a stub."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        pieces.append(text[start:end])
        start = end - CHUNK_OVERLAP_CHARS if end < len(text) else end
    return pieces


def chunk_policy_wording(doc_id: str, text: str) -> list[dict[str, Any]]:
    """Splits on the explicit "[Clause XX-N.N]" marker every clause carries."""
    matches = list(CLAUSE_MARKER.finditer(text))
    chunks = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        clause_id = match.group(1)
        for piece in _split_oversized(text[start:end].strip()):
            chunks.append({"doc_id": doc_id, "clause_id": clause_id, "content": piece})
    return chunks


def chunk_member_handbook(doc_id: str, text: str) -> list[dict[str, Any]]:
    """Splits on the "Related to clause XX-N.N" heading each paraphrased paragraph carries."""
    matches = list(HANDBOOK_MARKER.finditer(text))
    chunks = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        clause_id = match.group(1)
        for piece in _split_oversized(text[start:end].strip()):
            chunks.append({"doc_id": doc_id, "clause_id": clause_id, "content": piece})
    return chunks


def extract_annexure_rows(pdf_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                header, *body = table
                for row in body:
                    columns = [h or "" for h in header]
                    values = [v or "" for v in row]
                    rows.append(dict(zip(columns, values, strict=True)))
    return rows


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def graph_pickle_path(settings: Settings) -> Path:
    return Path(settings.documents_dir).parent / "graph" / "claims.gpickle"


def ingest(
    source_dir: Path,
    domain: str,
    rebuild_graph: bool,
    settings: Settings,
    embeddings_client: Any = None,
    graph_llm: Any = None,
) -> dict[str, int]:
    """embeddings_client / graph_llm override the real OpenAI clients — used by tests."""
    wording_chunks = chunk_policy_wording(
        "POL-WORDING", _extract_pdf_text(source_dir / "policy_wording.pdf")
    )
    handbook_chunks = chunk_member_handbook(
        "MEMBER-HANDBOOK", _extract_pdf_text(source_dir / "member_handbook.pdf")
    )
    all_chunks = wording_chunks + handbook_chunks

    contents = [c["content"] for c in all_chunks]
    embeddings = embed_texts(contents, client=embeddings_client)

    vector_store = get_vector_store(settings)
    store_chunks: list[Chunk] = [
        {
            "domain": domain,
            "doc_id": c["doc_id"],
            "clause_id": c["clause_id"],
            "page": None,
            "content": c["content"],
            "content_hash": _content_hash(c["content"]),
            "metadata": {},
        }
        for c in all_chunks
    ]
    inserted = vector_store.upsert(store_chunks, embeddings)

    node_count = edge_count = 0
    if rebuild_graph:
        schema = yaml.safe_load(GRAPH_SCHEMA_PATH.read_text(encoding="utf-8"))
        annexure_rows = extract_annexure_rows(source_dir / "procedure_code_annexure.pdf")
        edges = build_edges_from_annexure_table(annexure_rows)
        edges += build_edges_from_chunks(wording_chunks, schema, llm=graph_llm)

        graph_store = PolicyGraphStore()
        graph_store.add_edges(edges)
        graph_store.save(graph_pickle_path(settings))
        node_count, edge_count = graph_store.node_count(), graph_store.edge_count()

        if settings.vector_backend == "pgvector":
            from app.rag.pgvector_store import PgVectorStore

            assert isinstance(vector_store, PgVectorStore)
            vector_store.mirror_graph_edges(domain, edges)

    return {
        "chunks_inserted": inserted,
        "chunks_total": vector_store.count(domain),
        "graph_nodes": node_count,
        "graph_edges": edge_count,
    }


def verify(domain: str, settings: Settings, embeddings_client: Any = None) -> dict[str, Any]:
    vector_store = get_vector_store(settings)
    chunk_count = vector_store.count(domain)

    graph_store = PolicyGraphStore()
    node_count = edge_count = 0
    sample_hit = None
    graph_path = graph_pickle_path(settings)
    if graph_path.exists():
        graph_store.load(graph_path)
        node_count, edge_count = graph_store.node_count(), graph_store.edge_count()

    if chunk_count:
        sample_embedding = embed_texts(
            ["outpatient consultation sub-limit"], client=embeddings_client
        )[0]
        hits = vector_store.similarity_search(sample_embedding, top_k=1, domain=domain)
        sample_hit = hits[0]["clause_id"] if hits else None

    return {
        "chunk_count": chunk_count,
        "graph_nodes": node_count,
        "graph_edges": edge_count,
        "sample_similarity_hit": sample_hit,
    }


def purge(domain: str, settings: Settings) -> None:
    get_vector_store(settings).purge(domain)
    graph_path = graph_pickle_path(settings)
    if graph_path.exists():
        graph_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m pipelines.data_pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--source", required=True)
    ingest_parser.add_argument("--domain", default="claims")
    ingest_parser.add_argument("--rebuild-graph", action="store_true")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--domain", default="claims")

    purge_parser = subparsers.add_parser("purge")
    purge_parser.add_argument("--domain", default="claims")

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "ingest":
        result = ingest(Path(args.source), args.domain, args.rebuild_graph, settings)
        print(result)
    elif args.command == "verify":
        print(verify(args.domain, settings))
    elif args.command == "purge":
        purge(args.domain, settings)
        print(f"purged domain '{args.domain}'")


if __name__ == "__main__":
    main()
