import asyncio
import csv
import json
import os
import time
import subprocess
import requests
import websockets
import numpy as np
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8086/api"
WS_URL = "ws://localhost:8086/api/conv/ws"

QUERIES_FILE = "assets/test_data/queries.csv"
EN_VOICE_DIR = "assets/test_data/En_voice"
AM_VOICE_DIR = "assets/test_data/Am_voice"
OUTPUT_FILE = "performance_results.csv"

def get_audio_bytes(filepath):
    """Convert audio file to raw PCM float32 16kHz mono bytes using ffmpeg."""
    command = [
        "ffmpeg",
        "-i", filepath,
        "-f", "f32le",
        "-acodec", "pcm_f32le",
        "-ac", "1",
        "-ar", "16000",
        "pipe:1"
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    stdout, _ = process.communicate()
    return stdout

async def run_text_test(lang_code, lang_name):
    """Run text mode tests."""
    results = []
    
    with open(QUERIES_FILE, 'r') as f:
        reader = csv.DictReader(f)
        queries = list(reader)
        
    print(f"\n--- Running Text Mode Tests ({lang_name}) ---")
    
    for row in queries:
        query = row['query_text']
        print(f"Testing: {query}")
        
        start_time = time.time()
        try:
            response = requests.post(
                f"{BASE_URL}/chat/",
                json={
                    "query": query,
                    "source_lang": "en", # Input is English text (transliterated or translated usually)
                    "target_lang": lang_code,
                    "user_id": "test_script"
                },
                stream=True
            )
            
            collected_metrics = None
            
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode('utf-8'))
                        if "metrics" in data:
                            collected_metrics = data["metrics"]
                    except:
                        pass
            
            if collected_metrics:
                collected_metrics['mode'] = f"Text - {lang_name}"
                collected_metrics['input'] = query
                results.append(collected_metrics)
                print("✅ Metrics captured")
            else:
                print("⚠️ No metrics returned")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            
    return results

async def run_voice_test(lang_code, lang_name, voice_dir):
    """Run voice mode tests."""
    results = []
    
    if not os.path.exists(voice_dir):
        print(f"Directory {voice_dir} not found. Skipping.")
        return []
        
    files = [f for f in os.listdir(voice_dir) if f.endswith('.m4a') or f.endswith('.wav')]
    print(f"\n--- Running Voice Mode Tests ({lang_name}) ---")
    
    for filename in files:
        filepath = os.path.join(voice_dir, filename)
        print(f"Testing: {filename}")
        
        audio_bytes = get_audio_bytes(filepath)
        if not audio_bytes:
            print("Failed to convert audio.")
            continue
            
        try:
            async with websockets.connect(f"{WS_URL}?lang={lang_code}") as ws:
                # Chunk size for sending (e.g., 4096 bytes)
                chunk_size = 4096
                for i in range(0, len(audio_bytes), chunk_size):
                    chunk = audio_bytes[i:i+chunk_size]
                    # Send as bytes for audio
                    await ws.send(chunk)
                    await asyncio.sleep(0.01) # Simulate real-time streaming roughly
                
                print("Finished sending audio. Waiting for response...")
                
                # Wait for metrics
                captured_metrics = None
                start_wait = time.time()
                
                while time.time() - start_wait < 30: # 30s timeout
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        if isinstance(msg, bytes):
                            continue # Skip audio output
                        
                        data = json.loads(msg)
                        if data.get("type") == "metrics":
                            captured_metrics = data.get("data")
                            print("✅ Metrics captured")
                            break
                        
                        # Assuming the server sends metrics AFTER response
                        
                    except asyncio.TimeoutError:
                        print("Timeout waiting for message chunk.")
                        break
                    except websockets.exceptions.ConnectionClosed:
                        print("Details: Connection closed by server.")
                        break
                
                if captured_metrics:
                    captured_metrics['mode'] = f"Voice - {lang_name}"
                    captured_metrics['input'] = filename
                    results.append(captured_metrics)
                else:
                    print("⚠️ No metrics captured for this file.")
                    
        except Exception as e:
            print(f"❌ Error: {e}")
            
    return results

async def main():
    all_results = []
    
    # Text - En
    all_results.extend(await run_text_test("en", "En"))
    
    # Text - Am
    all_results.extend(await run_text_test("am", "Am"))
    
    # Voice - En
    all_results.extend(await run_voice_test("en", "En", EN_VOICE_DIR))
    
    # Voice - Am
    all_results.extend(await run_voice_test("am", "Am", AM_VOICE_DIR))
    
    # Save to CSV
    if all_results:
        # Determine headers from first result keys
        # We want to normalize headers order
        headers = ['mode', 'input', 'query', 'stt_duration', 'stt_transcription', 'buffer_wait', 'llm_ttfb', 'llm_inference_total', 'llm_total_time', 'tool_calls', 'tool_processing', 'moderation', 'tts_synthesis', 'e2e_latency', 'total_e2e_latency', 'first_audio_latency', 'text_streaming', 'response_generation', 'full_pipeline_time']
        
        # Merge keys from all results to be safe
        keys = set().union(*(d.keys() for d in all_results))
        for k in keys:
            if k not in headers:
                headers.append(k)
        
        with open(OUTPUT_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(all_results)
            
        print(f"\n✅ Results saved to {OUTPUT_FILE}")
    else:
        print("\n❌ No results collected.")

if __name__ == "__main__":
    asyncio.run(main())
