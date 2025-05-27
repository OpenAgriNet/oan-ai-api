import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

def text_to_speech_bhashini(text, source_lang='mr', gender='female', sampling_rate=8000):
    url = 'https://dhruva-api.bhashini.gov.in/services/inference/pipeline'
    headers = {
        'Accept': '*/*',
        'Authorization': os.getenv('MEITY_API_KEY_VALUE'),
        'Content-Type': 'application/json',
    }
    data = {
        "pipelineTasks": [
            {
                "taskType": "tts",
                "config": {
                    "language": {
                        "sourceLanguage": source_lang
                    },
                    "serviceId": "",  
                    "gender": gender,
                    "samplingRate": sampling_rate
                }
            }
        ],
        "inputData": {
            "input": [
                {
                    "source": text
                }
            ]
        }
    }
    response = requests.post(url, headers=headers, json=data)
    assert response.status_code == 200, f"Error: {response.status_code} {response.text}"
    response_json = response.json()

    audio_content = response_json['pipelineResponse'][0]['audio'][0]['audioContent']
    audio_data = base64.b64decode(audio_content)
    return audio_data