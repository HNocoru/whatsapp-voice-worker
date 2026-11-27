"""Cómo se obtiene el `call_id` del despacho (W2 de docs/02-architecture.md §8: POR VERIFICAR).

Todavía no se sabe cómo lo expone el Connector de WhatsApp de LiveKit, así que se aceptan las dos
vías del contrato, con esta prioridad (la primera que traiga un valor gana):

1. metadata del job: JSON `{"call_id": "..."}`.
2. atributo del participante: `call_id`.

La primera prueba con una llamada real decide cuál sobra.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping

logger = logging.getLogger(__name__)

ATTRIBUTE_NAME = "call_id"
CONTEXT_KEY = "context"  # snapshot del contexto que la app mete en la metadata del job


class MissingCallIdError(Exception):
    """El despacho no trajo un `call_id` utilizable; no hay dónde registrar la llamada."""


def _valid(value: object) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


def resolve_call_id(job_metadata: str | None, participant_attributes: Mapping[str, str]) -> str:
    if job_metadata and job_metadata.strip():
        try:
            data = json.loads(job_metadata)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and (found := _valid(data.get(ATTRIBUTE_NAME))):
            return found
    if found := _valid(participant_attributes.get(ATTRIBUTE_NAME)):
        return found
    msg = "no hay call_id (UUID) ni en la metadata del job ni en los atributos del participante"
    raise MissingCallIdError(msg)


def resolve_context(
    job_metadata: str | None, expected_call_id: str | None = None
) -> dict[str, object] | None:
    """Snapshot del contexto en la metadata del job (`{"call_id", "context": {...}}`), o None.

    Solo se acepta si `context` es un objeto con `business` objeto; si no, se usa el GET.
    Si el `call_id` del snapshot no coincide con el resuelto se ignora (aviso sin contenido).
    """
    if not job_metadata or not job_metadata.strip():
        return None
    try:
        data = json.loads(job_metadata)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    ctx = data.get(CONTEXT_KEY)
    if not (isinstance(ctx, dict) and isinstance(ctx.get("business"), dict)):
        return None
    snapshot_id = _valid(data.get(ATTRIBUTE_NAME))
    if expected_call_id is not None and snapshot_id != expected_call_id:
        logger.warning("el snapshot de la metadata no coincide con el call_id; se usa el GET")
        return None
    return ctx
