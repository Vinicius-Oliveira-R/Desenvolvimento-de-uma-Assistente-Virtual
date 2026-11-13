from sqlalchemy.orm import Session

from app.backend.models import Medico, Usuario


class MedicoRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, medico: Medico) -> Medico:
        self.db.add(medico)
        self.db.commit()
        self.db.refresh(medico)
        return medico

    def list_all(self) -> list[Medico]:
        return self.db.query(Medico).all()

    def list_active(self) -> list[Medico]:
        return self.db.query(Medico).filter(Medico.ativo.is_(True)).filter(
            (Medico.usuario_id.is_(None)) | Medico.usuario.has(Usuario.ativo.is_(True))
        ).all()

    def get_by_id(self, medico_id: int) -> Medico | None:
        return self.db.query(Medico).filter(Medico.id == medico_id).first()

    def get_by_crm(self, crm: str) -> Medico | None:
        return self.db.query(Medico).filter(Medico.crm == crm).first()
