import unicodedata


def normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(caractere for caractere in decomposto if not unicodedata.combining(caractere))
