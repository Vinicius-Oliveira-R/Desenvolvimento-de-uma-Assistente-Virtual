from sqlalchemy.orm import Session

from app.models import Consulta


class ConsultaRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, consulta: Consulta) -> Consulta:
        self.db.add(consulta)
        self.db.commit()
        self.db.refresh(consulta)
        return consulta

    def list_all(self) -> list[Consulta]:
        return self.db.query(Consulta).all()

    def get_by_id(self, consulta_id: int) -> Consulta | None:
        return self.db.query(Consulta).filter(Consulta.id == consulta_id).first()

    def update(self, consulta: Consulta) -> Consulta:
        self.db.commit()
        self.db.refresh(consulta)
        return consulta

    def delete(self, consulta: Consulta) -> None:
        self.db.delete(consulta)
        self.db.commit()
