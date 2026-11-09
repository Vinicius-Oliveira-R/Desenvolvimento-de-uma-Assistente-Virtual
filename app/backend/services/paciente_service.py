from sqlalchemy.orm import Session

from app.backend.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.backend.models import Paciente, PapelUsuario
from app.backend.repositories.paciente_repository import PacienteRepository
from app.backend.repositories.usuario_repository import UsuarioRepository
from app.backend.schemas.paciente import PacienteCreate, PacienteOut


class PacienteService:
    def __init__(self, db: Session):
        self.repository = PacienteRepository(db)
        self.usuarios = UsuarioRepository(db)

    def create(self, payload: PacienteCreate) -> PacienteOut:
        usuario = self.usuarios.get_by_id(payload.usuario_id)
        if not usuario:
            raise NotFoundError("Usuário não encontrado")
        if usuario.papel != PapelUsuario.PACIENTE:
            raise BusinessRuleError("O cadastro de paciente deve ser vinculado a um usuário com papel de paciente")
        if self.repository.get_by_usuario_id(usuario.id):
            raise ConflictError("Este usuário já possui cadastro de paciente")
        if self.repository.get_by_cpf(payload.cpf):
            raise ConflictError("Já existe um paciente com este CPF")

        paciente = Paciente(
            usuario_id=usuario.id,
            nome=payload.nome,
            cpf=payload.cpf,
            data_nascimento=payload.data_nascimento,
            telefone=payload.telefone,
        )
        return PacienteOut.model_validate(self.repository.create(paciente))

    def list_all(self) -> list[PacienteOut]:
        return [PacienteOut.model_validate(item) for item in self.repository.list_all()]
