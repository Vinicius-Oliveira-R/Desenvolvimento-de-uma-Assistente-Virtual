"""Criação inicial ou redefinição explícita de gestor, sem usuários de demonstração."""
import argparse
import getpass
import warnings

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.backend.core.database import SessionLocal, engine
from app.backend.core.security import get_password_hash
from app.backend.models import PapelUsuario, Usuario


def configure_manager(db: Session, nome: str, email: str, senha: str, *, reset: bool = False) -> Usuario:
    nome = nome.strip()
    if not 2 <= len(nome) <= 150:
        raise ValueError("Informe um nome entre 2 e 150 caracteres")
    email = validate_email(email.strip(), check_deliverability=False).normalized.lower()
    if len(senha) < 12 or len(senha.encode("utf-8")) > 72:
        raise ValueError("A senha deve ter pelo menos 12 caracteres e no máximo 72 bytes")
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(71029041)"))
    user = db.execute(select(Usuario).where(func.lower(Usuario.email) == email).with_for_update()).scalar_one_or_none()
    if reset:
        if user is None or user.papel != PapelUsuario.GESTOR or not user.ativo:
            raise ValueError("Não existe gestor ativo com esse e-mail; nenhuma conta foi promovida")
        user.senha_hash = get_password_hash(senha)
        user.token_version += 1
    else:
        if user is not None or db.query(Usuario.id).filter(Usuario.papel == PapelUsuario.GESTOR).first():
            raise ValueError("Já existe usuário com esse e-mail ou gestor no banco; nenhuma alteração")
        user = Usuario(nome=nome, email=email, senha_hash=get_password_hash(senha), papel=PapelUsuario.GESTOR)
        db.add(user)
    db.flush()
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redefinir", action="store_true", help="Redefine somente a senha de um gestor ativo existente")
    args = parser.parse_args()
    print("Destino:", engine.url.host or "local", "/", engine.url.database)
    print("Modo:", "REDEFINIR senha e revogar sessões" if args.redefinir else "CRIAR primeiro gestor")
    nome = "Gestor" if args.redefinir else input("Nome completo: ")
    email = input("E-mail do gestor: ")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            senha = getpass.getpass("Nova senha (não aparece): ")
            confirmation = getpass.getpass("Confirme a senha: ")
        except getpass.GetPassWarning:
            raise SystemExit("Use um terminal que permita ocultar a senha") from None
    if senha != confirmation:
        raise SystemExit("As senhas não coincidem")
    phrase = "REDEFINIR GESTOR" if args.redefinir else "CRIAR GESTOR"
    if input(f"Confirme o destino digitando {phrase}: ").strip() != phrase:
        raise SystemExit("Operação cancelada; nenhuma alteração")
    try:
        with SessionLocal() as db:
            try:
                configure_manager(db, nome, email, senha, reset=args.redefinir)
                db.commit()
            except Exception:
                db.rollback()
                raise
    except (ValueError, EmailNotValidError) as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        raise SystemExit("Não foi possível concluir; nenhuma alteração confirmada (" + type(exc).__name__ + ")") from None
    print("Operação concluída; nenhum usuário de demonstração foi criado")


if __name__ == "__main__":
    main()
