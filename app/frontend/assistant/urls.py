from django.urls import path
from .views import ChatView, CalendarioView

urlpatterns = [
    path('', ChatView.as_view(), name='chat'),
    path('calendario/', CalendarioView.as_view(), name='calendario'),
]