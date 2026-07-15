"""Per-business knowledge base for RAG-grounded campaign generation.

Owners (or an onboarding flow) add short snippets — services offered, brand
voice notes, past high-performing campaigns — that get embedded and retrieved
into the campaign prompt (app/campaigns/generator.py) so AI copy reflects the
actual business instead of a generic template.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text, Uuid
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.models.mixins import UUIDMixin


# Base tables are also created against in-memory SQLite in tests
# (see tests/test_ingest.py); pgvector has no SQLite type, so give
# create_all a stand-in there. Never queried under that dialect.
@compiles(Vector, "sqlite")
def _compile_vector_sqlite(element, compiler, **kw):  # noqa: ARG001
    return "BLOB"


KNOWLEDGE_KINDS = ("service", "brand_voice", "campaign_example", "note")


class BusinessKnowledge(UUIDMixin, Base):
    __tablename__ = "business_knowledge"

    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="note")
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dimensions))
