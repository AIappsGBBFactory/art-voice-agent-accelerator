"""
Multi-agent system for VoiceLive with function calling capabilities.

This module defines specialized agents that can be dynamically switched
during conversations based on detected intents using OpenAI function calling.
"""

from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
from enum import Enum
import logging
import json

from azure.ai.voicelive.models import (
    RequestSession,
    ServerVad,
    AzureStandardVoice,
    Modality,
    InputAudioFormat,
    OutputAudioFormat,
    FunctionTool
)

logger = logging.getLogger(__name__)


class AgentType(Enum):
    """Available agent types for specialization."""
    ORCHESTRATOR = "orchestrator"
    CARDIOLOGY = "cardiology"
    ORTHOPEDIC = "orthopedic"
    NEUROLOGY = "neurology"
    DERMATOLOGY = "dermatology"
    PEDIATRICS = "pediatrics"
    GENERAL_PRACTICE = "general_practice"
    CUSTOMER_SERVICE = "customer_service"
    TECHNICAL_SUPPORT = "technical_support"


@dataclass
class AgentConfig:
    """Configuration for a specialized agent."""
    agent_type: AgentType
    name: str
    instructions: str
    voice: str
    tools: List[FunctionTool]
    greeting: Optional[str] = None
    handoff_keywords: Optional[List[str]] = None


