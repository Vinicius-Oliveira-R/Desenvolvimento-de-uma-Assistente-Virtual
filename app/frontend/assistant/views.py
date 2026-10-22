from django.views.generic import TemplateView

class ChatView(TemplateView):
    template_name = "assistant/chat.html"

class CalendarioView(TemplateView):
    template_name = "assistant/calendario.html"