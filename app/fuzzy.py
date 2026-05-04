import unicodedata
import re
from rapidfuzz import process, fuzz
from .models import Medico


def _normalizar(texto: str) -> str:
    """Remove acentos, prefixos como 'dr', 'dra' e normaliza espaços."""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.lower()
    texto = re.sub(r"\bdr[a]?\b\.?", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def buscar_medico(nome_digitado: str) -> Medico | None:
    """Retorna o Medico mais próximo pelo nome ou None se nenhum passar o limiar."""
    medicos = Medico.query.filter_by(ativo=True).all()
    if not medicos:
        return None

    candidatos = {m.id: _normalizar(m.nome) for m in medicos}
    alvo = _normalizar(nome_digitado)

    resultado = process.extractOne(
        alvo, candidatos, scorer=fuzz.token_sort_ratio
    )
    if resultado is None:
        return None

    _match_nome, score, medico_id = resultado
    if score >= 60:
        return next(m for m in medicos if m.id == medico_id)
    return None
