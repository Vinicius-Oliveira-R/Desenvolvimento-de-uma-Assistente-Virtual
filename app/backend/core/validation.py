"""Validações sintáticas; não comprovam titularidade ou registro profissional."""
import re
from datetime import date


def normalize_cpf(value: str) -> str:
    if not isinstance(value, str) or re.search(r"[^0-9.\-\s]", value):
        raise ValueError("CPF deve conter onze dígitos")
    digits = re.sub(r"[.\-\s]", "", value)
    if len(digits) != 11 or not digits.isascii() or not digits.isdigit() or len(set(digits)) == 1:
        raise ValueError("CPF inválido")
    base = digits[:9]
    for size in (10, 11):
        total = sum(int(digit) * weight for digit, weight in zip(base, range(size, 1, -1)))
        base += str((total * 10 % 11) % 10)
    if digits != base:
        raise ValueError("Dígitos verificadores do CPF inválidos")
    return digits


def normalize_phone(value: str) -> str:
    if not isinstance(value, str) or re.search(r"[^0-9+()\-\s]", value):
        raise ValueError("Telefone inválido")
    digits = re.sub(r"[^0-9]", "", value)
    if not 10 <= len(digits) <= 15:
        raise ValueError("Informe telefone com DDD, entre 10 e 15 dígitos")
    return digits


def normalize_birth_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed > date.today():
        raise ValueError("Data de nascimento não pode estar no futuro")
    return parsed.isoformat()
