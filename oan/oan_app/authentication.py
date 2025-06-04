# oan/oan_app/authentication.py

import jwt
from dotenv import load_dotenv
load_dotenv()
# Cryptography
from cryptography.hazmat.primitives import serialization
from rest_framework.authentication import BaseAuthentication
from rest_framework import exceptions
from helpers.utils import get_logger

logger = get_logger(__name__)

# Load the public key
with open('../jwt_public_key.pem', 'rb') as key_file:
    public_key = serialization.load_pem_public_key(key_file.read())

class CustomJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise exceptions.AuthenticationFailed('No auth header')
        
        token = auth_header.split(' ')[1]
        try:
            decoded_token = jwt.decode(
                token,
                public_key,
                algorithms=['RS256'],
                audience=None,
                issuer=None, 
                options={"verify_signature": True} 
            )
            
            logger.info(f"\n\nSuccessfully decoded token: {decoded_token}\n\n")

            mobile = decoded_token.get('mobile')


            return (mobile, None)
        
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed('Token has expired')
        
        except jwt.InvalidTokenError as e:
            logger.info(f"Invalid token error: {str(e)}")
            raise exceptions.AuthenticationFailed(f'Invalid token: {str(e)}')
        
        except Exception as e:
            logger.info(f"Unexpected error during token verification: {str(e)}")
            raise exceptions.AuthenticationFailed(f'Token verification failed: {str(e)}')
