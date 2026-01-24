import os
import inspect
import httpx
import json
from typing import List, Dict, Any
from agents.tools import TOOLS
from helpers.utils import get_logger
from pydantic import TypeAdapter

logger = get_logger(__name__)

# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "function-gemma")
ENABLE_OLLAMA_ROUTER = os.getenv("ENABLE_OLLAMA_ROUTER", "false").lower() == "true"

class ToolRouter:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.tools_map = {tool.name: tool for tool in TOOLS}
        self.tools_schema = self._generate_tools_schema()
        logger.info(f"ToolRouter initialized with {len(self.tools_schema)} tools. Enabled: {ENABLE_OLLAMA_ROUTER}")

    def _generate_tools_schema(self) -> List[Dict[str, Any]]:
        """Generate JSON schema for tools compatible with Ollama/OpenAI"""
        schema_list = []
        for tool in TOOLS:
            try:
                func = tool.function
                sig = inspect.signature(func)
                doc = inspect.getdoc(func) or ""
                
                properties = {}
                required = []
                
                for name, param in sig.parameters.items():
                    # Skip 'ctx' or RunContext
                    if name == 'ctx' or 'RunContext' in str(param.annotation):
                        continue
                        
                    # Get parameter type
                    param_type = param.annotation
                    if param_type == inspect.Parameter.empty:
                        param_type = str
                        
                    # Generate schema for type
                    try:
                        type_schema = TypeAdapter(param_type).json_schema()
                        
                        prop = {}
                        if 'type' in type_schema:
                            prop['type'] = type_schema['type']
                        elif 'anyOf' in type_schema:
                            # Handle Optional[str] -> anyOf: [{type: string}, {type: null}]
                            # Simplify to string for LLM
                            prop['type'] = 'string'
                        
                        if 'enum' in type_schema:
                            prop['enum'] = type_schema['enum']
                            
                        # Add to properties
                        properties[name] = prop
                    except:
                        # Fallback
                        properties[name] = {"type": "string"}
                    
                    if param.default == inspect.Parameter.empty:
                        required.append(name)
                
                tool_def = {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": doc.split('\n')[0],
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required
                        }
                    }
                }
                schema_list.append(tool_def)
            except Exception as e:
                logger.error(f"Failed to generate schema for tool {tool.name}: {e}")
        
        return schema_list

    async def route_query(self, query: str) -> List[Dict[str, Any]]:
        """Call Ollama to detect tool calls"""
        if not ENABLE_OLLAMA_ROUTER:
            return []
            
        try:
            logger.info(f"Router calling Ollama ({OLLAMA_MODEL}) for query: {query}")
            
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": query}],
                "tools": self.tools_schema,
                "stream": False,
                "options": {
                    "temperature": 0.0 # Deterministic for tools
                }
            }
            
            response = await self.client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            
            if response.status_code != 200:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                return []
                
            data = response.json()
            message = data.get("message", {})
            tool_calls = message.get("tool_calls", [])
            
            if tool_calls:
                logger.info(f"Router found {len(tool_calls)} tool calls: {json.dumps(tool_calls)}")
            else:
                logger.info("Router found no tool calls")
                
            return tool_calls
            
        except Exception as e:
            logger.error(f"Error in route_query: {e}")
            return []

    async def execute_tools(self, tool_calls: List[Dict[str, Any]], deps: Any) -> List[Dict[str, Any]]:
        """Execute selected tools and return results"""
        results = []
        for call in tool_calls:
            func_data = call.get("function", {})
            func_name = func_data.get("name")
            args = func_data.get("arguments", {})
            
            tool = self.tools_map.get(func_name)
            if tool:
                try:
                    logger.info(f"Executing tool: {func_name} with args: {args}")
                    
                    # Execute tool via pydantic-ai Tool.run
                    # pydantic-ai handles context injection if deps provided
                    result = await tool.run(args, deps=deps)
                    
                    # Extract string result
                    result_str = str(result.data) if hasattr(result, 'data') else str(result)
                    
                    results.append({
                        "tool_name": func_name,
                        "args": args,
                        "result": result_str
                    })
                except Exception as e:
                    logger.error(f"Error executing tool {func_name}: {e}")
                    results.append({
                        "tool_name": func_name,
                        "args": args,
                        "error": str(e)
                    })
            else:
                logger.warning(f"Tool {func_name} not found in registry")
                
        return results

tool_router = ToolRouter()
