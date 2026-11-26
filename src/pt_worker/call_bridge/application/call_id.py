"""Cómo se obtiene el `call_id` del despacho (W2 de docs/02-architecture.md §8: POR VERIFICAR).

Todavía no se sabe cómo lo expone el Connector de WhatsApp de LiveKit, así que se aceptan las dos
vías del contrato, con esta prioridad (la primera que traiga un valor gana):

1. metadata del job: JSON `{"call_id": "..."}`.
2. atributo del participante: `call_id`.

La primera prueba con una llamada real decide cuál sobra.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

ATTRIBUTE_NAME = "call_id"


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
