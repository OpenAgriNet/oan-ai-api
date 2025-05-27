from rest_framework.decorators import api_view
from rest_framework.response import Response
from helpers.tts import text_to_speech_bhashini
from rest_framework import status
from helpers.utils import get_logger
import uuid
import base64
from oan_app.authentication import CustomJWTAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import authentication_classes, permission_classes
logger = get_logger(__name__)


@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
@api_view(['POST','OPTIONS'])
def tts(request):
    """Handles text to speech of audio."""
    text       = request.data.get('text')
    target_lang = request.data.get('target_lang', 'mr')
    session_id = request.data.get('session_id', str(uuid.uuid4()))
    
    if not text:
        return Response({
            'status': 'error',
            'message': 'text is required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    audio_data = text_to_speech_bhashini(text, target_lang, gender='female', sampling_rate=8000)
    
    # Base64 encode the binary audio data for JSON serialization
    if isinstance(audio_data, bytes):
        audio_data = base64.b64encode(audio_data).decode('utf-8')
    
    return Response({
        'status': 'success',
        'audio_data': audio_data,
        'session_id': session_id
    }, status=status.HTTP_200_OK)
