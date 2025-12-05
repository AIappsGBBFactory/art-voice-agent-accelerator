"""
Agent Builder Endpoints
=======================

REST endpoints for dynamically creating and managing agents at runtime.
Supports session-scoped agent configurations that can be modified through
the frontend without restarting the backend.

Endpoints:
    GET  /api/v1/agent-builder/tools      - List available tools
    GET  /api/v1/agent-builder/voices     - List available voices
    GET  /api/v1/agent-builder/defaults   - Get default agent configuration
    POST /api/v1/agent-builder/create     - Create dynamic agent for session
    GET  /api/v1/agent-builder/session/{session_id} - Get session agent config
    PUT  /api/v1/agent-builder/session/{session_id} - Update session agent config
    DELETE /api/v1/agent-builder/session/{session_id} - Reset to default agent
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from apps.artagent.backend.agents.tools.registry import (
    initialize_tools,
    list_tools,
    get_tool_definition,
    _TOOL_DEFINITIONS,
)
from apps.artagent.backend.agents.loader import (
    load_defaults,
    load_prompt,
    AGENTS_DIR,
)
from apps.artagent.backend.agents.base import (
    UnifiedAgent,
    VoiceConfig,
    ModelConfig,
    HandoffConfig,
    SpeechConfig,
)
from apps.artagent.backend.agents.session_manager import (
    SessionAgentManager,
    SessionAgentConfig,
)
from apps.artagent.backend.src.orchestration.session_agents import (
    get_session_agent,
    set_session_agent,
    remove_session_agent,
    list_session_agents,
)
from config import DEFAULT_TTS_VOICE
from utils.ml_logging import get_logger
import yaml

logger = get_logger("v1.agent_builder")

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════


class ToolInfo(BaseModel):
    """Tool information for frontend display."""
    name: str
    description: str
    is_handoff: bool = False
    tags: List[str] = []
    parameters: Optional[Dict[str, Any]] = None


class VoiceInfo(BaseModel):
    """Voice information for frontend selection."""
    name: str
    display_name: str
    category: str  # turbo, standard, hd
    language: str = "en-US"


class ModelConfigSchema(BaseModel):
    """Model configuration schema."""
    deployment_id: str = "gpt-4o"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, ge=1, le=16384)


class VoiceConfigSchema(BaseModel):
    """Voice configuration schema."""
    name: str = "en-US-AvaMultilingualNeural"
    type: str = "azure-standard"
    style: str = "chat"
    rate: str = "+0%"


class SpeechConfigSchema(BaseModel):
    """Speech recognition (STT) configuration schema."""
    vad_silence_timeout_ms: int = Field(
        default=800, 
        ge=100, 
        le=5000, 
        description="Silence duration (ms) before finalizing recognition"
    )
    use_semantic_segmentation: bool = Field(
        default=False, 
        description="Enable semantic sentence boundary detection"
    )
    candidate_languages: List[str] = Field(
        default_factory=lambda: ["en-US", "es-ES", "fr-FR", "de-DE", "it-IT"],
        description="Languages for automatic detection"
    )
    enable_diarization: bool = Field(
        default=False, 
        description="Enable speaker diarization"
    )
    speaker_count_hint: int = Field(
        default=2, 
        ge=1, 
        le=10, 
        description="Hint for number of speakers"
    )


class DynamicAgentConfig(BaseModel):
    """Configuration for creating a dynamic agent."""
    name: str = Field(..., min_length=1, max_length=64, description="Agent display name")
    description: str = Field(default="", max_length=512, description="Agent description")
    greeting: str = Field(default="", max_length=1024, description="Initial greeting message")
    return_greeting: str = Field(default="", max_length=1024, description="Return greeting when caller comes back")
    prompt: str = Field(..., min_length=10, description="System prompt for the agent")
    tools: List[str] = Field(default_factory=list, description="List of tool names to enable")
    model: Optional[ModelConfigSchema] = None
    voice: Optional[VoiceConfigSchema] = None
    speech: Optional[SpeechConfigSchema] = None
    template_vars: Optional[Dict[str, Any]] = None


class SessionAgentResponse(BaseModel):
    """Response for session agent operations."""
    session_id: str
    agent_name: str
    status: str
    config: Dict[str, Any]
    created_at: Optional[float] = None
    modified_at: Optional[float] = None


class AgentTemplateInfo(BaseModel):
    """Agent template information for frontend display."""
    id: str
    name: str
    description: str
    greeting: str
    prompt_preview: str
    prompt_full: str
    tools: List[str]
    voice: Optional[Dict[str, Any]] = None
    model: Optional[Dict[str, Any]] = None
    is_entry_point: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# AVAILABLE VOICES CATALOG
# ═══════════════════════════════════════════════════════════════════════════════

AVAILABLE_VOICES = [
    # Turbo voices - lowest latency
    VoiceInfo(name="en-US-AlloyTurboMultilingualNeural", display_name="Alloy (Turbo)", category="turbo"),
    VoiceInfo(name="en-US-EchoTurboMultilingualNeural", display_name="Echo (Turbo)", category="turbo"),
    VoiceInfo(name="en-US-FableTurboMultilingualNeural", display_name="Fable (Turbo)", category="turbo"),
    VoiceInfo(name="en-US-OnyxTurboMultilingualNeural", display_name="Onyx (Turbo)", category="turbo"),
    VoiceInfo(name="en-US-NovaTurboMultilingualNeural", display_name="Nova (Turbo)", category="turbo"),
    VoiceInfo(name="en-US-ShimmerTurboMultilingualNeural", display_name="Shimmer (Turbo)", category="turbo"),
    # Standard voices
    VoiceInfo(name="en-US-AvaMultilingualNeural", display_name="Ava", category="standard"),
    VoiceInfo(name="en-US-AndrewMultilingualNeural", display_name="Andrew", category="standard"),
    VoiceInfo(name="en-US-EmmaMultilingualNeural", display_name="Emma", category="standard"),
    VoiceInfo(name="en-US-BrianMultilingualNeural", display_name="Brian", category="standard"),
    # HD voices - highest quality
    VoiceInfo(name="en-US-Ava:DragonHDLatestNeural", display_name="Ava HD", category="hd"),
    VoiceInfo(name="en-US-Andrew:DragonHDLatestNeural", display_name="Andrew HD", category="hd"),
    VoiceInfo(name="en-US-Brian:DragonHDLatestNeural", display_name="Brian HD", category="hd"),
    VoiceInfo(name="en-US-Emma:DragonHDLatestNeural", display_name="Emma HD", category="hd"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION AGENT STORAGE
# ═══════════════════════════════════════════════════════════════════════════════
# Session agent storage is now centralized in:
# apps/artagent/backend/src/orchestration/session_agents.py
# Import get_session_agent, set_session_agent, remove_session_agent from there.


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/tools",
    response_model=Dict[str, Any],
    summary="List Available Tools",
    description="Get list of all registered tools that can be assigned to dynamic agents.",
    tags=["Agent Builder"],
)
async def list_available_tools(
    category: Optional[str] = None,
    include_handoffs: bool = True,
) -> Dict[str, Any]:
    """
    List all available tools for agent configuration.
    
    Args:
        category: Filter by category (banking, auth, fraud, etc.)
        include_handoffs: Whether to include handoff tools
    """
    start = time.time()
    
    # Ensure tools are initialized
    initialize_tools()
    
    tools_list: List[ToolInfo] = []
    categories: Dict[str, int] = {}
    
    for name, defn in _TOOL_DEFINITIONS.items():
        # Skip handoffs if not requested
        if defn.is_handoff and not include_handoffs:
            continue
        
        # Filter by category if specified
        if category and category not in defn.tags:
            continue
        
        # Extract parameter info from schema
        params = None
        if defn.schema and "parameters" in defn.schema:
            params = defn.schema["parameters"]
        
        tool_info = ToolInfo(
            name=name,
            description=defn.description or defn.schema.get("description", ""),
            is_handoff=defn.is_handoff,
            tags=list(defn.tags),
            parameters=params,
        )
        tools_list.append(tool_info)
        
        # Count categories
        for tag in defn.tags:
            categories[tag] = categories.get(tag, 0) + 1
    
    # Sort by name for consistent display
    tools_list.sort(key=lambda t: (t.is_handoff, t.name))
    
    return {
        "status": "success",
        "total": len(tools_list),
        "tools": [t.model_dump() for t in tools_list],
        "categories": categories,
        "response_time_ms": round((time.time() - start) * 1000, 2),
    }


@router.get(
    "/voices",
    response_model=Dict[str, Any],
    summary="List Available Voices",
    description="Get list of all available TTS voices for agent configuration.",
    tags=["Agent Builder"],
)
async def list_available_voices(
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all available TTS voices.
    
    Args:
        category: Filter by category (turbo, standard, hd)
    """
    voices = AVAILABLE_VOICES
    
    if category:
        voices = [v for v in voices if v.category == category]
    
    # Group by category
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for voice in voices:
        if voice.category not in by_category:
            by_category[voice.category] = []
        by_category[voice.category].append(voice.model_dump())
    
    return {
        "status": "success",
        "total": len(voices),
        "voices": [v.model_dump() for v in voices],
        "by_category": by_category,
        "default_voice": DEFAULT_TTS_VOICE,
    }


