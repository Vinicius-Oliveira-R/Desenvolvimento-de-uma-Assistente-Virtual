"""Consultas já marcadas: identificar qual, escolher entre mudar ou desmarcar, confirmar."""
from dataclasses import replace

from app.backend.assistant.dialogue import Preambulo, ResultadoDialogo, TipoResultado
from app.backend.assistant.nlp import Entidades, Intencao
from app.backend.assistant.replies import TipoLeitura
from app.backend.assistant.temporal import IntervaloDatas
from app.backend.core.text import normalizar_frase
from app.backend.schemas.assistant import AcaoPendente, Pergunta, TipoAcao

_MUDAR = frozenset({
    "mudar", "muda", "mude", "trocar", "troca", "remarcar", "remarca", "mudar o horario", "mudar horario",
    "mudar a data", "mudar o dia", "trocar o horario", "trocar o dia", "outro horario", "outro dia",
})
_DESMARCAR = frozenset({"desmarcar", "desmarca", "cancelar", "cancela", "desmarcar esta", "desmarcar essa"})


class GerenciamentoDeConsultas:
    def gerenciar(self, paciente) -> ResultadoDialogo:
        consultas = self._consultas_futuras(paciente)
        if not consultas:
            return ResultadoDialogo(TipoResultado.SEM_CONSULTAS)
        if len(consultas) == 1:
            return self._escolher_acao(paciente, consultas[0].consulta_id)
        lote = consultas[:self.page_size]
        return ResultadoDialogo(
            TipoResultado.GERENCIAR_CONSULTAS, opcoes=tuple(lote),
            acao_pendente=AcaoPendente(tipo=TipoAcao.GERENCIAR, consultas_oferecidas=[c.consulta_id for c in lote]),
        )

    def solicitar_cancelamento(self, paciente, entidades: Entidades) -> ResultadoDialogo:
        candidatas = self._filtrar(self._consultas_futuras(paciente), entidades)
        if not candidatas:
            referencia = IntervaloDatas(entidades.data, entidades.data) if entidades.data else entidades.periodo
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA, periodo=referencia)
        if len(candidatas) > 1:
            lote = candidatas[:self.page_size]
            return ResultadoDialogo(
                TipoResultado.CANCELAMENTO_AMBIGUO, opcoes=tuple(lote),
                acao_pendente=AcaoPendente(tipo=TipoAcao.CANCELAR, consultas_oferecidas=[c.consulta_id for c in lote]),
            )
        return self._confirmar_cancelamento_de(paciente, candidatas[0].consulta_id)

    def _confirmar_cancelamento_de(self, paciente, consulta_id: int | None) -> ResultadoDialogo:
        opcao = self._consulta_do_paciente(paciente, consulta_id)
        if opcao is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        return ResultadoDialogo(
            TipoResultado.CONFIRMAR_CANCELAMENTO, opcao=opcao,
            acao_pendente=AcaoPendente(
                tipo=TipoAcao.CANCELAR, consulta_id=opcao.consulta_id, origem_horario_id=opcao.horario_id
            ),
        )

    def _escolher_acao(self, paciente, consulta_id: int | None) -> ResultadoDialogo:
        opcao = self._consulta_do_paciente(paciente, consulta_id)
        if opcao is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        return ResultadoDialogo(
            TipoResultado.ESCOLHER_ACAO, opcao=opcao,
            acao_pendente=AcaoPendente(
                tipo=TipoAcao.GERENCIAR, consulta_id=opcao.consulta_id, origem_horario_id=opcao.horario_id
            ),
        )

    def _executar_acao_escolhida(self, paciente, pendente: AcaoPendente, mudar: bool) -> ResultadoDialogo:
        if mudar:
            return self._request_destination(paciente, pendente.consulta_id)
        return self._confirmar_cancelamento_de(paciente, pendente.consulta_id)

    def _responder_desmarcacao(self, leitura, mensagem, paciente, pendente: AcaoPendente) -> ResultadoDialogo | None:
        if leitura.tipo == TipoLeitura.CONFIRMA:
            if self._consulta_mudou(paciente, pendente):
                return self._com_consulta_atualizada(paciente, pendente)
            return self._cancelar(paciente, pendente.consulta_id)
        if leitura.tipo == TipoLeitura.NEGA:
            return self._descartar(paciente, pendente)
        return None

    def _responder_escolha_de_consulta(self, leitura, mensagem, paciente, pendente: AcaoPendente):
        match leitura.tipo:
            case TipoLeitura.ESCOLHA:
                consulta_id = pendente.consultas_oferecidas[leitura.indices[0] - 1]
                if pendente.tipo == TipoAcao.REMARCAR:
                    return self._request_destination(paciente, consulta_id, pendente.criterios)
                if pendente.tipo == TipoAcao.CANCELAR:
                    return self._confirmar_cancelamento_de(paciente, consulta_id)
                return self._escolher_acao(paciente, consulta_id)
            case TipoLeitura.AMBIGUA:
                ids = [pendente.consultas_oferecidas[indice - 1] for indice in leitura.indices]
                return self.reapresentar(paciente, pendente.model_copy(update={"consultas_oferecidas": ids}))
            case TipoLeitura.CONFIRMA:
                return self.reapresentar(paciente, pendente, Preambulo.ESCOLHA_PENDENTE)
            case TipoLeitura.NEGA:
                return ResultadoDialogo(TipoResultado.CANCELAMENTO_DESCARTADO)
            case TipoLeitura.OUTRA_OPCAO if pendente.tipo == TipoAcao.REMARCAR:
                return self.start_rescheduling(paciente, pendente.pagina_consultas + len(pendente.consultas_oferecidas))
        return None

    def _responder_acao_da_consulta(self, leitura, mensagem, paciente, pendente: AcaoPendente):
        frase = normalizar_frase(mensagem.texto)
        if mensagem.intencao == Intencao.REMARCAR or frase in _MUDAR:
            return self._executar_acao_escolhida(paciente, pendente, mudar=True)
        if mensagem.intencao == Intencao.CANCELAR or frase in _DESMARCAR:
            return self._executar_acao_escolhida(paciente, pendente, mudar=False)
        if leitura.tipo == TipoLeitura.NEGA:
            return self._descartar(paciente, pendente)
        if leitura.tipo == TipoLeitura.CONFIRMA:
            return self.reapresentar(paciente, pendente, Preambulo.ESCOLHA_PENDENTE)
        return None

    def _consulta_mudou(self, paciente, pendente: AcaoPendente) -> bool:
        """A confirmação vale para o horário mostrado; se a clínica mudou a consulta, pergunta de novo."""
        atual = self._consulta_do_paciente(paciente, pendente.consulta_id)
        return atual is not None and pendente.origem_horario_id is not None and atual.horario_id != pendente.origem_horario_id

    def _com_consulta_atualizada(self, paciente, pendente: AcaoPendente) -> ResultadoDialogo:
        if pendente.tipo == TipoAcao.CANCELAR:
            atualizada = self._confirmar_cancelamento_de(paciente, pendente.consulta_id)
        else:
            atualizada = self._escolher_acao(paciente, pendente.consulta_id)
        return replace(atualizada, preambulo=Preambulo.CONSULTA_MUDOU)

    def etapa_de_consulta(self, paciente, pendente: AcaoPendente) -> ResultadoDialogo:
        """Reapresenta cancelamento ou "mudar ou cancelar" conferindo se a consulta ainda existe."""
        if pendente.pergunta == Pergunta.ESCOLHER_CONSULTA:
            exibidas = [opcao for opcao in self._consultas_exibidas(paciente, pendente) if opcao is not None]
            if not exibidas:
                return self._listar(paciente)
            tipo = TipoResultado.CANCELAMENTO_AMBIGUO if pendente.tipo == TipoAcao.CANCELAR else TipoResultado.GERENCIAR_CONSULTAS
            atual = pendente.model_copy(update={"consultas_oferecidas": [opcao.consulta_id for opcao in exibidas]})
            return ResultadoDialogo(tipo, opcoes=tuple(exibidas), acao_pendente=atual)
        opcao = self._consulta_do_paciente(paciente, pendente.consulta_id)
        if opcao is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        if self._consulta_mudou(paciente, pendente):
            return self._com_consulta_atualizada(paciente, pendente)
        tipo = TipoResultado.CONFIRMAR_CANCELAMENTO if pendente.tipo == TipoAcao.CANCELAR else TipoResultado.ESCOLHER_ACAO
        return ResultadoDialogo(tipo, opcao=opcao, acao_pendente=pendente)
