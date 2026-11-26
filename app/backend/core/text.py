import re
import unicodedata

_FORA_DE_PALAVRA = re.compile(r"[^\w\s:/]")
_ESPACOS = re.compile(r"\s+")
_CORTESIA_FINAL = re.compile(r"(?:\s+(?:por favor|pfv|pf|obrigad[oa]|obg|valeu|grat[oa]))+$")


def normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(caractere for caractere in decomposto if not unicodedata.combining(caractere))


def normalizar_frase(texto: str) -> str:
    """Minúsculas, sem acento, sem pontuação e sem cortesia final: "Sim, por favor!" -> "sim"."""
    base = _ESPACOS.sub(" ", _FORA_DE_PALAVRA.sub(" ", normalizar(texto))).strip()
    return _CORTESIA_FINAL.sub("", base).strip()