@router.get(
    "/defaults",
    response_model=Dict[str, Any],
    summary="Get Default Agent Configuration",
    description="Get the default configuration template for creating new agents.",
    tags=["Agent Builder"],
)
async def get_default_config() -> Dict[str, Any]:
    """Get default agent configuration from _defaults.yaml."""
    defaults = load_defaults(AGENTS_DIR)
    
    return {
        "status": "success",
        "defaults": {
            "model": defaults.get("model", {
                "deployment_id": "gpt-4o",
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": 4096,
            }),
            "voice": defaults.get("voice", {
                "name": "en-US-AvaMultilingualNeural",
                "type": "azure-standard",
                "style": "chat",
                "rate": "+0%",
            }),
            "session": defaults.get("session", {}),
            "template_vars": defaults.get("template_vars", {
                "institution_name": "Contoso Financial",
                "agent_name": "Assistant",
            }),
        },
        "prompt_template": """You are {{ agent_name }}, a helpful assistant for {{ institution_name }}.

## Your Role
Assist customers with their inquiries in a friendly, professional manner.

## Guidelines
- Be concise and helpful
- Ask clarifying questions when needed
- Use the available tools when appropriate
""",
    }


@router.get(
    "/templates",
    response_model=Dict[str, Any],
    summary="List Available Agent Templates",
    description="Get list of all existing agent configurations that can be used as templates.",
    tags=["Agent Builder"],
)
async def list_agent_templates() -> Dict[str, Any]:
    """
    List all available agent templates from the agents directory.
    
    Returns agent configurations that can be used as starting points
    for creating new dynamic agents.
    """
    start = time.time()
    templates: List[AgentTemplateInfo] = []
    defaults = load_defaults(AGENTS_DIR)
    
    # Scan for agent directories
    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        if agent_dir.name.startswith("_") or agent_dir.name.startswith("."):
            continue
        
        agent_file = agent_dir / "agent.yaml"
        if not agent_file.exists():
            continue
        
        try:
            with open(agent_file, "r") as f:
                raw = yaml.safe_load(f) or {}
            
            # Extract name and description
            name = raw.get("name") or agent_dir.name.replace("_", " ").title()
            description = raw.get("description", "")
            greeting = raw.get("greeting", "")
            
            # Load prompt from file or inline
            prompt_full = ""
            if "prompts" in raw and raw["prompts"].get("path"):
                prompt_full = load_prompt(agent_dir, raw["prompts"]["path"])
            elif raw.get("prompt"):
                prompt_full = load_prompt(agent_dir, raw["prompt"])
            
            # Get tools list
            tools = raw.get("tools", [])
            
            # Get voice and model configs
            voice = raw.get("voice")
            model = raw.get("model")
            
            # Check if entry point
            handoff_config = raw.get("handoff", {})
            is_entry_point = handoff_config.get("is_entry_point", False)
            
            # Create preview (first 300 chars)
            prompt_preview = prompt_full[:300] + "..." if len(prompt_full) > 300 else prompt_full
            
            templates.append(AgentTemplateInfo(
                id=agent_dir.name,
                name=name,
                description=description if isinstance(description, str) else str(description)[:200],
                greeting=greeting if isinstance(greeting, str) else str(greeting),
                prompt_preview=prompt_preview,
                prompt_full=prompt_full,
                tools=tools,
                voice=voice,
                model=model,
                is_entry_point=is_entry_point,
            ))
            
        except Exception as e:
            logger.warning("Failed to load agent template %s: %s", agent_dir.name, e)
            continue
    
    # Sort by name, with entry point first
    templates.sort(key=lambda t: (not t.is_entry_point, t.name))
    
    return {
        "status": "success",
        "total": len(templates),
        "templates": [t.model_dump() for t in templates],
        "response_time_ms": round((time.time() - start) * 1000, 2),
    }


