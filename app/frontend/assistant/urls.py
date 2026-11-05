from django.urls import path
from .views import (
    CadastroUsuarioView,
    CalendarioView,
    CancelarConsultaView,
    ChatView,
    ConsultasView,
    DashboardRedirectView,
    EditarConsultaView,
    EquipeView,
    AgendaMedicaView,
    HorariosLivresView,
    LiberarHorariosView,
    NovaConsultaView,
)

urlpatterns = [
    path('', ChatView.as_view(), name='chat'),
    path('calendario/', CalendarioView.as_view(), name='calendario'),
    path('inicio/', DashboardRedirectView.as_view(), name='inicio'),
    path('medico/agenda/', AgendaMedicaView.as_view(), name='agenda_medica'),
    path('gestao/', EquipeView.as_view(), name='equipe'),
    path('gestao/cadastrar/', CadastroUsuarioView.as_view(), name='cadastro_usuario'),
    path('gestao/consultas/', ConsultasView.as_view(), name='consultas'),
    path('gestao/consultas/nova/', NovaConsultaView.as_view(), name='nova_consulta'),
    path('gestao/consultas/<int:consulta_id>/', EditarConsultaView.as_view(), name='editar_consulta'),
    path('gestao/consultas/<int:consulta_id>/cancelar/', CancelarConsultaView.as_view(), name='cancelar_consulta'),
    path('gestao/horarios/', LiberarHorariosView.as_view(), name='liberar_horarios'),
    path('gestao/horarios-livres/', HorariosLivresView.as_view(), name='horarios_livres'),
]