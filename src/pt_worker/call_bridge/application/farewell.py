"""Detecta si el cliente se despide, para que el asistente cuelgue solo tras responder.

Se decide por la transcripción (no por una herramienta del modelo): no depende de cómo el motor S2S
maneje las tools. Es una lista corta y conservadora de despedidas en español de México; ante la duda
no es despedida (colgar de más es peor que esperar al tope de 300 s).
"""

from __future__ import annotations

import re
import unicodedata

MAX_WORDS = 8  # una despedida es corta; una frase larga con "adiós" en medio no cuenta
_ANYWHERE = re.compile(r"\b(adios|hasta luego|bye|ya es todo|gracias es todo)\b")
_AT_END = re.compile(r"\bnada mas$")  # "nada más el precio" no es despedida


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", plain).split())


def is_farewell(text: str) -> bool:
    if "?" in text or "¿" in text:
        return False
    norm = _normalize(text)
    if not norm or len(norm.split()) > MAX_WORDS:
        return False
    return bool(_ANYWHERE.search(norm) or _AT_END.search(norm))