@router.get(
    "/templates/{template_id}",
    response_model=Dict[str, Any],
    summary="Get Agent Template Details",
    description="Get full details of a specific agent template.",
    tags=["Agent Builder"],
)
async def get_agent_template(template_id: str) -> Dict[str, Any]:
    """
    Get the full configuration of a specific agent template.
    
    Args:
        template_id: The agent directory name (e.g., 'concierge', 'fraud_agent')
    """
    agent_dir = AGENTS_DIR / template_id
    agent_file = agent_dir / "agent.yaml"
    
    if not agent_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Agent template '{template_id}' not found. Use GET /templates to see available templates.",
        )
    
    defaults = load_defaults(AGENTS_DIR)
    
    try:
        with open(agent_file, "r") as f:
            raw = yaml.safe_load(f) or {}
        
        # Extract all fields
        name = raw.get("name") or template_id.replace("_", " ").title()
        description = raw.get("description", "")
        greeting = raw.get("greeting", "")
        return_greeting = raw.get("return_greeting", "")
        
        # Load full prompt
        prompt_full = ""
        if "prompts" in raw and raw["prompts"].get("path"):
            prompt_full = load_prompt(agent_dir, raw["prompts"]["path"])
        elif raw.get("prompt"):
            prompt_full = load_prompt(agent_dir, raw["prompt"])
        
        # Get tools, voice, model
        tools = raw.get("tools", [])
        voice = raw.get("voice") or defaults.get("voice", {})
        model = raw.get("model") or defaults.get("model", {})
        template_vars = raw.get("template_vars") or defaults.get("template_vars", {})
        
        return {
            "status": "success",
            "template": {
                "id": template_id,
                "name": name,
                "description": description if isinstance(description, str) else str(description),
                "greeting": greeting if isinstance(greeting, str) else str(greeting),
                "return_greeting": return_greeting,
                "prompt": prompt_full,
                "tools": tools,
                "voice": voice,
                "model": model,
                "template_vars": template_vars,
                "handoff": raw.get("handoff", {}),
            },
        }
        
    except Exception as e:
        logger.error("Failed to load agent template %s: %s", template_id, e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load agent template: {str(e)}",
        )


