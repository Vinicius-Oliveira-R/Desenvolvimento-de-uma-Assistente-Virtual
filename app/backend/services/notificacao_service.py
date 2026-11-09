from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.backend.core.exceptions import ConflictError, HorarioIndisponivelError, NotFoundError
from app.backend.models import Horario, Medico, PapelUsuario, StatusConsulta, Usuario
from app.backend.models.notificacao import Notificacao, StatusNotificacao, TipoNotificacao, agora_utc
from app.backend.repositories.consulta_repository import ConsultaDaAgenda, ConsultaRepository
from app.backend.repositories.horario_repository import HorarioRepository
from app.backend.repositories.notificacao_repository import NotificacaoRepository
from app.backend.schemas.consulta import ConfirmacaoConsulta, ConsultaUpdate
from app.backend.schemas.notificacao import NotificacaoOut, SolicitacaoAlteracao, TipoSolicitacao
from app.backend.services.consulta_service import ConsultaService

TIPO_DA_SOLICITACAO = {
    TipoSolicitacao.REAGENDAMENTO: TipoNotificacao.REAGENDAMENTO_PENDENTE,
    TipoSolicitacao.CANCELAMENTO: TipoNotificacao.CANCELAMENTO_PENDENTE,
}


def _quando(horario: Horario) -> str:
    ano, mes, dia = horario.data.split("-")
    return f"{dia}/{mes}/{ano} às {horario.hora_inicio}"


class NotificacaoService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = NotificacaoRepository(db)
        self.consultas = ConsultaRepository(db)
        self.horarios = HorarioRepository(db)

    def listar_pendentes(self, usuario: Usuario) -> list[NotificacaoOut]:
        return [NotificacaoOut.model_validate(item) for item in self.repository.pendentes_do_usuario(usuario.id)]

    def solicitar(self, consulta_id: int, pedido: SolicitacaoAlteracao, solicitante: Usuario) -> NotificacaoOut:
        consulta, horario, medico, paciente = self._consulta(consulta_id)
        if consulta.status != StatusConsulta.AGENDADA:
            raise ConflictError("Somente consultas agendadas podem ser remarcadas ou canceladas")
        if self.repository.solicitacao_pendente_da_consulta(consulta.id):
            raise ConflictError("Esta consulta já tem um pedido aguardando a resposta do paciente")

        atual = f"sua consulta com {medico.nome} de {_quando(horario)}"
        novo = None
        if pedido.tipo == TipoSolicitacao.REAGENDAMENTO:
            novo = self.horarios.get_by_id(pedido.horario_id)
            if novo is None or not novo.disponivel or novo.id == horario.id:
                raise HorarioIndisponivelError("O novo horário escolhido não está disponível")
            novo_medico = self.db.get(Medico, novo.medico_id)
            mensagem = f"{solicitante.nome} pediu para remarcar {atual} para {_quando(novo)} com {novo_medico.nome}."
        else:
            mensagem = f"{solicitante.nome} pediu para cancelar {atual}."
        if pedido.motivo:
            mensagem = f"{mensagem} Motivo: {pedido.motivo}"

        notificacao = self.repository.add(
            Notificacao(
                usuario_destino_id=paciente.usuario_id,
                consulta_id=consulta.id,
                solicitante_id=solicitante.id,
                horario_novo_id=novo.id if novo else None,
                tipo=TIPO_DA_SOLICITACAO[pedido.tipo],
                mensagem=mensagem,
            )
        )
        self.db.commit()
        return NotificacaoOut.model_validate(notificacao)

    def responder(self, notificacao_id: int, usuario: Usuario, aceitar: bool) -> NotificacaoOut:
        notificacao = self.repository.get_for_update(notificacao_id)
        if notificacao is None or notificacao.usuario_destino_id != usuario.id:
            raise NotFoundError("Notificação não encontrada")
        if notificacao.status != StatusNotificacao.PENDENTE:
            raise ConflictError("Esta notificação já foi respondida")

        if notificacao.e_solicitacao and aceitar:
            self._executar(notificacao)
            notificacao = self.repository.get_for_update(notificacao_id)
        notificacao.status = StatusNotificacao.ACEITO if aceitar else StatusNotificacao.RECUSADO
        notificacao.respondido_em = agora_utc()
        if notificacao.e_solicitacao and notificacao.solicitante_id:
            resposta = "aceitou" if aceitar else "recusou"
            remarcacao = notificacao.tipo == TipoNotificacao.REAGENDAMENTO_PENDENTE
            pedido = "a remarcação" if remarcacao else "o cancelamento"
            inicio = f"{usuario.nome} {resposta} {pedido} da"
            self._avisar([notificacao.solicitante_id], notificacao.consulta_id, inicio)
        self.db.commit()
        return NotificacaoOut.model_validate(notificacao)

    def avisar_equipe_sobre_cancelamento(self, consulta_id: int) -> None:
        _, _, medico, paciente = self._consulta(consulta_id)
        atendentes = [id_ for (id_,) in self.db.query(Usuario.id).filter(Usuario.papel == PapelUsuario.ADMIN)]
        destinos = [*([medico.usuario_id] if medico.usuario_id else []), *atendentes]
        self._avisar(destinos, consulta_id, f"{paciente.nome} cancelou pelo assistente a")
        self.db.commit()

    def avisar_paciente_sobre_alteracao(self, consulta_id: int, solicitante: Usuario, cancelada: bool) -> None:
        paciente = self._consulta(consulta_id)[3]
        acao = "cancelou" if cancelada else "remarcou"
        self._avisar([paciente.usuario_id], consulta_id, f"{solicitante.nome} {acao}, com a sua confirmação, a")
        self.db.commit()

    def _executar(self, notificacao: Notificacao) -> None:
        consultas = ConsultaService(self.db)
        if notificacao.tipo == TipoNotificacao.REAGENDAMENTO_PENDENTE:
            consultas.update(
                notificacao.consulta_id, ConsultaUpdate(horario_id=notificacao.horario_novo_id, confirmado=True)
            )
        else:
            consultas.cancel(notificacao.consulta_id, ConfirmacaoConsulta(confirmado=True))

    def _avisar(self, destinos: Iterable[int], consulta_id: int, inicio: str) -> None:
        _, horario, medico, _ = self._consulta(consulta_id)
        mensagem = f"{inicio} consulta com {medico.nome} de {_quando(horario)}."
        for destino in dict.fromkeys(destinos):
            self.repository.add(
                Notificacao(
                    usuario_destino_id=destino, consulta_id=consulta_id, tipo=TipoNotificacao.AVISO, mensagem=mensagem
                )
            )

    def _consulta(self, consulta_id: int) -> ConsultaDaAgenda:
        linha = self.consultas.get_da_agenda(consulta_id)
        if linha is None:
            raise NotFoundError("Consulta não encontrada")
        return linha
