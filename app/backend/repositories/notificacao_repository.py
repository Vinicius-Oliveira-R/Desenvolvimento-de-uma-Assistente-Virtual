from collections.abc import Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.backend.models import Consulta, StatusConsulta
from app.backend.models.notificacao import SOLICITACOES, Notificacao, StatusNotificacao, TipoNotificacao


class NotificacaoRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, notificacao: Notificacao) -> Notificacao:
        self.db.add(notificacao)
        self.db.flush()
        return notificacao

    def get_for_update(self, notificacao_id: int) -> Notificacao | None:
        return (
            self.db.query(Notificacao)
            .filter(Notificacao.id == notificacao_id)
            .with_for_update()
            .populate_existing()
            .first()
        )

    def pendentes_do_usuario(self, usuario_id: int) -> list[Notificacao]:
        query = self._pendentes().filter(Notificacao.usuario_destino_id == usuario_id)
        return query.order_by(Notificacao.id.desc()).all()

    def proxima_solicitacao(self, usuario_id: int, ignorar: Sequence[int] = ()) -> Notificacao | None:
        query = self._pendentes().filter(
            Notificacao.usuario_destino_id == usuario_id, Notificacao.tipo.in_(SOLICITACOES)
        )
        if ignorar:
            query = query.filter(Notificacao.id.notin_(ignorar))
        return query.order_by(Notificacao.id).first()

    def solicitacao_pendente_da_consulta(self, consulta_id: int) -> Notificacao | None:
        return (
            self._pendentes()
            .filter(Notificacao.consulta_id == consulta_id, Notificacao.tipo.in_(SOLICITACOES))
            .first()
        )

    def solicitacoes_pendentes_por_consulta(self, consulta_ids: Sequence[int]) -> dict[int, str]:
        if not consulta_ids:
            return {}
        pendentes = (
            self._pendentes()
            .filter(Notificacao.consulta_id.in_(consulta_ids), Notificacao.tipo.in_(SOLICITACOES))
            .all()
        )
        return {notificacao.consulta_id: notificacao.tipo for notificacao in pendentes}

    def _pendentes(self) -> Query:
        # Pedido sobre consulta que já deixou de estar agendada não tem mais o que confirmar.
        return (
            self.db.query(Notificacao)
            .join(Consulta, Notificacao.consulta_id == Consulta.id)
            .filter(
                Notificacao.status == StatusNotificacao.PENDENTE,
                or_(Notificacao.tipo == TipoNotificacao.AVISO, Consulta.status == StatusConsulta.AGENDADA),
            )
        )