@router.post(
    "/create",
    response_model=SessionAgentResponse,
    summary="Create Dynamic Agent",
    description="Create a new dynamic agent configuration for a session.",
    tags=["Agent Builder"],
)
async def create_dynamic_agent(
    config: DynamicAgentConfig,
    session_id: str,
    request: Request,
) -> SessionAgentResponse:
    """
    Create a dynamic agent for a specific session.
    
    This agent will be used instead of the default agent for this session.
    The configuration is stored in memory and can be modified at runtime.
    """
    start = time.time()
    
    # Validate tools exist
    initialize_tools()
    invalid_tools = [t for t in config.tools if t not in _TOOL_DEFINITIONS]
    if invalid_tools:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tools: {', '.join(invalid_tools)}. Use GET /tools to see available tools.",
        )
    
    # Build model config
    model_config = ModelConfig(
        deployment_id=config.model.deployment_id if config.model else "gpt-4o",
        temperature=config.model.temperature if config.model else 0.7,
        top_p=config.model.top_p if config.model else 0.9,
        max_tokens=config.model.max_tokens if config.model else 4096,
    )
    
    # Build voice config
    voice_config = VoiceConfig(
        name=config.voice.name if config.voice else "en-US-AvaMultilingualNeural",
        type=config.voice.type if config.voice else "azure-standard",
        style=config.voice.style if config.voice else "chat",
        rate=config.voice.rate if config.voice else "+0%",
    )
    
    # Build speech config (STT / VAD settings)
    speech_config = SpeechConfig(
        vad_silence_timeout_ms=config.speech.vad_silence_timeout_ms if config.speech else 800,
        use_semantic_segmentation=config.speech.use_semantic_segmentation if config.speech else False,
        candidate_languages=config.speech.candidate_languages if config.speech else ["en-US"],
        enable_diarization=config.speech.enable_diarization if config.speech else False,
        speaker_count_hint=config.speech.speaker_count_hint if config.speech else 2,
    )
    
    # Create the agent
    agent = UnifiedAgent(
        name=config.name,
        description=config.description,
        greeting=config.greeting,
        return_greeting=config.return_greeting,
        handoff=HandoffConfig(trigger=f"handoff_{config.name.lower().replace(' ', '_')}"),
        model=model_config,
        voice=voice_config,
        speech=speech_config,
        prompt_template=config.prompt,
        tool_names=config.tools,
        template_vars=config.template_vars or {},
        metadata={
            "source": "dynamic",
            "session_id": session_id,
            "created_at": time.time(),
        },
    )
    
    # Store in session
    set_session_agent(session_id, agent)
    
    logger.info(
        "Dynamic agent created | session=%s name=%s tools=%d",
        session_id,
        config.name,
        len(config.tools),
    )
    
    return SessionAgentResponse(
        session_id=session_id,
        agent_name=config.name,
        status="created",
        config={
            "name": config.name,
            "description": config.description,
            "greeting": config.greeting,
            "return_greeting": config.return_greeting,
            "prompt_preview": config.prompt[:200] + "..." if len(config.prompt) > 200 else config.prompt,
            "tools": config.tools,
            "model": model_config.to_dict(),
            "voice": voice_config.to_dict(),
            "speech": speech_config.to_dict(),
        },
        created_at=time.time(),
    )


