#!/usr/bin/env python3
"""
Test script to verify agent imports work correctly
"""
import sys
import time

print("Testing agent imports...")
print("=" * 60)

# Test 1: Import agent
print("\n1. Testing agent import...")
start = time.time()
try:
    from agents.agrinet import agrinet_agent
    elapsed = time.time() - start
    print(f"   ✅ Agent imported successfully in {elapsed:.2f}s")
    print(f"   Agent name: {agrinet_agent.name}")
except Exception as e:
    elapsed = time.time() - start
    print(f"   ❌ Agent import failed in {elapsed:.2f}s")
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Import context
print("\n2. Testing context import...")
start = time.time()
try:
    from agents.deps import FarmerContext
    elapsed = time.time() - start
    print(f"   ✅ Context imported successfully in {elapsed:.2f}s")
except Exception as e:
    elapsed = time.time() - start
    print(f"   ❌ Context import failed in {elapsed:.2f}s")
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Create context
print("\n3. Testing context creation...")
start = time.time()
try:
    context = FarmerContext(
        query="Test query",
        lang_code="en"
    )
    elapsed = time.time() - start
    print(f"   ✅ Context created successfully in {elapsed:.2f}s")
    print(f"   Query: {context.query}")
    print(f"   Lang: {context.lang_code}")
except Exception as e:
    elapsed = time.time() - start
    print(f"   ❌ Context creation failed in {elapsed:.2f}s")
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Test agent run (simple)
print("\n4. Testing agent run...")
start = time.time()
try:
    import asyncio
    
    async def test_agent():
        result = await agrinet_agent.run(
            user_prompt="Hello",
            deps=context
        )
        return result
    
    result = asyncio.run(test_agent())
    elapsed = time.time() - start
    print(f"   ✅ Agent run completed in {elapsed:.2f}s")
    print(f"   Response: {result.output[:100]}...")
except Exception as e:
    elapsed = time.time() - start
    print(f"   ❌ Agent run failed in {elapsed:.2f}s")
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ All tests passed!")
print("=" * 60)

