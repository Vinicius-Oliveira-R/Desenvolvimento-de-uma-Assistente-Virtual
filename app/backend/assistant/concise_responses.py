"""Contador de unidades do estilo passo a passo (meta: até três por resposta).

Cabeçalhos terminados em ":" introduzem a etapa e não contam; abreviações de nomes e datas
não são sentenças. Cada opção numerada conta como uma unidade, mesmo sem ponto final.
"""
import re


def response_units(text: str) -> int:
    text = re.sub(r"\b(Dr|Dra|Sr|Sra)\.", r"\1", text, flags=re.I)
    units = 0
    for line in text.splitlines():
        if re.match(r"^\d+[).]\s", line):
            units += 1
        elif line.strip() and not line.rstrip().endswith(":"):
            units += max(1, len(re.findall(r"[.!?]+(?:\s|$)", line)))
    return units
