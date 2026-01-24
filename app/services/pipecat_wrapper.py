import asyncio
import os
import json
from typing import AsyncGenerator

from loguru import logger

# Pipecat imports (Standard assumptions)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.network.fastapi_websocket import FastAPIWebSocketTransport, FastAPIWebSocketParams
from pipecat.services.ai_services import LLMService
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    AudioFrame,
    StartInterruptionFrame,
    EndInterruptionFrame,
    LLMFullResponseFrame,
    EndFrame
)
from pipecat.vad.silero import SileroVADAnalyzer

# App imports
from agents.agrinet import agrinet_agent, generation_agent
from app.services.router import tool_router, ENABLE_OLLAMA_ROUTER
from agents.deps import FarmerContext
from app.utils import sanitize_history_for_generation

class AgriNetLLMService(LLMService):
    """Custom LLM Service for Pipecat that uses AgriNet Router + Generator"""
    
    def __init__(self, context: FarmerContext):
        super().__init__()
        self.context = context
        self.history = [] # Simplified history

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame):
            user_text = frame.text
            logger.info(f"User text: {user_text}")

            # Route 
            agent_to_use = agrinet_agent
            prompt_text = user_text
            
            if ENABLE_OLLAMA_ROUTER:
                try:
                    tool_calls = await tool_router.route_query(user_text)
                    if tool_calls:
                        # Execute tools
                        # Note: This is synchronous/blocking for now in the pipeline flow
                        tool_results = await tool_router.execute_tools(tool_calls, deps=self.context)
                        res_str = "\n".join([f"Tool {t['tool_name']} returned: {t.get('result', t.get('error'))}" for t in tool_results])
                        prompt_text = f"{user_text}\n\n[Context from Tool Execution]:\n{res_str}"
                    
                    agent_to_use = generation_agent
                except Exception as e:
                    logger.error(f"Router failed: {e}")
            
            # Generate Stream
            # We need to bridge pydantic-ai streaming to Pipecat frames
            # pydantic-ai stream yields text chunks
            
            # Sanitize history if using generation agent
            hist_to_use = self.history
            if agent_to_use == generation_agent:
                hist_to_use = sanitize_history_for_generation(self.history)

            try:
                async with agent_to_use.run_stream(
                    user_prompt=prompt_text,
                    message_history=hist_to_use,
                    deps=self.context
                ) as result:
                    async for chunk in result.stream_text(delta=True):
                        if chunk:
                            await self.push_frame(TextFrame(chunk))
                    
                    # Store history?
                    # Pipecat doesn't manage history automatically like pydantic-ai.
                    # We manually updated self.history?
                    # Actually pydantic-ai `result` object has `.new_messages()`
                    pass
                
                # Get final result to update history
                final_res = result
                self.history.extend(final_res.new_messages())
                
                await self.push_frame(LLMFullResponseFrame("Done"))
                
            except Exception as e:
                logger.error(f"Generation failed: {e}")
                await self.push_frame(TextFrame("I encountered an error."))

        else:
            await self.push_frame(frame, direction)