class AgentRegistry:
    """Registry of all available agents and their configurations."""
    
    def __init__(self):
        self._agents: Dict[AgentType, AgentConfig] = {}
        self._initialize_agents()
    
    def _initialize_agents(self):
        """Initialize all agent configurations."""
        
        # Orchestrator Agent - Main routing agent with function calling
        self._agents[AgentType.ORCHESTRATOR] = AgentConfig(
            agent_type=AgentType.ORCHESTRATOR,
            name="Dr Pepper - AI Assistant Coordinator",
            voice="en-US-AvaNeural",  # Professional, welcoming female voice
            greeting="Hello! I'm Dr Pepper, your AI assistant coordinator. I'm here to help connect you with the right specialist for your needs. How can I assist you today?",
            instructions="""You are Dr Pepper, an AI Assistant Coordinator. Your role is to:

1. Listen carefully to user requests and determine the best specialist to handle their needs
2. Use function calling to transfer users to the appropriate specialist agent
3. Provide brief, helpful introductions before transfers
4. Handle general inquiries that don't require specialist knowledge

AVAILABLE SPECIALISTS:
- Cardiology: Heart conditions, chest pain, blood pressure, cardiac procedures
- Orthopedic: Bones, joints, injuries, fractures, sports medicine
- Neurology: Brain, nervous system, headaches, seizures, memory issues
- Dermatology: Skin conditions, rashes, acne, moles
- Pediatrics: Children's health, development, vaccines
- General Practice: General health questions, preventive care
- Customer Service: Account issues, billing, general support
- Technical Support: Software, hardware, troubleshooting

Always use the appropriate handoff function when you detect a specialist need.
Be warm, professional, and efficient in your routing decisions.""",
            tools=[
                FunctionTool(
                    name="handoff_to_cardiology",
                    description="Transfer to cardiology specialist for heart-related medical questions",
                    parameters={
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the handoff"
                            },
                            "patient_concern": {
                                "type": "string", 
                                "description": "Summary of the patient's main concern"
                            }
                        },
                        "required": ["reason", "patient_concern"]
                    }
                ),
                FunctionTool(
                    name="handoff_to_orthopedic",
                    description="Transfer to orthopedic specialist for bone, joint, and injury-related questions",
                    parameters={
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the handoff"
                            },
                            "patient_concern": {
                                "type": "string",
                                "description": "Summary of the patient's main concern"
                            }
                        },
                        "required": ["reason", "patient_concern"]
                    }
                ),
                FunctionTool(
                    name="handoff_to_neurology",
                    description="Transfer to neurology specialist for brain and nervous system questions",
                    parameters={
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the handoff"
                            },
                            "patient_concern": {
                                "type": "string",
                                "description": "Summary of the patient's main concern"
                            }
                        },
                        "required": ["reason", "patient_concern"]
                    }
                ),
                FunctionTool(
                    name="handoff_to_dermatology",
                    description="Transfer to dermatology specialist for skin-related questions",
                    parameters={
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the handoff"
                            },
                            "patient_concern": {
                                "type": "string",
                                "description": "Summary of the patient's main concern"
                            }
                        },
                        "required": ["reason", "patient_concern"]
                    }
                ),
                FunctionTool(
                    name="handoff_to_pediatrics",
                    description="Transfer to pediatrics specialist for children's health questions",
                    parameters={
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the handoff"
                            },
                            "patient_concern": {
                                "type": "string",
                                "description": "Summary of the patient's main concern"
                            }
                        },
                        "required": ["reason", "patient_concern"]
                    }
                ),
                FunctionTool(
                    name="handoff_to_general_practice",
                    description="Transfer to general practice for general medical questions",
                    parameters={
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the handoff"
                            },
                            "patient_concern": {
                                "type": "string",
                                "description": "Summary of the patient's main concern"
                            }
                        },
                        "required": ["reason", "patient_concern"]
                    }
                ),
                FunctionTool(
                    name="handoff_to_customer_service",
                    description="Transfer to customer service for account, billing, or general support questions",
                    parameters={
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the handoff"
                            },
                            "customer_issue": {
                                "type": "string",
                                "description": "Summary of the customer's issue"
                            }
                        },
                        "required": ["reason", "customer_issue"]
                    }
                ),
                FunctionTool(
                    name="handoff_to_technical_support",
                    description="Transfer to technical support for software or hardware issues",
                    parameters={
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the handoff"
                            },
                            "technical_issue": {
                                "type": "string",
                                "description": "Summary of the technical issue"
                            }
                        },
                        "required": ["reason", "technical_issue"]
                    }
                )
            ]
        )
        
        # Cardiology Specialist
        self._agents[AgentType.CARDIOLOGY] = AgentConfig(
            agent_type=AgentType.CARDIOLOGY,
            name="Dr. Sarah Chen - Cardiology Specialist",
            voice="en-US-JennyNeural",  # Warm, caring female voice for medical specialist
            greeting="Hello, I'm Dr. Sarah Chen, your cardiology specialist. I'm here to help with any heart-related concerns you may have.",
            instructions="""You are Dr. Sarah Chen, a Cardiology Specialist. You ONLY handle heart-related medical questions and procedures.

YOUR EXPERTISE INCLUDES:
- Arrhythmias and heart rhythm disorders
- Heart attacks and coronary artery disease
- Chest pain evaluation
- Blood pressure management
- Cardiac procedures and interventions
- Heart medications and treatments
- Heart failure management
- Preventive cardiology

IMPORTANT: If a patient asks about non-cardiac topics, politely redirect them back to cardiac concerns or suggest they speak with the coordinator for other specialists.

Always speak confidently about cardiac matters, use appropriate medical terminology when helpful, and provide clear, actionable guidance. Remember that you're providing educational information, not replacing in-person medical care.""",
            tools=[],
            handoff_keywords=["orthopedic", "bone", "joint", "neurology", "brain", "skin", "dermatology", "children", "pediatric"]
        )
        
        # Orthopedic Specialist
        self._agents[AgentType.ORTHOPEDIC] = AgentConfig(
            agent_type=AgentType.ORTHOPEDIC,
            name="Dr. Michael Roberts - Orthopedic Specialist", 
            voice="en-US-BrianNeural",  # Confident, sports-oriented male voice
            greeting="Hi there! I'm Dr. Michael Roberts, your orthopedic specialist. I'm here to help with any bone, joint, or injury-related concerns.",
            instructions="""You are Dr. Michael Roberts, an Orthopedic Specialist. You handle musculoskeletal conditions and injuries.

YOUR EXPERTISE INCLUDES:
- Bone fractures and injuries
- Joint problems (knee, hip, shoulder, etc.)
- Sports medicine and athletic injuries
- Arthritis and joint pain
- Spine conditions and back pain
- Muscle strains and sprains
- Orthopedic procedures and surgeries
- Physical therapy recommendations

IMPORTANT: If a patient asks about non-orthopedic topics, politely redirect them to orthopedic concerns or suggest they speak with the coordinator.

Provide practical advice on injury prevention, recovery, and when to seek immediate care. Use clear language and focus on helping patients understand their conditions.""",
            tools=[],
            handoff_keywords=["heart", "cardiac", "brain", "neurology", "skin", "dermatology", "children", "pediatric"]
        )
        
        # Neurology Specialist
        self._agents[AgentType.NEUROLOGY] = AgentConfig(
            agent_type=AgentType.NEUROLOGY,
            name="Dr. Emily Watson - Neurology Specialist",
            voice="en-US-AriaNeural",  # Intelligent, analytical female voice
            greeting="Hello, I'm Dr. Emily Watson, your neurology specialist. I'm here to help with any brain or nervous system concerns.",
            instructions="""You are Dr. Emily Watson, a Neurology Specialist. You handle brain, nervous system, and neurological conditions.

YOUR EXPERTISE INCLUDES:
- Headaches and migraines
- Seizures and epilepsy
- Memory issues and cognitive concerns
- Stroke and TIA evaluation
- Peripheral neuropathy
- Movement disorders
- Sleep disorders with neurological basis
- Neurological examinations and tests

IMPORTANT: If a patient asks about non-neurological topics, politely redirect them to neurological concerns or suggest they speak with the coordinator.

Be sensitive when discussing neurological conditions, provide clear explanations, and emphasize the importance of proper neurological evaluation when appropriate.""",
            tools=[],
            handoff_keywords=["heart", "cardiac", "bone", "joint", "skin", "dermatology", "children", "pediatric"]
        )
        
        # Customer Service Agent
        self._agents[AgentType.CUSTOMER_SERVICE] = AgentConfig(
            agent_type=AgentType.CUSTOMER_SERVICE,
            name="Maria Santos - Customer Service Representative",
            voice="en-US-CoraNeural",  # Friendly, helpful customer service voice
            greeting="Hello! I'm Sarah Johnson from customer service. I'm here to help with any account, billing, or general service questions you may have.",
            instructions="""You are Sarah Johnson, a Customer Service Representative. You handle account management, billing, and general customer support.

YOUR EXPERTISE INCLUDES:
- Account management and settings
- Billing inquiries and payment issues
- Service plan information
- General product information
- Order status and tracking
- Refunds and cancellations
- Account security and access issues

Always be courteous, patient, and solution-focused. If you cannot resolve an issue, clearly explain the limitations and offer to escalate or provide alternative solutions.""",
            tools=[],
            handoff_keywords=["medical", "health", "technical", "software", "hardware"]
        )
        
        # Technical Support Agent
        self._agents[AgentType.TECHNICAL_SUPPORT] = AgentConfig(
            agent_type=AgentType.TECHNICAL_SUPPORT,
            name="Alex Rodriguez - Technical Support Specialist",
            voice="en-US-DavisNeural",  # Clear, tech-savvy male voice 
            greeting="Hi! I'm Alex Kim from technical support. I'm here to help you resolve any software or hardware issues you're experiencing.",
            instructions="""You are Alex Kim, a Technical Support Specialist. You help customers resolve software and hardware issues.

YOUR EXPERTISE INCLUDES:
- Software troubleshooting and configuration
- Hardware connectivity and setup
- System performance optimization
- Application errors and bugs
- Network and connectivity issues
- Device compatibility
- Software installation and updates
- User account and access problems

Be patient and methodical in your troubleshooting approach. Ask clarifying questions to understand the exact issue and provide step-by-step solutions.""",
            tools=[],
            handoff_keywords=["medical", "health", "billing", "account", "payment"]
        )
        
        # Dermatology Specialist
        self._agents[AgentType.DERMATOLOGY] = AgentConfig(
            agent_type=AgentType.DERMATOLOGY,
            name="Dr. Lisa Park - Dermatology Specialist",
            voice="en-US-EmmaNeural",  # Gentle, reassuring female voice for skin conditions
            greeting="Hello! I'm Dr. Lisa Park, your dermatology specialist. I'm here to help with any skin, hair, or nail concerns you may have.",
            instructions="""You are Dr. Lisa Park, a Dermatology Specialist. You handle skin, hair, and nail conditions.

YOUR EXPERTISE INCLUDES:
- Acne and skin blemishes
- Rashes and skin irritations
- Moles and skin lesions
- Eczema and psoriasis
- Hair loss and scalp conditions
- Nail disorders
- Skin cancer screening advice
- Cosmetic dermatology concerns

IMPORTANT: If a patient asks about non-dermatological topics, politely redirect them to skin concerns or suggest they speak with the coordinator.

Be reassuring and thorough when discussing skin conditions. Many patients are self-conscious about skin issues, so maintain a supportive and understanding tone.""",
            tools=[],
            handoff_keywords=["heart", "cardiac", "bone", "joint", "brain", "neurology", "children", "pediatric"]
        )
        
        # Pediatrics Specialist
        self._agents[AgentType.PEDIATRICS] = AgentConfig(
            agent_type=AgentType.PEDIATRICS,
            name="Dr. James Wilson - Pediatrics Specialist",
            voice="en-US-GuyNeural",  # Warm, trustworthy male voice for children's health
            greeting="Hi there! I'm Dr. James Wilson, your pediatrics specialist. I'm here to help with any questions about children's health and development.",
            instructions="""You are Dr. James Wilson, a Pediatrics Specialist. You handle children's health and development from infancy through adolescence.

YOUR EXPERTISE INCLUDES:
- Child development milestones
- Pediatric illnesses and infections
- Childhood vaccines and immunizations
- Growth and nutrition concerns
- Behavioral and learning issues
- Adolescent health concerns
- Child safety and injury prevention
- Newborn and infant care

IMPORTANT: If a patient asks about adult health topics, politely redirect them to pediatric concerns or suggest they speak with the coordinator.

Use language that's appropriate whether speaking to parents or directly to young patients. Be patient, caring, and provide clear explanations about children's health.""",
            tools=[],
            handoff_keywords=["heart", "cardiac", "bone", "joint", "brain", "neurology", "skin", "dermatology"]
        )
        
        # General Practice Specialist
        self._agents[AgentType.GENERAL_PRACTICE] = AgentConfig(
            agent_type=AgentType.GENERAL_PRACTICE,
            name="Dr. Robert Kim - General Practice Physician",
            voice="en-US-ChristopherNeural",  # Professional, knowledgeable male voice
            greeting="Hello! I'm Dr. Robert Kim, your general practice physician. I'm here to help with general health questions and preventive care.",
            instructions="""You are Dr. Robert Kim, a General Practice Physician. You handle general health questions, preventive care, and coordinate overall patient wellness.

YOUR EXPERTISE INCLUDES:
- General health assessments
- Preventive care and screenings
- Common illnesses and conditions
- Health maintenance and wellness
- Medication management
- Lifestyle and diet advice
- Mental health awareness
- When to seek specialist care

IMPORTANT: For complex specialist conditions, acknowledge the concern but recommend appropriate specialist consultation.

Provide comprehensive, practical health advice while being mindful of when to refer to specialists. Focus on overall health and wellness guidance.""",
            tools=[],
            handoff_keywords=["technical", "software", "hardware", "billing", "account"]
        )
    
    def get_agent(self, agent_type: AgentType) -> AgentConfig:
        """Get agent configuration by type."""
        return self._agents[agent_type]
    
    def get_all_agents(self) -> Dict[AgentType, AgentConfig]:
        """Get all agent configurations."""
        return self._agents.copy()
    
    def get_agent_by_function_name(self, function_name: str) -> Optional[AgentType]:
        """Map function call names to agent types."""
        function_to_agent = {
            "handoff_to_cardiology": AgentType.CARDIOLOGY,
            "handoff_to_orthopedic": AgentType.ORTHOPEDIC,
            "handoff_to_neurology": AgentType.NEUROLOGY,
            "handoff_to_dermatology": AgentType.DERMATOLOGY,
            "handoff_to_pediatrics": AgentType.PEDIATRICS,
            "handoff_to_general_practice": AgentType.GENERAL_PRACTICE,
            "handoff_to_customer_service": AgentType.CUSTOMER_SERVICE,
            "handoff_to_technical_support": AgentType.TECHNICAL_SUPPORT,
        }
        return function_to_agent.get(function_name)


