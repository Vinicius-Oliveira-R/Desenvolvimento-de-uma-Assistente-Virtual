from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.dependencies import get_current_user, require_gestor
from app.backend.core.exceptions import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.backend.core.validation import normalize_phone
from app.backend.models import Medico, Paciente, PapelUsuario, Usuario

router = APIRouter(prefix="/cadastros", tags=["cadastros"])


class ContatoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr | None = None
    telefone: str | None = None

    @field_validator("telefone")
    @classmethod
    def telefone_valido(cls, value: str | None) -> str | None:
        return normalize_phone(value) if value is not None else None


class Ativacao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ativo: bool


class MedicoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str | None = Field(default=None, min_length=2, max_length=150)
    crm: str | None = Field(default=None, min_length=3, max_length=30)
    especialidade: str | None = Field(default=None, min_length=2, max_length=100)
    ativo: bool | None = None


def _paciente(db: Session, usuario: Usuario, paciente_id: int | None = None) -> Paciente:
    query = select(Paciente)
    query = query.where(Paciente.usuario_id == usuario.id) if paciente_id is None else query.where(Paciente.id == paciente_id)
    paciente = db.execute(query.with_for_update()).scalar_one_or_none()
    if paciente is None:
        raise NotFoundError("Cadastro de paciente não encontrado")
    if usuario.papel not in (PapelUsuario.ADMIN, PapelUsuario.MEDICO) and paciente.usuario_id != usuario.id:
        raise ForbiddenError("Sem permissão para alterar esse cadastro")
    return paciente


def _contato(paciente: Paciente) -> dict:
    return {"id": paciente.id, "nome": paciente.nome, "email": paciente.usuario.email, "telefone": paciente.telefone}


def _update_contact(db: Session, paciente: Paciente, payload: ContatoUpdate) -> dict:
    try:
        if payload.email is not None:
            email = str(payload.email).strip().lower()
            exists = db.query(Usuario.id).filter(func.lower(Usuario.email) == email, Usuario.id != paciente.usuario_id).first()
            if exists:
                raise ConflictError("E-mail já cadastrado")
            paciente.usuario.email = email
        if payload.telefone is not None:
            paciente.telefone = payload.telefone
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("E-mail já cadastrado") from exc
    except Exception:
        db.rollback()
        raise
    return _contato(paciente)


@router.get("/pacientes/me")
def my_contact(usuario: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _contato(_paciente(db, usuario))


@router.patch("/pacientes/me")
def update_my_contact(payload: ContatoUpdate, usuario: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _update_contact(db, _paciente(db, usuario), payload)


@router.get("/pacientes/{paciente_id}")
def get_contact(paciente_id: int, usuario: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _contato(_paciente(db, usuario, paciente_id))


@router.patch("/pacientes/{paciente_id}")
def update_contact(paciente_id: int, payload: ContatoUpdate, usuario: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _update_contact(db, _paciente(db, usuario, paciente_id), payload)


@router.patch("/usuarios/{usuario_id}/ativo")
def set_user_active(usuario_id: int, payload: Ativacao, actor: Usuario = Depends(require_gestor), db: Session = Depends(get_db)) -> dict:
    target = db.execute(select(Usuario).where(Usuario.id == usuario_id).with_for_update()).scalar_one_or_none()
    if target is None:
        raise NotFoundError("Usuário não encontrado")
    if target.papel == PapelUsuario.GESTOR:
        raise BusinessRuleError("Gestores não podem ser desativados por essa operação")
    if target.ativo != payload.ativo:
        target.ativo = payload.ativo
        target.token_version += 1
    db.commit()
    return {"id": target.id, "ativo": target.ativo}


@router.patch("/medicos/{medico_id}")
def update_doctor(medico_id: int, payload: MedicoUpdate, actor: Usuario = Depends(require_gestor), db: Session = Depends(get_db)) -> dict:
    medico = db.execute(select(Medico).where(Medico.id == medico_id).with_for_update()).scalar_one_or_none()
    if medico is None:
        raise NotFoundError("Médico não encontrado")
    try:
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(medico, key, value)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("CRM já cadastrado") from exc
    return {"id": medico.id, "nome": medico.nome, "crm": medico.crm, "especialidade": medico.especialidade, "ativo": medico.ativo}
