"""Text embeddings via AWS Bedrock (Cohere Embed v4).

boto3 has no native asyncio support, so calls run in a worker thread. Cohere's
Bedrock API wants ``input_type`` set differently for stored documents vs. search
queries — using the wrong one measurably hurts retrieval quality, so callers
must say which they mean rather than defaulting one way.
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from typing import Literal

import boto3
from botocore.config import Config

from app.core.config import settings

logger = logging.getLogger("pulse.rag.embeddings")

InputType = Literal["search_document", "search_query"]


class EmbeddingError(Exception):
    """Raised when Bedrock couldn't return embeddings."""


@lru_cache(maxsize=1)
def _client():
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.bedrock_region,
        config=Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 2}),
    )


def _invoke(texts: list[str], input_type: InputType) -> list[list[float]]:
    body = json.dumps({"texts": texts, "input_type": input_type})
    response = _client().invoke_model(
        modelId=settings.bedrock_embedding_model,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    data = json.loads(response["body"].read())
    try:
        vectors = data["embeddings"]["float"]
    except (KeyError, TypeError) as exc:
        raise EmbeddingError(f"Unexpected Bedrock embeddings response: {data}") from exc
    if len(vectors) != len(texts):
        raise EmbeddingError(f"Expected {len(texts)} embeddings, got {len(vectors)}")
    return vectors


async def embed_texts(texts: list[str], *, input_type: InputType) -> list[list[float]]:
    """Embed a batch of strings. Raises EmbeddingError on any failure — callers
    decide whether that should block (storing knowledge) or degrade (retrieval)."""
    if not texts:
        return []
    try:
        return await asyncio.to_thread(_invoke, texts, input_type)
    except EmbeddingError:
        raise
    except Exception as exc:  # botocore ClientError, network, etc.
        raise EmbeddingError(f"Bedrock embeddings request failed: {exc}") from exc


async def embed_query(text: str) -> list[float]:
    vectors = await embed_texts([text], input_type="search_query")
    return vectors[0]
