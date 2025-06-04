import uuid
from rest_framework.decorators import api_view
from rest_framework.response import Response
from helpers.transcription import transcribe_bhashini, detect_audio_language_bhashini
from rest_framework import status
from helpers.utils import get_logger
from oan_app.authentication import CustomJWTAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, authentication_classes, permission_classes

logger = get_logger(__name__)


@authentication_classes([CustomJWTAuthentication])
@permission_classes([IsAuthenticated])
@api_view(['POST','OPTIONS'])
def transcribe(request):
    """Handles language detection and transcription of audio."""
    audio_base64 = request.data.get('audio_content')
    session_id = request.data.get('session_id', str(uuid.uuid4()))
    
    if not audio_base64:
        return Response({
            'status': 'error',
            'message': 'audio_content is required'
        }, status=status.HTTP_400_BAD_REQUEST)
   
    lang_code = detect_audio_language_bhashini(audio_base64)
    logger.info(f"Detected language code: {lang_code}")
    transcription = transcribe_bhashini(audio_base64, lang_code)
    logger.info(f"Transcription: {transcription}")
   
    return Response({
        'status': 'success',
        'text': transcription,
        'lang_code': lang_code,
        'session_id': session_id
    }, status=status.HTTP_200_OK)
