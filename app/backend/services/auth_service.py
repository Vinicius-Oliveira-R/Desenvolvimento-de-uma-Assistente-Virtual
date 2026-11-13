from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.core.exceptions import BusinessRuleError, ConflictError, ForbiddenError, UnauthorizedError
from app.backend.core.security import create_access_token, get_password_hash, verify_password
from app.backend.models import Medico, Paciente, Usuario
from app.backend.repositories.medico_repository import MedicoRepository
from app.backend.repositories.paciente_repository import PacienteRepository
from app.backend.repositories.usuario_repository import UsuarioRepository
from app.backend.schemas.usuario import SessaoOut, UsuarioCreate, UsuarioLogin, UsuarioOut


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = UsuarioRepository(db)
        self.pacientes = PacienteRepository(db)
        self.medicos = MedicoRepository(db)

    def register(self, payload: UsuarioCreate, solicitante: Usuario) -> UsuarioOut:
        if not solicitante.papel.pode_cadastrar(payload.papel):
            raise ForbiddenError(f"Seu perfil não pode cadastrar usuários com o papel '{payload.papel}'")
        if self.repository.get_by_email(payload.email):
            raise BusinessRuleError("Email já cadastrado")
        if payload.paciente and self.pacientes.get_by_cpf(payload.paciente.cpf):
            raise ConflictError("Já existe um paciente com este CPF")
        if payload.medico and self.medicos.get_by_crm(payload.medico.crm):
            raise ConflictError("Já existe um médico com este CRM")

        # Usuário e ficha nascem na mesma transação: uma ficha recusada não deixa um usuário órfão para trás.
        try:
            usuario = self.repository.add(
                Usuario(
                    nome=payload.nome,
                    email=str(payload.email).strip().lower(),
                    senha_hash=get_password_hash(payload.senha),
                    papel=payload.papel,
                )
            )
            if payload.paciente:
                self.db.add(Paciente(usuario_id=usuario.id, nome=payload.nome, **payload.paciente.model_dump()))
            if payload.medico:
                self.db.add(Medico(nome=payload.nome, usuario_id=usuario.id, **payload.medico.model_dump()))
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("E-mail, CPF ou CRM já cadastrado") from exc
        return UsuarioOut.model_validate(usuario)

    def login(self, payload: UsuarioLogin) -> SessaoOut:
        usuario = self.repository.get_by_email(payload.email)
        if not usuario or not usuario.ativo or not verify_password(payload.senha, usuario.senha_hash):
            raise UnauthorizedError("Credenciais inválidas")

        token = create_access_token(str(usuario.id), usuario.token_version)
        return SessaoOut(id=usuario.id, nome=usuario.nome, email=usuario.email, papel=usuario.papel, token=token)
