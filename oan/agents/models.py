import os
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.google_gla import GoogleGLAProvider
from dotenv import load_dotenv

load_dotenv()

# Get configurations from environment variables
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'gemini').lower()
LLM_MODEL_NAME = os.getenv('LLM_MODEL_NAME', 'gemini-2.0-flash')

# Configure the model based on provider
if LLM_PROVIDER == 'gemini':
    LLM_MODEL = GeminiModel(
        LLM_MODEL_NAME,
        provider=GoogleGLAProvider(
            api_key=os.getenv('GEMINI_API_KEY'),
        )
    )
elif LLM_PROVIDER == 'vllm':
    LLM_MODEL = OpenAIModel(
        LLM_MODEL_NAME,
        provider=OpenAIProvider(
            base_url=os.getenv('INFERENCE_ENDPOINT_URL'), 
            api_key=os.getenv('INFERENCE_API_KEY'),  
        ),
    )
elif LLM_PROVIDER == 'openai':
    LLM_MODEL = OpenAIModel(
        LLM_MODEL_NAME,
        provider=OpenAIProvider(
            api_key=os.getenv('OPENAI_API_KEY'),
        ),
    )
else:
    raise ValueError(f"Invalid LLM_PROVIDER: {LLM_PROVIDER}. Must be one of: 'gemini', 'openai', 'vllm'")