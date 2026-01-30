
import re
from datetime import datetime

log_file = "detailed_analysis_logs.txt"

def parse_logs():
    turns = {}
    
    # Check if file exists
    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: {log_file} not found.")
        return

    # Regex patterns
    # 2026-01-22 19:02:49,603
    timestamp_pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
    
    # We need to map timestamps to high-resolution floats for accurate diffs if possible, 
    # but the log format only gives ms. We can parsed datetime.
    
    for line in lines:
        try:
            ts_match = re.search(timestamp_pattern, line)
            if not ts_match:
                continue
            
            ts_str = ts_match.group(1)
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f").timestamp()
            
            # Identify Turn
            # Matches "[Turn 1]" or "Turn 1:"
            turn_match = re.search(r"Turn (\d+)", line) # Simplified regex
            turn_id = int(turn_match.group(1)) if turn_match else None
            
            # Debug
            # if "LATENCY" in line:
            #    print(f"Debug: Found LATENCY. Turn: {turn_id} | Line: {line.strip()}")

            # Start of a Turn's LLM Request
            if "LLM Request START" in line and turn_id:
                if turn_id not in turns: turns[turn_id] = {"tools": []}
                turns[turn_id]["start"] = ts
                
            # First Token
            if "First Token Received" in line and turn_id:
                turns[turn_id]["ttft_ts"] = ts
                
            # End of Turn
            if "LLM Request END" in line and turn_id:
                turns[turn_id]["end"] = ts
                
            # Tool Usage (approximate mapping to latest active turn)
            if "PRINT_LATENCY" in line and "START" in line:
                # Find the active turn (latest one started but not ended)
                # But wait, if START is logged, the turn might not be "ended" yet?
                # Actually, tools run INSIDE the run.
                # However, with run_stream vs tools...
                # Tools are part of the 'start' to 'ttft' phase if pydantic-ai.
                
                # If we can't find an active turn, maybe just list it separately?
                # Let's try to find a turn where start < tool_start and (end is None or end > tool_start)
                active_turns = [t for t in turns if turns[t].get("start") and turns[t]["start"] < ts]
                if active_turns:
                    active_turn = max(active_turns) # Assume latest started turn
                    tool_name = re.search(r"Tool '(.+?)'", line).group(1)
                    turns[active_turn]["tools"].append({"name": tool_name, "start": ts})
                else:
                    # Fallback for when tool execution happens before logic captures start? Unlikely.
                    pass
            
            if "PRINT_LATENCY" in line and "END" in line:
                active_turns = [t for t in turns if turns[t].get("start") and turns[t]["start"] < ts]
                if active_turns:
                    active_turn = max(active_turns)
                    # Match with last started tool
                    if turns[active_turn]["tools"]:
                        last_tool = turns[active_turn]["tools"][-1]
                        last_tool["end"] = ts
                    
        except Exception as e:
            continue

    # Analysis
    print(f"{'Turn':<6} | {'Phase 1 (Pre-Tool)':<20} | {'Phase 2 (Tools)':<20} | {'Phase 3 (Post-Tool)':<20} | {'Phase 4 (Stream)':<20} | {'Total':<10}")
    print("-" * 105)
    
    for t_id, data in sorted(turns.items()):
        start = data.get("start")
        end = data.get("end")
        ttft_ts = data.get("ttft_ts")
        tools = data.get("tools", [])
        
        if not start or not end: continue
        
        # Calculate Tool Time
        tool_start = tools[0]["start"] if tools else None
        tool_end = tools[-1]["end"] if tools else None
        tool_duration = sum([t["end"] - t["start"] for t in tools if "end" in t and "start" in t])
        
        # Phase 1: Start -> Tool Start (or TTFT if no tools)
        p1_end = tool_start if tools else ttft_ts
        p1_duration = (p1_end - start) if (p1_end and start) else 0
        
        # Phase 2: Tools
        p2_duration = tool_duration
        
        # Phase 3: Tool End -> TTFT
        p3_start = tool_end if tools else start
        p3_duration = (ttft_ts - p3_start) if (ttft_ts and p3_start) else 0
        
        # Phase 4: TTFT -> End
        p4_duration = (end - ttft_ts) if (end and ttft_ts) else 0
        
        total = end - start
        
        print(f"{t_id:<6} | {p1_duration:<20.4f} | {p2_duration:<20.4f} | {p3_duration:<20.4f} | {p4_duration:<20.4f} | {total:<10.4f}")
        for tool in tools:
             print(f"       -> Tool: {tool['name']} ({tool.get('end', 0) - tool.get('start', 0):.4f}s)")

if __name__ == "__main__":
    parse_logs()
