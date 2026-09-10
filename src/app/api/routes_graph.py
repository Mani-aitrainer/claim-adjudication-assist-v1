"""GET /v1/graph/subgraph — teaching endpoint: shows exactly what PolicyAdjudicatorAgent
retrieved from the policy knowledge graph for a given set of codes.
"""

from fastapi import APIRouter, Request

from app.api.schemas import SubgraphResponse

router = APIRouter(prefix="/v1/graph", tags=["graph"])


@router.get("/subgraph")
async def get_subgraph(request: Request, codes: str, hops: int = 2) -> SubgraphResponse:
    graph_store = request.app.state.graph_store
    seed_codes = [c.strip() for c in codes.split(",") if c.strip()]
    triples = graph_store.ego_subgraph_triples(seed_codes, hops)
    return SubgraphResponse(seed_codes=seed_codes, hops=hops, triples=triples)
