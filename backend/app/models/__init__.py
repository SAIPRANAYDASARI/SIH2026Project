"""ORM models.

Import every model module here so `Base.metadata` is fully populated before
Alembic's `env.py` uses it for autogenerate, and before the app creates any
tables. Adding a new model module without importing it here is the most
common way autogenerate silently produces an empty migration — don't do that.
"""

from app.models.audit import AuditLogEntry
from app.models.certification import Scheme
from app.models.conversation import Conversation, Message
from app.models.document import Chunk, Document
from app.models.standard import Standard
from app.models.verification import Licence

__all__ = [
    "AuditLogEntry",
    "Scheme",
    "Conversation",
    "Message",
    "Chunk",
    "Document",
    "Standard",
    "Licence",
]
