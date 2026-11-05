from django.urls import path
from .views import (
    CadastroUsuarioView,
    CalendarioView,
    CancelarConsultaView,
    ChatView,
    ConsultasView,
    EditarConsultaView,
    EquipeView,
    HorariosLivresView,
    NovaConsultaView,
)

urlpatterns = [
    path('', ChatView.as_view(), name='chat'),
    path('calendario/', CalendarioView.as_view(), name='calendario'),
    path('equipe/', EquipeView.as_view(), name='equipe'),
    path('equipe/cadastrar/', CadastroUsuarioView.as_view(), name='cadastro_usuario'),
    path('equipe/consultas/', ConsultasView.as_view(), name='consultas'),
    path('equipe/consultas/nova/', NovaConsultaView.as_view(), name='nova_consulta'),
    path('equipe/consultas/<int:consulta_id>/', EditarConsultaView.as_view(), name='editar_consulta'),
    path('equipe/consultas/<int:consulta_id>/cancelar/', CancelarConsultaView.as_view(), name='cancelar_consulta'),
    path('equipe/horarios-livres/', HorariosLivresView.as_view(), name='horarios_livres'),
]