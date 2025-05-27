from django.urls import path
from oan_app.views import chat, transcribe, suggestions, tts

urlpatterns = [
    path('api/chat/', chat.chat, name='chat'),
    path('api/transcribe/', transcribe.transcribe, name='transcribe'),
    path('api/suggest/', suggestions.suggest, name='suggest'),
    path('api/tts/', tts.tts, name='tts')
]