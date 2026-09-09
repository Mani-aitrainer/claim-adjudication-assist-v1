"""text-embedding-3-small, batched per config/agents.yaml[agents.embedding]."""

from functools import cache

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.core.agent_config import get_agent_config
from app.core.settings import get_settings


@cache
def get_embeddings_client() -> OpenAIEmbeddings:
    config = get_agent_config("embedding")
    settings = get_settings()
    dimensions = (config.model_extra or {}).get("dimensions")
    api_key = SecretStr(settings.openai_api_key) if settings.openai_api_key else None
    return OpenAIEmbeddings(model=config.model, dimensions=dimensions, openai_api_key=api_key)


def embed_texts(texts: list[str], client: OpenAIEmbeddings | None = None) -> list[list[float]]:
    """Embeds in batches of config/agents.yaml[agents.embedding.batch_size]."""
    config = get_agent_config("embedding")
    batch_size = (config.model_extra or {}).get("batch_size", 64)
    embeddings_client = client if client is not None else get_embeddings_client()

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(embeddings_client.embed_documents(batch))
    return vectors
