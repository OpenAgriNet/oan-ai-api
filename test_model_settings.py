#!/usr/bin/env python3
"""
Quick test to verify model settings are being applied correctly.
Run: python test_model_settings.py
"""

import os
import sys
import time
import asyncio
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

# Test 1: Check if model settings are accessible
print("=" * 80)
print("TEST 1: Model Settings Configuration")
print("=" * 80)

model = GoogleModel(model_name="gemini-3-flash-preview")
print(f"✓ Model created: {model}")

agent = Agent(
    model=model,
    output_type=str,
    model_settings={
        "max_output_tokens": 200,
        "temperature": 0.2,
        "thinking_config": {
            "thinking_level": "MINIMAL"
        }
    }
)

print(f"✓ Agent created")
print(f"✓ Agent.model_settings: {agent.model_settings}")
print()

# Test 2: Make a simple call and measure time
print("=" * 80)
print("TEST 2: Simple Generation Test (should be fast with 200 token limit)")
print("=" * 80)

async def test_generation():
    prompt = "Write a very long essay about agriculture."
    
    print(f"Prompt: {prompt}")
    print(f"Expected: Short response (max 200 tokens) due to max_output_tokens setting")
    print()
    
    start = time.time()
    result = await agent.run(prompt)
    elapsed = time.time() - start
    
    response = result.output
    word_count = len(response.split())
    char_count = len(response)
    
    print(f"✓ Response received in {elapsed:.2f}s")
    print(f"✓ Response length: {char_count} chars, ~{word_count} words")
    print(f"✓ Response preview: {response[:200]}...")
    print()
    
    # Check if response is short (200 tokens ≈ 150 words ≈ 800 chars)
    if char_count > 1000:
        print("⚠️  WARNING: Response is too long! max_output_tokens might not be working")
        print(f"   Expected: <800 chars, Got: {char_count} chars")
    else:
        print("✅ Response length looks good - max_output_tokens seems to be working")
    
    return elapsed, char_count

# Test 3: Compare with and without settings
print("=" * 80)
print("TEST 3: Comparison Test")
print("=" * 80)

async def test_comparison():
    # Agent WITH settings
    agent_with = Agent(
        model=GoogleModel(model_name="gemini-3-flash-preview"),
        output_type=str,
        model_settings={
            "max_output_tokens": 200,
            "temperature": 0.2,
        }
    )
    
    # Agent WITHOUT settings
    agent_without = Agent(
        model=GoogleModel(model_name="gemini-3-flash-preview"),
        output_type=str,
    )
    
    prompt = "Explain photosynthesis in detail."
    
    print("Testing WITH max_output_tokens=200...")
    start = time.time()
    result_with = await agent_with.run(prompt)
    time_with = time.time() - start
    len_with = len(result_with.output)
    
    print(f"  Time: {time_with:.2f}s, Length: {len_with} chars")
    
    print("\nTesting WITHOUT max_output_tokens...")
    start = time.time()
    result_without = await agent_without.run(prompt)
    time_without = time.time() - start
    len_without = len(result_without.output)
    
    print(f"  Time: {time_without:.2f}s, Length: {len_without} chars")
    
    print("\nComparison:")
    print(f"  WITH settings:    {time_with:.2f}s, {len_with} chars")
    print(f"  WITHOUT settings: {time_without:.2f}s, {len_without} chars")
    
    if len_with < len_without * 0.5:
        print("✅ max_output_tokens IS working (response is much shorter)")
    else:
        print("⚠️  max_output_tokens might NOT be working (responses similar length)")

# Run tests
async def main():
    try:
        elapsed, length = await test_generation()
        print()
        await test_comparison()
        
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"If max_output_tokens is working:")
        print(f"  - Responses should be <800 chars")
        print(f"  - Generation should be faster (~2-3s)")
        print(f"\nYour results:")
        print(f"  - Response length: {length} chars")
        print(f"  - Generation time: {elapsed:.2f}s")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