class SessionManager:
    """Manages session configurations and agent switching."""
    
    def __init__(self, agent_registry: AgentRegistry):
        self.agent_registry = agent_registry
        self.current_agent: Optional[AgentType] = None
        self.conversation_context: Dict[str, Any] = {}
    
    def create_session_config(
        self, 
        agent_type: AgentType,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> RequestSession:
        """Create a session configuration for the specified agent."""
        agent_config = self.agent_registry.get_agent(agent_type)
        
        # Create voice configuration
        voice_config: Union[AzureStandardVoice, str]
        if agent_config.voice.startswith("en-US-") or "-" in agent_config.voice:
            voice_config = AzureStandardVoice(name=agent_config.voice, type="azure-standard")
        else:
            voice_config = agent_config.voice
        
        # Create turn detection configuration
        turn_detection_config = ServerVad(
            threshold=kwargs.get("vad_threshold", 0.5),
            prefix_padding_ms=kwargs.get("prefix_padding_ms", 300),
            silence_duration_ms=kwargs.get("silence_duration_ms", 500)
        )
        
        # Modify instructions based on context for specialist agents
        instructions = agent_config.instructions
        if context and agent_type != AgentType.ORCHESTRATOR:
            # Add context-aware introduction for specialist agents
            user_concern = context.get('user_concern', 'your inquiry')
            handoff_reason = context.get('handoff_reason', 'User request')
            
            context_intro = f"You have just been connected to assist with {user_concern}. The user was transferred to you because: {handoff_reason}. "
            if agent_config.greeting:
                context_intro += f"Please start by introducing yourself: '{agent_config.greeting}' Then ask how you can specifically help them with their concern. "
            
            instructions = context_intro + instructions
        
        # Create session configuration with proper tool handling
        session_kwargs = {
            "modalities": [Modality.TEXT, Modality.AUDIO],
            "instructions": instructions,
            "voice": voice_config,
            "input_audio_format": InputAudioFormat.PCM16,
            "output_audio_format": OutputAudioFormat.PCM16,
            "turn_detection": turn_detection_config,
        }
        
        # Only add tools if they exist and are properly formatted
        if agent_config.tools is not None and len(agent_config.tools) > 0:
            # Validate that all tools have required fields
            valid_tools = []
            for tool in agent_config.tools:
                if isinstance(tool, FunctionTool) and tool.name and tool.name.strip():
                    valid_tools.append(tool)
                    logger.debug(f"Valid tool found: {tool.name}")
                else:
                    logger.warning(f"Invalid tool format found: {tool}")
            
            if valid_tools:
                session_kwargs["tools"] = valid_tools
                session_kwargs["tool_choice"] = "auto"
                logger.info(f"Including {len(valid_tools)} tools in session")
                
                # Log the first tool for debugging
                if logger.isEnabledFor(logging.DEBUG):
                    first_tool = valid_tools[0]
                    logger.debug(f"First tool structure: name={first_tool.name}, description={first_tool.description}")
            else:
                logger.warning("No valid tools found, creating session without tools")
        else:
            logger.debug(f"Agent {agent_config.name} has no tools configured")
        
        session_config = RequestSession(**session_kwargs)
        
        self.current_agent = agent_type
        logger.info(f"Created session config for agent: {agent_config.name}")
        
        # Debug logging for session configuration
        logger.debug(f"Session config details:")
        logger.debug(f"  - Agent: {agent_config.name}")
        logger.debug(f"  - Voice: {voice_config}")
        logger.debug(f"  - Tools count: {len(session_kwargs.get('tools', []))}")
        logger.debug(f"  - Tool choice: {session_kwargs.get('tool_choice', 'None')}")
        
        return session_config
    
    def get_current_agent(self) -> Optional[AgentConfig]:
        """Get the current active agent configuration."""
        if self.current_agent:
            return self.agent_registry.get_agent(self.current_agent)
        return None
    
    def set_conversation_context(self, key: str, value: Any):
        """Set conversation context for handoffs."""
        self.conversation_context[key] = value
    
    def get_conversation_context(self, key: str) -> Any:
        """Get conversation context."""
        return self.conversation_context.get(key)
    
    def clear_conversation_context(self):
        """Clear conversation context."""
        self.conversation_context.clear()