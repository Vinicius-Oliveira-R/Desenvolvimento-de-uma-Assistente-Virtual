from sqlalchemy.orm import Session

from app.backend.models import Horario


class HorarioRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, horario: Horario) -> Horario:
        self.db.add(horario)
        self.db.commit()
        self.db.refresh(horario)
        return horario

    def list_all(self) -> list[Horario]:
        return self.db.query(Horario).all()

    def get_by_id(self, horario_id: int) -> Horario | None:
        return self.db.query(Horario).filter(Horario.id == horario_id).first()