@router.get(
    "/session/{session_id}",
    response_model=SessionAgentResponse,
    summary="Get Session Agent",
    description="Get the current dynamic agent configuration for a session.",
    tags=["Agent Builder"],
)
async def get_session_agent_config(
    session_id: str,
    request: Request,
) -> SessionAgentResponse:
    """Get the dynamic agent for a session."""
    agent = get_session_agent(session_id)
    
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"No dynamic agent configured for session {session_id}. Using default agent.",
        )
    
    return SessionAgentResponse(
        session_id=session_id,
        agent_name=agent.name,
        status="active",
        config={
            "name": agent.name,
            "description": agent.description,
            "greeting": agent.greeting,
            "return_greeting": agent.return_greeting,
            "prompt_preview": agent.prompt_template[:200] + "..." if len(agent.prompt_template) > 200 else agent.prompt_template,
            "prompt_full": agent.prompt_template,
            "tools": agent.tool_names,
            "model": agent.model.to_dict(),
            "voice": agent.voice.to_dict(),
            "template_vars": agent.template_vars,
        },
        created_at=agent.metadata.get("created_at"),
        modified_at=agent.metadata.get("modified_at"),
    )


@router.put(
    "/session/{session_id}",
    response_model=SessionAgentResponse,
    summary="Update Session Agent",
    description="Update the dynamic agent configuration for a session.",
    tags=["Agent Builder"],
)
async def update_session_agent(
    session_id: str,
    config: DynamicAgentConfig,
    request: Request,
) -> SessionAgentResponse:
    """
    Update the dynamic agent for a session.
    
    Creates a new agent if one doesn't exist.
    """
    # Validate tools exist
    initialize_tools()
    invalid_tools = [t for t in config.tools if t not in _TOOL_DEFINITIONS]
    if invalid_tools:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tools: {', '.join(invalid_tools)}",
        )
    
    existing = get_session_agent(session_id)
    created_at = existing.metadata.get("created_at") if existing else time.time()
    
    # Build configs
    model_config = ModelConfig(
        deployment_id=config.model.deployment_id if config.model else "gpt-4o",
        temperature=config.model.temperature if config.model else 0.7,
        top_p=config.model.top_p if config.model else 0.9,
        max_tokens=config.model.max_tokens if config.model else 4096,
    )
    
    voice_config = VoiceConfig(
        name=config.voice.name if config.voice else "en-US-AvaMultilingualNeural",
        type=config.voice.type if config.voice else "azure-standard",
        style=config.voice.style if config.voice else "chat",
        rate=config.voice.rate if config.voice else "+0%",
    )
    
    # Build speech config (STT / VAD settings)
    speech_config = SpeechConfig(
        vad_silence_timeout_ms=config.speech.vad_silence_timeout_ms if config.speech else 800,
        use_semantic_segmentation=config.speech.use_semantic_segmentation if config.speech else False,
        candidate_languages=config.speech.candidate_languages if config.speech else ["en-US"],
        enable_diarization=config.speech.enable_diarization if config.speech else False,
        speaker_count_hint=config.speech.speaker_count_hint if config.speech else 2,
    )
    
    # Create updated agent
    agent = UnifiedAgent(
        name=config.name,
        description=config.description,
        greeting=config.greeting,
        return_greeting=config.return_greeting,
        handoff=HandoffConfig(trigger=f"handoff_{config.name.lower().replace(' ', '_')}"),
        model=model_config,
        voice=voice_config,
        speech=speech_config,
        prompt_template=config.prompt,
        tool_names=config.tools,
        template_vars=config.template_vars or {},
        metadata={
            "source": "dynamic",
            "session_id": session_id,
            "created_at": created_at,
            "modified_at": time.time(),
        },
    )
    
    set_session_agent(session_id, agent)
    
    logger.info(
        "Dynamic agent updated | session=%s name=%s",
        session_id,
        config.name,
    )
    
    return SessionAgentResponse(
        session_id=session_id,
        agent_name=config.name,
        status="updated",
        config={
            "name": config.name,
            "description": config.description,
            "greeting": config.greeting,
            "return_greeting": config.return_greeting,
            "prompt_preview": config.prompt[:200] + "...",
            "tools": config.tools,
            "model": model_config.to_dict(),
            "voice": voice_config.to_dict(),
            "speech": speech_config.to_dict(),
        },
        created_at=created_at,
        modified_at=time.time(),
    )


