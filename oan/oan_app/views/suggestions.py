
from rest_framework.decorators import api_view
from oan_app.views.utils import get_logger
from oan_app.tasks.suggestions import create_suggestions
from django.core.cache import cache
from rest_framework.response import Response
from oan_app.authentication import CustomJWTAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, authentication_classes, permission_classes

logger = get_logger(__name__)


@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
@api_view(['GET','OPTIONS'])
def suggest(request):
    """Handles chat sessions between a user and the AI assistant."""
    session_id    = request.query_params.get('session_id')
    target_lang   = request.query_params.get('target_lang', 'mr') # Target language is Marathi, unless otherwise specified
    suggestions   = cache.get(f"suggestions_{session_id}_{target_lang}", [])
    if not suggestions:
        create_suggestions.s(session_id, target_lang).apply_async()
    return Response(suggestions)