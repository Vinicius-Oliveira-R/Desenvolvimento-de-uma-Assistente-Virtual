import os
from app.backend.core.database import SessionLocal
from app.backend.core.security import get_password_hash
from app.backend.models import PapelUsuario, Usuario

email = os.environ.get("GESTOR_EMAIL", "viniciusoliveira12353@gmail.com")
senha = os.environ.get("GESTOR_SENHA", "785421369")

with SessionLocal() as db:
    usuario = db.query(Usuario).filter(Usuario.email == email).first()

    if usuario is None:
        usuario = Usuario(
            nome="Gestor da Clínica",
            email=email,
            senha_hash=get_password_hash(senha),
            papel=PapelUsuario.GESTOR,
        )
        db.add(usuario)
    else:
        usuario.senha_hash = get_password_hash(senha)
        usuario.papel = PapelUsuario.GESTOR

    db.commit()

print(f"Gestor configurado com sucesso: {email}")