@router.delete(
    "/session/{session_id}",
    summary="Reset Session Agent",
    description="Remove the dynamic agent for a session, reverting to default behavior.",
    tags=["Agent Builder"],
)
async def reset_session_agent(
    session_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Remove the dynamic agent for a session."""
    removed = remove_session_agent(session_id)
    
    if not removed:
        return {
            "status": "not_found",
            "message": f"No dynamic agent configured for session {session_id}",
            "session_id": session_id,
        }
    
    return {
        "status": "removed",
        "message": f"Dynamic agent removed for session {session_id}. Using default agent.",
        "session_id": session_id,
    }


@router.get(
    "/sessions",
    summary="List All Session Agents",
    description="List all sessions with dynamic agents configured.",
    tags=["Agent Builder"],
)
async def list_session_agents_endpoint() -> Dict[str, Any]:
    """List all sessions with dynamic agents."""
    all_agents = list_session_agents()
    sessions = []
    for session_id, agent in all_agents.items():
        sessions.append({
            "session_id": session_id,
            "agent_name": agent.name,
            "tools_count": len(agent.tool_names),
            "created_at": agent.metadata.get("created_at"),
            "modified_at": agent.metadata.get("modified_at"),
        })
    
    return {
        "status": "success",
        "total": len(sessions),
        "sessions": sessions,
    }


@router.post(
    "/reload-agents",
    summary="Reload Agent Templates",
    description="Re-discover and reload all agent templates from disk into the running application.",
    tags=["Agent Builder"],
)
async def reload_agent_templates(request: Request) -> Dict[str, Any]:
    """
    Reload agent templates from disk.
    
    This endpoint re-runs discover_agents() and updates app.state.unified_agents,
    making newly created or modified agents available without restarting the server.
    """
    from apps.artagent.backend.agents.loader import (
        discover_agents,
        build_handoff_map,
        build_agent_summaries,
    )
    
    start = time.time()
    
    try:
        # Re-discover agents from disk
        unified_agents = discover_agents()
        
        # Rebuild handoff map and summaries
        handoff_map = build_handoff_map(unified_agents)
        agent_summaries = build_agent_summaries(unified_agents)
        
        # Update app state
        request.app.state.unified_agents = unified_agents
        request.app.state.handoff_map = handoff_map
        request.app.state.agent_summaries = agent_summaries
        
        logger.info(
            "Agent templates reloaded",
            extra={
                "agent_count": len(unified_agents),
                "agents": list(unified_agents.keys()),
            },
        )
        
        return {
            "status": "success",
            "message": f"Reloaded {len(unified_agents)} agent templates",
            "agents": list(unified_agents.keys()),
            "agent_count": len(unified_agents),
            "response_time_ms": round((time.time() - start) * 1000, 2),
        }
        
    except Exception as e:
        logger.error("Failed to reload agent templates: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reload agent templates: {str(e)}",
        )
