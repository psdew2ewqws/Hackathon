"""traffic-intel MCP server.

Exposes the Wadi Saqra intersection tools (live state, forecast, history,
recommendation, incidents, signal plan, read-only SQL) over the Model
Context Protocol. External clients (Claude Desktop, Cursor, other agents)
can connect via stdio and use the same intersection knowledge that the
in-app chat advisor uses.

Tool implementations are imported directly from
``traffic_intel_phase3.poc_wadi_saqra.llm.tools`` so there is one source
of truth for the tool surface.
"""
