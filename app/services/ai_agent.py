"""
AI Agent Service using LangGraph and Gemini for intelligent conversation handling
"""
import json
import logging
from typing import Dict, Any, Optional, List, TypedDict, Union, Annotated
from datetime import datetime
from enum import Enum

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from app.config import get_settings
from app.models import ConversationState, Customer, Order, Group, Product, ProductVariant, BusinessType
from app.services.inventory_service import get_inventory_service
from app.services.analytics_service import get_analytics_service
from app.services.business_config_service import get_business_config_service
from app.services.rate_limiter import get_rate_limiter, rate_limited_api_call
from app.services.api_monitor import get_api_monitor
# Enhanced memory service removed - using pure LangGraph memory management
from app.services.cache_service import get_cache_service
from app.utils.security import SecurityValidator, ai_circuit_breaker
from sqlalchemy.orm import Session

settings = get_settings()
logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    """
    Enhanced state for AI agent conversation flow using LangGraph v0.3+ best practices
    
    This replaces the custom ConversationSession system with LangGraph's built-in state management
    """
    # LangGraph v0.3+ pattern: Use Annotated with add_messages for proper message handling
    messages: Annotated[List[BaseMessage], add_messages]
    
    # Customer and business context
    customer_id: int
    group_id: int
    
    # Conversation flow state
    current_intent: str
    conversation_state: str
    last_action: str
    
    # Enhanced conversation context (replaces ConversationSession context)
    context: Dict[str, Any]
    order_data: Optional[Dict[str, Any]]
    
    # LangGraph persistence fields
    thread_id: str  # For conversation threading
    session_metadata: Dict[str, Any]  # Session information
    
    # State validation and recovery
    state_version: str  # For state migration/compatibility
    error_context: Optional[Dict[str, Any]]  # For error recovery
    
    # Conversation history management (LangGraph pattern)
    conversation_summary: Optional[str]  # For long conversation summarization
    total_messages: int  # Message count tracking

class Intent(str, Enum):
    """Customer intents the AI can detect"""
    PLACE_ORDER = "place_order"
    TRACK_ORDER = "track_order"
    CANCEL_ORDER = "cancel_order"
    CONTACT_SUPPORT = "contact_support"
    MPESA_PAYMENT = "mpesa_payment"
    CASH_PAYMENT = "cash_payment"
    PAYMENT_INQUIRY = "payment_inquiry"
    PAYMENT_CONFIRMATION = "payment_confirmation"
    PAYMENT_SELECTION = "payment_selection"
    PRODUCT_INQUIRY = "product_inquiry"
    GENERAL_INQUIRY = "general_inquiry"
    UNKNOWN = "unknown"

class OrderBotAgent:
    """
    LangGraph-based AI agent for handling WhatsApp order conversations
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.settings = settings
        
        # Initialize services (enhanced memory removed - using pure LangGraph memory)
        self.inventory_service = get_inventory_service(db)
        self.analytics_service = get_analytics_service(db)
        self.business_config_service = get_business_config_service(db)
        self._cache_service = None
        self.rate_limiter = get_rate_limiter()
        self.api_monitor = get_api_monitor(db)
        
        # Initialize Gemini model
        if not self.settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY not set. AI agent will be disabled.")
            self.llm = None
            self.graph = None
            return
        
        try:
            self.llm = ChatGoogleGenerativeAI(
                model=self.settings.ai_model_name,
                google_api_key=self.settings.gemini_api_key,
                temperature=self.settings.ai_temperature,
                max_output_tokens=self.settings.ai_max_tokens,
                # Add safety settings to prevent blocks (use numeric values)
                safety_settings={
                    1: 4,  # HATE -> BLOCK_NONE
                    2: 4,  # HARASSMENT -> BLOCK_NONE 
                    3: 4,  # SEXUAL -> BLOCK_NONE
                    7: 4   # DANGEROUS -> BLOCK_NONE
                }
            )
            logger.info(f"✅ Gemini AI model '{self.settings.ai_model_name}' initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini model: {str(e)}")
            self.llm = None
            self.graph = None
            return
        
        # LangGraph v0.3+ pattern: Use MemorySaver checkpointer for conversation persistence
        # This replaces custom ConversationSession and EnhancedMemoryService
        self.checkpointer = MemorySaver() if self.settings.ai_conversation_memory else None
        
        # Build the conversation graph
        self.graph = self._build_conversation_graph()
        
    async def _get_cache_service(self):
        """Lazy cache service initialization"""
        if self._cache_service is None:
            self._cache_service = await get_cache_service()
        return self._cache_service
        
    def _build_conversation_graph(self) -> StateGraph:
        """Build the LangGraph conversation flow"""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("intent_detection", self._detect_intent_node)
        workflow.add_node("process_order", self._process_order_node)
        workflow.add_node("track_order", self._track_order_node)
        workflow.add_node("handle_payment", self._handle_payment_node)
        workflow.add_node("handle_product_inquiry", self._handle_product_inquiry_node)
        workflow.add_node("general_response", self._general_response_node)
        workflow.add_node("error_handler", self._error_handler_node)
        
        # Add edges/routing
        workflow.set_entry_point("intent_detection")
        
        workflow.add_conditional_edges(
            "intent_detection",
            self._route_by_intent,
            {
                Intent.PLACE_ORDER: "process_order",
                Intent.TRACK_ORDER: "track_order",
                Intent.CANCEL_ORDER: "track_order",
                Intent.MPESA_PAYMENT: "handle_payment",
                Intent.CASH_PAYMENT: "handle_payment",
                Intent.PAYMENT_INQUIRY: "handle_payment",
                Intent.PAYMENT_CONFIRMATION: "handle_payment",
                Intent.PAYMENT_SELECTION: "handle_payment",
                Intent.PRODUCT_INQUIRY: "handle_product_inquiry",
                Intent.CONTACT_SUPPORT: "general_response",
                Intent.GENERAL_INQUIRY: "general_response",
                Intent.UNKNOWN: "general_response"
            }
        )
        
        # All processing nodes lead to END
        workflow.add_edge("process_order", END)
        workflow.add_edge("track_order", END)
        workflow.add_edge("handle_payment", END)
        workflow.add_edge("handle_product_inquiry", END)
        workflow.add_edge("general_response", END)
        workflow.add_edge("error_handler", END)
        
        return workflow.compile(checkpointer=self.checkpointer)
    
    @rate_limited_api_call(get_rate_limiter())
    async def _rate_limited_llm_call(self, messages: List, estimated_tokens: int = 1000):
        """
        Rate-limited wrapper for LLM API calls with monitoring
        """
        start_time = datetime.utcnow()
        success = True
        error_message = None
        error_code = None
        actual_tokens = 0
        
        try:
            # Validate messages before API call
            if not messages:
                raise ValueError("No messages provided to LLM")
            
            # Enhanced message validation based on Gemini API requirements
            valid_messages = self._validate_and_clean_messages(messages)
            
            if not valid_messages:
                logger.error(f"All {len(messages)} messages are empty or invalid after validation")
                # Create a fallback message instead of raising an error
                from langchain_core.messages import HumanMessage
                valid_messages = [HumanMessage(content="Please help me with my order.")]
            
            # Additional debug logging for Gemini API calls
            logger.debug(f"Sending {len(valid_messages)} messages to Gemini API")
            for i, msg in enumerate(valid_messages):
                logger.debug(f"Message {i}: {type(msg).__name__} - Content: {getattr(msg, 'content', 'NO_CONTENT')[:100]}")
                
            # Final validation: ensure all messages have content
            final_messages = []
            for msg in valid_messages:
                if hasattr(msg, 'content') and msg.content and str(msg.content).strip():
                    final_messages.append(msg)
                else:
                    logger.warning(f"Dropping invalid message: {type(msg).__name__} with content: {repr(getattr(msg, 'content', 'NO_CONTENT'))}")
            
            # Ensure we have at least one valid message
            if not final_messages:
                logger.error("No valid messages for Gemini after final validation")
                from langchain_core.messages import HumanMessage
                final_messages = [HumanMessage(content="Hello, please help me.")]
            
            # Use invoke for synchronous call wrapped in rate limiter
            response = self.llm.invoke(final_messages)
            
            # Record successful call for circuit breaker
            ai_circuit_breaker.record_success()
            
            # Check for empty response due to safety filtering
            if not response or not hasattr(response, 'content') or not response.content.strip():
                logger.warning("Gemini returned empty response - likely due to safety filtering")
                # Return a safe fallback response
                from langchain_core.messages import AIMessage
                response = AIMessage(content="I apologize, but I cannot process that request. Please try rephrasing or contact support for assistance.")
            
            # Estimate actual tokens used (rough approximation)
            prompt_text = " ".join([msg.content for msg in valid_messages])
            actual_tokens = len(prompt_text.split()) * 1.3  # Rough token estimation
            
            return response
            
        except Exception as e:
            success = False
            error_message = str(e)
            
            # Record failure for circuit breaker
            ai_circuit_breaker.record_failure()
            
            if "429" in error_message:
                error_code = "rate_limit_exceeded"
            elif "quota" in error_message.lower():
                error_code = "quota_exceeded"
            else:
                error_code = "api_error"
            
            logger.error(f"LLM API call failed: {str(e)}")
            
            # Return a more helpful fallback response based on error type
            class FallbackResponse:
                def __init__(self, content):
                    self.content = content
            
            if "quota" in error_message.lower() or "429" in error_message:
                fallback_content = "I'm currently at capacity due to high demand. Let me help you with a quick response - what specific items would you like to order? Please provide: item names, quantities, and any size/color preferences."
            else:
                fallback_content = "I'm experiencing a temporary issue. Please try again in a moment or contact support if the problem persists."
                
            return FallbackResponse(fallback_content)
            
        finally:
            # Log the API call for monitoring
            try:
                response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
                
                await self.api_monitor.log_api_call(
                    api_provider="gemini",
                    api_method="chat_completion",
                    success=success,
                    tokens_used=int(actual_tokens),
                    estimated_tokens=estimated_tokens,
                    response_time_ms=response_time,
                    error_message=error_message,
                    error_code=error_code
                )
            except Exception as log_error:
                logger.error(f"Failed to log API call: {log_error}")
    
    async def _detect_intent_node(self, state: AgentState) -> AgentState:
        """Detect customer intent using Gemini AI"""
        try:
            messages = state["messages"]
            latest_message = messages[-1] if messages else None
            
            if not latest_message or not isinstance(latest_message, HumanMessage):
                state["current_intent"] = Intent.UNKNOWN
                return state
            
            # Get customer and group context
            customer = self.db.query(Customer).filter(Customer.id == state["customer_id"]).first()
            group = self.db.query(Group).filter(Group.id == state["group_id"]).first()
            
            # Create context-aware prompt
            system_prompt = self._build_intent_detection_prompt(customer, group, state)
            
            # Use Gemini to detect intent with rate limiting
            # Since we have convert_system_message_to_human=True, let's use HumanMessage directly
            combined_prompt = f"{system_prompt}\n\nCustomer message: {latest_message.content}"
            response = await self._rate_limited_llm_call([
                HumanMessage(content=combined_prompt)
            ], estimated_tokens=len(combined_prompt))
            
            # Parse intent from response
            detected_intent = self._parse_intent_from_response(response.content)
            state["current_intent"] = detected_intent
            
            if self.settings.ai_debug_mode:
                logger.info(f"Detected intent: {detected_intent} for message: {latest_message.content[:50]}...")
                
            return state
            
        except Exception as e:
            logger.error(f"Error in intent detection: {str(e)}")
            state["current_intent"] = Intent.UNKNOWN
            return state
    
    async def _process_order_node(self, state: AgentState) -> AgentState:
        """Enhanced order processing with inventory checking and business-specific handling"""
        try:
            messages = state["messages"]
            latest_message = messages[-1] if messages else None
            
            if not latest_message:
                return state
            
            # Get business context
            group = self.db.query(Group).filter(Group.id == state["group_id"]).first()
            business_type = group.business_type if group else BusinessType.GENERAL
            
            # Extract order details using business-specific AI
            order_details = await self._extract_order_details_enhanced(
                latest_message.content, state, business_type
            )
            
            if order_details and order_details.get("items"):
                # Check inventory availability for each item
                availability_check = self._check_order_availability(order_details, state["group_id"])
                
                if availability_check["all_available"]:
                    # Calculate intelligent pricing
                    pricing_info = self._calculate_intelligent_pricing(order_details, state["customer_id"])
                    order_details.update(pricing_info)
                    
                    state["order_data"] = order_details
                    state["last_action"] = "order_extracted"
                    state["conversation_state"] = ConversationState.AWAITING_PAYMENT.value
                else:
                    # Some items unavailable - provide alternatives
                    alternatives = self._suggest_alternatives(availability_check["unavailable_items"], state["customer_id"])
                    state["order_data"] = {
                        "availability_issues": availability_check,
                        "suggested_alternatives": alternatives
                    }
                    state["last_action"] = "inventory_issues_found"
            else:
                # Use business-specific clarification
                clarification_type = self._get_business_specific_clarification(business_type, latest_message.content)
                state["order_data"] = {"clarification_type": clarification_type}
                state["last_action"] = "order_clarification_needed"
                
            return state
            
        except Exception as e:
            logger.error(f"Error processing order: {str(e)}")
            state["last_action"] = "error"
            return state
    
    def _track_order_node(self, state: AgentState) -> AgentState:
        """Handle order tracking and cancellation"""
        try:
            customer_id = state["customer_id"]
            intent = state["current_intent"]
            
            # Get customer's recent orders
            recent_orders = self.db.query(Order).filter(
                Order.customer_id == customer_id
            ).order_by(Order.created_at.desc()).limit(3).all()
            
            if intent == Intent.CANCEL_ORDER and recent_orders:
                # Find the most recent pending order to cancel
                pending_order = next((o for o in recent_orders if o.status.value == "pending"), None)
                if pending_order:
                    state["order_data"] = {
                        "action": "cancel",
                        "order_id": pending_order.id,
                        "order_number": pending_order.order_number
                    }
            else:
                # Prepare order tracking data
                state["order_data"] = {
                    "action": "track",
                    "orders": [
                        {
                            "order_number": o.order_number,
                            "status": o.status.value,
                            "created_at": o.created_at.isoformat(),
                            "total_amount": float(o.total_amount) if o.total_amount else 0
                        } for o in recent_orders
                    ]
                }
            
            state["last_action"] = "orders_retrieved"
            return state
            
        except Exception as e:
            logger.error(f"Error tracking orders: {str(e)}")
            state["last_action"] = "error"
            return state
    
    async def _handle_payment_node(self, state: AgentState) -> AgentState:
        """Enhanced payment handling - distinguishes questions from confirmations"""
        try:
            messages = state["messages"]
            latest_message = messages[-1] if messages else None
            intent = state["current_intent"]
            
            if not latest_message:
                state["last_action"] = "error"
                return state
                
            # Get business context
            customer = self.db.query(Customer).filter(Customer.id == state["customer_id"]).first()
            group = self.db.query(Group).filter(Group.id == state["group_id"]).first()
            
            if intent == Intent.PAYMENT_INQUIRY:
                # Handle payment questions (e.g., "Can I pay with M-Pesa?")
                response = await self._generate_payment_inquiry_response(latest_message.content, group)
                state["order_data"] = {
                    "ai_response": response,
                    "response_type": "payment_inquiry"
                }
                state["last_action"] = "payment_inquiry_handled"
                
            elif intent == Intent.PAYMENT_CONFIRMATION:
                # Handle M-Pesa confirmations
                transaction_details = self._extract_mpesa_details(latest_message.content)
                state["order_data"] = {
                    "payment_method": "mpesa",
                    "transaction_details": transaction_details
                }
                state["last_action"] = "payment_processed"
                
            elif intent == Intent.PAYMENT_SELECTION:
                # Handle numbered selections (1, 2, 3)
                selection = latest_message.content.strip()
                if selection == "1":
                    state["order_data"] = {"payment_method": "mpesa_selected"}
                elif selection == "2":
                    state["order_data"] = {"payment_method": "cash_on_delivery"}
                elif selection == "3":
                    state["order_data"] = {"payment_method": "cancel_order"}
                state["last_action"] = "payment_selection_processed"
                
            elif intent == Intent.CASH_PAYMENT:
                state["order_data"] = {
                    "payment_method": "cash_on_delivery"
                }
                state["last_action"] = "payment_processed"
            
            return state
            
        except Exception as e:
            logger.error(f"Error handling payment: {str(e)}")
            state["last_action"] = "error"
            return state
    
    async def _general_response_node(self, state: AgentState) -> AgentState:
        """Generate general AI responses for inquiries and support"""
        try:
            messages = state["messages"]
            latest_message = messages[-1] if messages else None
            
            if not latest_message:
                return state
            
            # Generate contextual response using Gemini
            customer = self.db.query(Customer).filter(Customer.id == state["customer_id"]).first()
            group = self.db.query(Group).filter(Group.id == state["group_id"]).first()
            
            response = await self._generate_contextual_response(latest_message.content, customer, group, state)
            
            state["order_data"] = {
                "ai_response": response,
                "response_type": "general"
            }
            state["last_action"] = "ai_response_generated"
            
            return state
            
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            state["last_action"] = "error"
            return state
    
    async def _handle_product_inquiry_node(self, state: AgentState) -> AgentState:
        """Handle product availability and information questions - Generic for all SMEs"""
        try:
            messages = state["messages"]
            latest_message = messages[-1] if messages else None
            
            if not latest_message:
                state["last_action"] = "error"
                return state
            
            # Get business context
            customer = self.db.query(Customer).filter(Customer.id == state["customer_id"]).first()
            group = self.db.query(Group).filter(Group.id == state["group_id"]).first()
            
            # Generate product inquiry response using enhanced prompt
            response = await self._generate_product_inquiry_response(
                latest_message.content, customer, group, state
            )
            
            state["order_data"] = {
                "ai_response": response,
                "response_type": "product_inquiry"
            }
            state["last_action"] = "product_inquiry_handled"
            
            return state
            
        except Exception as e:
            logger.error(f"Error handling product inquiry: {str(e)}")
            state["last_action"] = "error"
            state["order_data"] = {
                "ai_response": "I'm sorry, I'm having trouble with your product question right now. Please contact our support for assistance.",
                "response_type": "error"
            }
            return state
    
    def _error_handler_node(self, state: AgentState) -> AgentState:
        """Handle errors gracefully"""
        state["last_action"] = "error_handled"
        state["order_data"] = {
            "error_message": "I apologize, but I encountered an error. Please try again or contact support.",
            "response_type": "error"
        }
        return state
    
    def _route_by_intent(self, state: AgentState) -> str:
        """Route to appropriate node based on detected intent"""
        intent = state.get("current_intent", Intent.UNKNOWN)
        
        if intent in [Intent.PLACE_ORDER]:
            return Intent.PLACE_ORDER
        elif intent in [Intent.TRACK_ORDER, Intent.CANCEL_ORDER]:
            return Intent.TRACK_ORDER
        elif intent in [Intent.MPESA_PAYMENT, Intent.CASH_PAYMENT, Intent.PAYMENT_INQUIRY, 
                       Intent.PAYMENT_CONFIRMATION, Intent.PAYMENT_SELECTION]:
            return Intent.MPESA_PAYMENT
        elif intent in [Intent.PRODUCT_INQUIRY]:
            return Intent.PRODUCT_INQUIRY
        else:
            return Intent.GENERAL_INQUIRY
    
    def _build_intent_detection_prompt(self, customer: Customer, group: Group, state: AgentState) -> str:
        """Build enhanced intent detection prompt using 2024 best practices - Generic for all SMEs"""
        try:
            group_name = group.name if group and group.name else "Business"
            business_type = self._get_business_type_str(group.business_type) if group and group.business_type else "retail"
            conversation_state = state.get('conversation_state', 'initial') if state else 'initial'
            
            # STEP 1: Role + Context (Structured Context)
            role_context = f"""You are an expert conversational AI for {group_name}, a WhatsApp commerce assistant for SMEs in Africa.

CUSTOMER CONTEXT:
- Current conversation state: {conversation_state}
- Business type: {business_type}

TASK: Analyze the customer's message using step-by-step reasoning to determine their intent."""

            # STEP 2: Chain-of-Thought Reasoning Framework
            reasoning_framework = """
ANALYSIS FRAMEWORK - Follow these steps:

Step 1: MESSAGE TYPE ANALYSIS
- Is this a QUESTION (asking for information)?
- Is this an ACTION (wanting to do something)?
- Is this a CONFIRMATION (providing information)?

Step 2: CONTEXT ANALYSIS
- What is the conversation state?
- Is this a response to payment options?
- Is this about products/services?

Step 3: INTENT CLASSIFICATION
Based on steps 1-2, classify the intent."""

            # STEP 3: Few-Shot Examples (Generic for any business)
            few_shot_examples = """
EXAMPLES (African SME Context):

PRODUCT_INQUIRY Examples:
- "Do you have [product]?" → QUESTION about availability
- "What types of [product] do you sell?" → QUESTION about variety
- "Is [product] in stock?" → QUESTION about availability

PAYMENT_INQUIRY Examples:
- "Can I pay with M-Pesa?" → QUESTION about payment methods
- "How do I pay?" → QUESTION about payment process
- "What payment options do you accept?" → QUESTION about payment

PAYMENT_CONFIRMATION Examples:
- "QH47XYZ123" → M-Pesa transaction code
- "Confirmed. KSH 500.00 sent to..." → M-Pesa confirmation
- "I have paid via M-Pesa ref: ABC123" → Payment confirmation

WELCOME MENU Examples (when conversation_state=welcome):
- "1" → place_order (selecting "Place Order" menu option)
- "2" → track_order (selecting "Track My Order" menu option)

PAYMENT_SELECTION Examples (when conversation_state=awaiting_payment):
- "1" → payment_selection (selecting "M-Pesa" payment option)
- "2" → payment_selection (selecting "Cash on Delivery" option)
- "3" → payment_selection (selecting "Cancel Order" option)

ORDER_REQUEST Examples:
- "2 [items], 1 [item] size X" → place_order with specific items
- "I want to order [product]" → place_order request
- "order from group:[business]" → place_order (GROUP joining + ORDER)"""

            # STEP 4: Intent Categories
            intent_definitions = """
INTENT CATEGORIES:

1. product_inquiry: Questions about products/services, availability, features
2. place_order: Request to place new order with specific items
3. track_order: Request to check order status or delivery
4. cancel_order: Request to cancel existing order
5. payment_inquiry: Questions about payment methods or process
6. payment_confirmation: Providing M-Pesa codes or payment confirmations
7. payment_selection: Selecting numbered payment options (1,2,3)
8. contact_support: Request for human help or support
9. general_inquiry: General business questions
10. unknown: Unclear or ambiguous intent"""

            # STEP 5: State-Specific Context (Critical for intent detection)
            state_context = ""
            if conversation_state == "awaiting_payment":
                state_context = """
PAYMENT CONTEXT: Customer was presented with payment options:
1. Paid with M-Pesa / 2. Pay on Delivery / 3. Cancel Order
Numbers 1,2,3 = payment_selection intent"""
            elif conversation_state == "welcome":
                state_context = """
WELCOME MENU CONTEXT: Customer just received welcome message with menu options:
1. Place Order / 2. Track My Order
Numbers 1,2 = place_order/track_order intent (NOT payment_selection)"""
            elif conversation_state == "awaiting_order_details":
                state_context = """
ORDER CONTEXT: Customer should provide order details (items, quantities, specifications)
Text descriptions = place_order intent"""

            # STEP 6: Output Format
            output_format = """
OUTPUT: Respond with ONLY the intent name from the list above."""

            return f"{role_context}\n\n{reasoning_framework}\n\n{few_shot_examples}\n\n{intent_definitions}\n\n{state_context}\n\n{output_format}".strip()

        except Exception as e:
            logger.error(f"Error building intent detection prompt: {e}")
            return """Analyze the customer's message and respond with one of these intents: product_inquiry, place_order, track_order, cancel_order, payment_inquiry, payment_confirmation, payment_selection, contact_support, general_inquiry, or unknown."""
    
    def _parse_intent_from_response(self, response: str) -> str:
        """Parse intent from Gemini response"""
        response_lower = response.lower().strip()
        
        intent_mapping = {
            "product_inquiry": Intent.PRODUCT_INQUIRY,
            "place_order": Intent.PLACE_ORDER,
            "track_order": Intent.TRACK_ORDER,
            "cancel_order": Intent.CANCEL_ORDER,
            "payment_inquiry": Intent.PAYMENT_INQUIRY,
            "payment_confirmation": Intent.PAYMENT_CONFIRMATION,
            "payment_selection": Intent.PAYMENT_SELECTION,
            "mpesa_payment": Intent.MPESA_PAYMENT,
            "cash_payment": Intent.CASH_PAYMENT,
            "contact_support": Intent.CONTACT_SUPPORT,
            "general_inquiry": Intent.GENERAL_INQUIRY,
        }
        
        for key, intent in intent_mapping.items():
            if key in response_lower:
                return intent
                
        return Intent.UNKNOWN
    
    def _get_business_type_str(self, business_type) -> str:
        """Convert BusinessType enum or string to string safely"""
        if hasattr(business_type, 'value'):
            return business_type.value
        elif isinstance(business_type, str):
            return business_type
        else:
            return str(business_type)
            
    def _get_business_specific_clarification(self, business_type, message_content: str) -> str:
        """Get business-specific clarification prompts based on business type"""
        business_type_str = self._get_business_type_str(business_type).lower()
            
        if business_type_str in ['restaurant', 'food']:
            return "menu_items"
        elif business_type_str in ['fashion', 'clothing', 'apparel']:
            return "size_color_style"
        elif business_type_str in ['electronics', 'gadgets']:
            return "model_specifications" 
        else:
            return "general_details"
    
    def _parse_json_from_response(self, response_content: str) -> Optional[Dict[str, Any]]:
        """
        Parse JSON from AI response, handling markdown code blocks and other formatting
        """
        try:
            # First, try direct JSON parsing
            return json.loads(response_content)
        except json.JSONDecodeError:
            try:
                # Try to extract JSON from markdown code blocks
                import re
                
                # Look for JSON within ```json ... ``` or ``` ... ``` blocks
                json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response_content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1).strip()
                    return json.loads(json_str)
                
                # Look for any JSON-like structure
                json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    return json.loads(json_str)
                    
            except json.JSONDecodeError:
                logger.warning(f"Could not parse JSON from response: {response_content[:200]}...")
                
        return None

    async def _extract_order_details(self, message: str, state: AgentState) -> Optional[Dict[str, Any]]:
        """Extract structured order details from natural language"""
        try:
            prompt = f"""Extract order details from this customer message: "{message}"
            Return a JSON object with:
            - items: array of {{name: string, quantity: number, notes: string}}
            - special_instructions: string
            - estimated_total: number (if mentioned)

            If you cannot extract clear order details, return null.
            Example: {{"items": [{{"name": "T-shirt", "quantity": 2, "notes": "size L, red color"}}], "special_instructions": "deliver by 5pm", "estimated_total": 0}}

            Customer message: {message}
            """
            
            response = await self._rate_limited_llm_call([HumanMessage(content=prompt)], estimated_tokens=len(prompt))
            
            # Parse JSON response with improved handling
            order_data = self._parse_json_from_response(response.content)
            if order_data and "items" in order_data and order_data["items"]:
                return order_data
                
            return None
            
        except Exception as e:
            logger.error(f"Error extracting order details: {str(e)}")
            return None
    
    def _extract_mpesa_details(self, message: str) -> Dict[str, Any]:
        """Extract M-Pesa transaction details"""
        import re
        
        # Look for transaction codes (typically 8-12 alphanumeric characters)
        transaction_match = re.search(r'[A-Z0-9]{8,12}', message.upper())
        transaction_code = transaction_match.group(0) if transaction_match else message[:15]
        
        # Look for amounts
        amount_match = re.search(r'KSH?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)', message.upper())
        amount = amount_match.group(1) if amount_match else "0"
        
        return {
            "transaction_code": transaction_code,
            "amount": amount,
            "raw_message": message
        }
    
    async def _generate_contextual_response(self, message: str, customer: Customer, group: Group, state: AgentState) -> str:
        """Generate enhanced contextual AI response with business-specific personality"""
        try:
            group_name = group.name if group else "Our Business"
            business_type = group.business_type if group else BusinessType.GENERAL
            
            # Get conversation context from LangGraph state (modern approach)
            recent_context = ""
            if state.get("messages") and len(state["messages"]) > 1:
                # Extract recent message content from LangGraph state
                recent_messages = []
                for msg in state["messages"][-3:]:  # Last 3 messages
                    if hasattr(msg, 'content') and msg.content.strip():
                        recent_messages.append(msg.content.strip())
                
                if recent_messages:
                    recent_context = f"Recent conversation: {' | '.join(recent_messages[-2:])}"
            
            # Check if message is ambiguous (like "Yes", "No", "OK")
            is_ambiguous = len(message.strip()) <= 3 or message.lower().strip() in ['yes', 'no', 'ok', 'sure', 'fine', 'good']
            
            # Get customer analytics for personalization (with fallback for errors)
            try:
                customer_profile = await self.analytics_service.analyze_customer_behavior(customer.id, update_analytics=False)
            except Exception as e:
                logger.warning(f"Analytics service error: {e}, using default profile")
                customer_profile = {'advanced_metrics': {'customer_segment': 'new'}}
            
            # Get business-specific AI personality
            ai_personality = group.ai_personality if group and group.ai_personality else self._get_default_personality(business_type)
            
            # Get customer recommendations (with fallback for errors)
            try:
                recommendations = await self.analytics_service.get_customer_recommendations(customer.id, limit=3)
            except Exception as e:
                logger.warning(f"Recommendations service error: {e}, using empty recommendations")
                recommendations = []
            
            prompt = f"""{ai_personality}
            Customer message: "{message}"
            {recent_context}

            Customer context:
            - Customer segment: {customer_profile.get('advanced_metrics', {}).get('customer_segment', 'new')}
            - Previous orders: {customer_profile.get('basic_metrics', {}).get('total_orders', 0)}
            - Preferred categories: {customer_profile.get('category_preferences', {}).get('dominant_category', 'none')}

            Business context:
            - Business type: {self._get_business_type_str(business_type)}
            - Business name: {group_name}

            {'IMPORTANT: The customer response is ambiguous. Ask for clarification about what they want to do.' if is_ambiguous else ''}

            If relevant, you can mention these personalized recommendations:
            {', '.join([rec.get('name', '') for rec in recommendations[:2]])}

            Generate a helpful, personalized response. Keep it:
            - Under 100 words
            - WhatsApp appropriate with your business personality
            - Include personalized touches when relevant
            - If you don't know something, suggest contacting support
            - If the message is ambiguous, ask for clarification

            Response:"""
            
            response = await self._rate_limited_llm_call([HumanMessage(content=prompt)],estimated_tokens=len(prompt))
            return response.content
            
        except Exception as e:
            logger.error(f"Error generating contextual response: {str(e)}")
            return "I apologize, but I'm having trouble processing your request right now. Please contact our support team for assistance."
    
    async def _generate_product_inquiry_response(self, message: str, customer: Customer, group: Group, state: AgentState) -> str:
        """Generate AI-powered product inquiry response with real inventory data and business context"""
        try:
            group_name = group.name if group else "Our Business"
            business_type = self._get_business_type_str(group.business_type) if group and group.business_type else "retail"
            
            # Get business-specific AI personality for context-aware responses
            ai_personality = group.ai_personality if group.ai_personality else self._get_default_personality(group.business_type)
            
            # Initialize enhanced inventory service
            from app.services.enhanced_inventory_service import get_enhanced_inventory_service
            inventory_service = get_enhanced_inventory_service(self.db)
            
            # Check if this is a general inventory request
            is_general_request = self._is_general_inventory_request(message)
            
            if is_general_request:
                # Show all available products for general requests
                matching_products = inventory_service.get_all_available_products_for_ai(
                    group_id=group.id, 
                    limit=10
                )
                product_keywords = "general inventory"
            else:
                # Extract product keywords from customer message
                product_keywords = self._extract_product_keywords_from_message(message)
                
                # Search for matching products in inventory
                matching_products = inventory_service.search_products_for_ai(
                    group_id=group.id, 
                    search_query=product_keywords, 
                    limit=5
                )
            
            # Get business inventory summary for context
            inventory_summary = inventory_service.get_business_inventory_summary_for_ai(group.id)
            
            # Enhanced prompt with real inventory data AND business personality
            inventory_context = ""
            if matching_products:
                if is_general_request:
                    inventory_context = "OUR AVAILABLE PRODUCTS:\n"
                    for product in matching_products[:5]:  # Show more for general requests
                        status = "✅ In Stock" if product["in_stock"] else "❌ Out of Stock"
                        inventory_context += f"- {product['name']}: {status} ({product['stock_quantity']} available) - KSH {product['price']}\n"
                else:
                    inventory_context = "CURRENT INVENTORY MATCHES:\n"
                    for product in matching_products[:3]:  # Top 3 matches for specific searches
                        status = "✅ In Stock" if product["in_stock"] else "❌ Out of Stock"
                        inventory_context += f"- {product['name']}: {status} ({product['stock_quantity']} available) - KSH {product['price']}\n"
            else:
                if is_general_request:
                    inventory_context = "Currently no products are available in our inventory.\n"
                else:
                    inventory_context = "No exact matches found in current inventory.\n"
            
            # Get business-specific response patterns
            business_context = self._get_business_specific_context_for_inquiry(business_type, group_name)
            
            prompt = f"""{ai_personality}

CUSTOMER QUESTION: "{message}"
EXTRACTED KEYWORDS: "{product_keywords}"

{inventory_context}

BUSINESS CONTEXT:
- Total products in inventory: {inventory_summary.get('total_products', 'N/A')}
- Business specialization: {business_context['specialization']}
- What we DON'T sell: {business_context['out_of_scope']}

CONTEXT-AWARE RESPONSE GUIDELINES:
1. If GENERAL INVENTORY REQUEST: Show available products with prices from our current stock
2. If products found IN STOCK: Mention specific items and prices  
3. If products found but OUT OF STOCK: Suggest alternatives within our business scope
4. If NO matches AND request is WITHIN our business: Offer to check suppliers or suggest similar items
5. If NO matches AND request is OUTSIDE our business: Politely redirect to our specialization
6. Always maintain your business personality and expertise
7. Keep under 100 words for WhatsApp
8. For general requests, be helpful and show what's actually available

BUSINESS-SPECIFIC RESPONSE EXAMPLES:
{business_context['response_examples']}

Generate your contextually appropriate response:"""
            
            response = await self._rate_limited_llm_call([HumanMessage(content=prompt)], estimated_tokens=len(prompt))
            return response.content
            
        except Exception as e:
            logger.error(f"Error generating smart product inquiry response: {str(e)}")
            # Fallback to basic response
            return f"Thank you for asking about our products! Let me check what we have available for you. I'll get back to you with current stock and pricing information shortly."
    
    def _get_business_specific_context_for_inquiry(self, business_type: str, group_name: str) -> Dict[str, str]:
        """Get business-specific context for intelligent product inquiries"""
        business_contexts = {
            'electronics': {
                'specialization': 'Electronics, smartphones, computers, gadgets, and tech accessories',
                'out_of_scope': 'Food, clothing, medicines, furniture, or non-tech items',
                'response_examples': '''
                OUT OF SCOPE: "I'm a tech specialist - I help with electronics, phones, computers, and gadgets. Were you looking for any tech products instead?"
                SIMILAR TECH: "I don't have that exact model, but I have similar smartphones/laptops. Would you like to see what's available?"
                SUPPLIER CHECK: "Let me check with our tech suppliers for that specific model. In the meantime, we have similar electronics available."'''
                            },
            'restaurant': {
                'specialization': 'Food, beverages, meals, and dining experiences',  
                'out_of_scope': 'Electronics, clothing, medicines, or non-food items',
                'response_examples': '''
                OUT OF SCOPE: "I'm your food specialist - I help with meals, drinks, and dining. What can I prepare for you today?"
                FOOD ALTERNATIVE: "We don't have that dish, but I can suggest similar items from our menu. What flavors do you enjoy?"
                SUPPLIER CHECK: "Let me check if we can source those ingredients. Meanwhile, here's what we're serving today..."'''
                            },
            'pharmacy': {
                'specialization': 'Medicines, health products, medical supplies, and wellness items',
                'out_of_scope': 'Electronics, food, clothing, or non-medical items',
                'response_examples': '''
                OUT OF SCOPE: "I'm a pharmacy assistant specializing in health products and medicines. How can I help with your health needs?"
                HEALTH ALTERNATIVE: "We don't stock that brand, but I have similar medications. Please consult our pharmacist for alternatives."
                SUPPLIER CHECK: "Let me check our medical suppliers for that item. Do you have a prescription for this medication?"'''
                            },
            'fashion': {
                'specialization': 'Clothing, shoes, accessories, and fashion items',
                'out_of_scope': 'Electronics, food, medicines, or non-fashion items', 
                'response_examples': '''
                OUT OF SCOPE: "I'm your fashion consultant - I help with clothing, shoes, and style. What fashion items can I help you find?"
                STYLE ALTERNATIVE: "We don't have that exact piece, but I have similar styles in your size. What occasion is this for?"
                SUPPLIER CHECK: "Let me check with our fashion suppliers for that brand. What's your size and preferred color?"'''
                            },
            'grocery': {
                'specialization': 'Food items, beverages, household essentials, and daily necessities',
                'out_of_scope': 'Electronics, specialized medicines, or non-grocery items',
                'response_examples': '''
                OUT OF SCOPE: "I'm your grocery assistant - I help with food, drinks, and household items. What groceries do you need?"
                GROCERY ALTERNATIVE: "We don't carry that brand, but I have similar products. Are you looking for organic or regular?"
                SUPPLIER CHECK: "Let me check our grocery suppliers for that item. We do have similar products available now."'''
                            }
        }
        
        # Default context for unknown business types
        default_context = {
            'specialization': f'{business_type.title()} products and services',
            'out_of_scope': 'Items outside our business focus',
            'response_examples': '''
            OUT OF SCOPE: "I specialize in our business products and services. How can I help you with items we actually carry?"
            ALTERNATIVE: "We don't have that exact item, but I can suggest similar products we do have available."
            SUPPLIER CHECK: "Let me check with our suppliers for that item. Here's what we currently have available."'''
                    }
        
        return business_contexts.get(business_type.lower(), default_context)
    
    def _is_general_inventory_request(self, message: str) -> bool:
        """Check if the message is asking for general product listing"""
        message_lower = message.lower().strip()
        
        # Patterns that indicate general inventory requests
        general_patterns = [
            "what products do you have",
            "what do you have in stock",
            "what do you sell",
            "show me your products",
            "what products are available",
            "what's available",
            "what items do you have",
            "show inventory",
            "list products",
            "what products",
            "what stock",
            "products available",
            "available products"
        ]
        
        for pattern in general_patterns:
            if pattern in message_lower:
                return True
                
        return False
    
    def _extract_product_keywords_from_message(self, message: str) -> str:
        """Extract product-related keywords from customer message"""
        # Simple keyword extraction - can be enhanced with NLP
        message_lower = message.lower()
        
        # Remove common question words
        stop_words = ['do', 'you', 'have', 'any', 'what', 'kind', 'of', 'is', 'there', 'are', 'can', 'i', 'get', 'products', 'stock', 'available', 'in']
        words = message_lower.split()
        
        # Filter out stop words and keep potential product names
        keywords = [word for word in words if word not in stop_words and len(word) > 2]
        
        return ' '.join(keywords[:3])  # Take first 3 meaningful words
    
    async def _generate_payment_inquiry_response(self, message: str, group: Group) -> str:
        """Generate response to payment questions - Generic for African SMEs"""
        try:
            group_name = group.name if group else "Our Business"
            
            prompt = f"""You are a helpful payment assistant for {group_name}, an African SME.

                CUSTOMER PAYMENT QUESTION: "{message}"

                TASK: Answer their payment question professionally.

                GUIDELINES:
                1. For "Can I pay with M-Pesa?" → Confirm M-Pesa is accepted
                2. For "How do I pay?" → Explain available payment methods
                3. For "What payment options?" → List M-Pesa, Cash on Delivery, etc.
                4. Always be reassuring about payment security
                5. Keep under 50 words for WhatsApp
                6. Use African context

                RESPONSE EXAMPLES:
                Q: "Can I pay with M-Pesa?"
                A: "Yes! We accept M-Pesa payments. When you're ready to pay, I'll provide our payment details. We also offer cash on delivery if you prefer."

                Q: "How did you confirm my payment?"
                A: "I haven't confirmed any payment yet. When you're ready to pay, please share your M-Pesa confirmation message and I'll process it for you."

                Q: "What payment options do you have?"
                A: "We accept M-Pesa (most popular) and cash on delivery. Both are secure and convenient for our customers."

                Generate your response:"""
            
            response = await self._rate_limited_llm_call([HumanMessage(content=prompt)], estimated_tokens=len(prompt))
            return response.content
            
        except Exception as e:
            logger.error(f"Error generating payment inquiry response: {str(e)}")
            return "Yes, we accept M-Pesa and cash on delivery. When you're ready to pay, I'll guide you through the process!"
    
    async def _extract_order_details_enhanced(self, message: str, state: AgentState, business_type: BusinessType) -> Optional[Dict[str, Any]]:
        """Enhanced order extraction with business-specific understanding"""
        try:
            # Get business-specific attributes and categories
            business_config = self.business_config_service.get_business_template(business_type)
            typical_attributes = business_config.get("typical_product_attributes", [])
            
            prompt = f"""Extract order details from this {self._get_business_type_str(business_type)} customer message: "{message}"

            Business context: This is a {self._get_business_type_str(business_type)} business.
            Typical product attributes to look for: {', '.join(typical_attributes)}

            Return a JSON object with:
            - items: array of {{name: string, quantity: number, notes: string, attributes: object}}
            - special_instructions: string
            - estimated_total: number (if mentioned)
            - business_specific_notes: string (any {self._get_business_type_str(business_type)}-specific requirements)

            For {self._get_business_type_str(business_type)} businesses, pay special attention to:
            {self._get_business_specific_extraction_notes(business_type)}

            If you cannot extract clear order details, return null.

            Customer message: {message}
            """
            
            response = await self._rate_limited_llm_call([HumanMessage(content=prompt)], 
                                                        estimated_tokens=len(prompt))
            
            # Parse JSON response with improved handling
            order_data = self._parse_json_from_response(response.content)
            if order_data and "items" in order_data and order_data["items"]:
                # Enhance with product matching
                enhanced_items = self._match_products_to_catalog(order_data["items"], state["group_id"])
                order_data["items"] = enhanced_items
                return order_data
                
            return None
            
        except Exception as e:
            logger.error(f"Error extracting enhanced order details: {str(e)}")
            return None
    
    def _check_order_availability(self, order_details: Dict[str, Any], group_id: int) -> Dict[str, Any]:
        """Check inventory availability for order items"""
        try:
            items = order_details.get("items", [])
            availability_results = {
                "all_available": True,
                "available_items": [],
                "unavailable_items": [],
                "low_stock_warnings": []
            }
            
            for item in items:
                product_id = item.get("product_id")
                variant_id = item.get("variant_id")
                requested_quantity = item.get("quantity", 1)
                
                if product_id:
                    availability = self.inventory_service.get_product_availability(product_id, variant_id)
                    
                    if availability["available"]:
                        stock_qty = availability.get("stock_quantity", 0)
                        if stock_qty >= requested_quantity:
                            availability_results["available_items"].append(item)
                            
                            # Check for low stock warning
                            if availability.get("is_low_stock", False):
                                availability_results["low_stock_warnings"].append({
                                    "item": item,
                                    "remaining_stock": stock_qty
                                })
                        else:
                            availability_results["all_available"] = False
                            availability_results["unavailable_items"].append({
                                "item": item,
                                "reason": "insufficient_stock",
                                "available_quantity": stock_qty
                            })
                    else:
                        availability_results["all_available"] = False
                        availability_results["unavailable_items"].append({
                            "item": item,
                            "reason": availability["reason"]
                        })
                else:
                    # Custom item - assume available
                    availability_results["available_items"].append(item)
            
            return availability_results
            
        except Exception as e:
            logger.error(f"Error checking order availability: {str(e)}")
            return {"all_available": False, "error": str(e)}
    
    def _calculate_intelligent_pricing(self, order_details: Dict[str, Any], customer_id: int) -> Dict[str, Any]:
        """Calculate intelligent pricing with personalization and promotions"""
        try:
            # Get customer analytics for personalized pricing
            customer_analytics = self.analytics_service.analyze_customer_behavior(customer_id, update_analytics=False)
            customer_segment = customer_analytics.get("advanced_metrics", {}).get("customer_segment", "new")
            
            total = 0.0
            items_pricing = []
            
            for item in order_details.get("items", []):
                base_price = item.get("base_price", 0.0)
                quantity = item.get("quantity", 1)
                
                # Apply customer segment discounts
                discount_percent = self._get_segment_discount(customer_segment)
                discounted_price = base_price * (1 - discount_percent / 100)
                
                item_total = discounted_price * quantity
                total += item_total
                
                items_pricing.append({
                    **item,
                    "original_price": base_price,
                    "discounted_price": discounted_price,
                    "discount_percent": discount_percent,
                    "line_total": item_total
                })
            
            return {
                "items": items_pricing,
                "subtotal": total,
                "total_discount": sum(item["base_price"] * item["quantity"] for item in order_details.get("items", [])) - total,
                "final_total": total,
                "pricing_notes": f"Applied {customer_segment} customer discount" if discount_percent > 0 else ""
            }
            
        except Exception as e:
            logger.error(f"Error calculating intelligent pricing: {str(e)}")
            return {"final_total": 0.0, "error": str(e)}
    
    def _suggest_alternatives(self, unavailable_items: List[Dict[str, Any]], customer_id: int) -> List[Dict[str, Any]]:
        """Suggest alternative products for unavailable items"""
        try:
            alternatives = []
            
            # Get customer recommendations as alternatives
            recommendations = self.analytics_service.get_customer_recommendations(customer_id, limit=5)
            
            for unavailable_item in unavailable_items:
                item_alternatives = []
                
                # Find similar products based on name/category
                similar_products = self._find_similar_products(
                    unavailable_item["item"].get("name", ""),
                    unavailable_item["item"].get("category"),
                    customer_id
                )
                
                item_alternatives.extend(similar_products[:3])  # Top 3 similar products
                
                alternatives.append({
                    "unavailable_item": unavailable_item["item"]["name"],
                    "reason": unavailable_item["reason"],
                    "alternatives": item_alternatives
                })
            
            return alternatives
            
        except Exception as e:
            logger.error(f"Error suggesting alternatives: {str(e)}")
            return []
    
    def _get_business_specific_extraction_notes(self, business_type: BusinessType) -> str:
        """Get business-specific notes for order extraction"""
        notes = {
            BusinessType.RESTAURANT: "sizes, spice levels, dietary requirements, cooking preferences, sides, drinks",
            BusinessType.PHARMACY: "dosage, quantity, prescription requirements, generic alternatives",
            BusinessType.FASHION: "sizes, colors, materials, styles, occasions",
            BusinessType.ELECTRONICS: "models, specifications, compatibility, warranties, accessories",
            BusinessType.GROCERY: "weights, units, brands, organic preferences, freshness requirements"
        }
        
        return notes.get(business_type, "brand, model, specifications, preferences")
    
    def _get_default_personality(self, business_type) -> str:
        """Get default AI personality based on business type"""
        business_type_str = self._get_business_type_str(business_type).lower()
        
        personalities = {
            'restaurant': "You are a friendly restaurant assistant. Help customers with their food orders, suggest popular dishes, and provide information about ingredients and dietary options.",
            'fashion': "You are a helpful fashion consultant. Assist customers with clothing choices, sizes, styles, and outfit recommendations.",
            'electronics': "You are a knowledgeable electronics specialist. Help customers understand product specifications, compatibility, and make informed tech purchases.",
            'pharmacy': "You are a professional pharmacy assistant. Help customers with their medication needs while being careful about medical advice.",
            'grocery': "You are a friendly grocery store assistant. Help customers find products, understand nutrition information, and organize their shopping lists."
        }
        
        return personalities.get(business_type_str, "You are a helpful customer service assistant. Provide friendly, professional support to help customers with their orders and questions.")
    
    def _match_products_to_catalog(self, items: List[Dict[str, Any]], group_id: int) -> List[Dict[str, Any]]:
        """Match extracted items to actual products in catalog"""
        try:
            enhanced_items = []
            
            for item in items:
                item_name = item.get("name", "").lower()
                
                # Search for matching products
                from app.utils.sql_security import escape_sql_pattern
                safe_item_name = escape_sql_pattern(item_name)
                matching_products = self.db.query(Product).filter(
                    Product.group_id == group_id,
                    Product.is_active == True,
                    Product.name.ilike(f"%{safe_item_name}%", escape='\\')
                ).limit(3).all()
                
                if matching_products:
                    # Take the best match (first one)
                    best_match = matching_products[0]
                    enhanced_item = {
                        **item,
                        "product_id": best_match.id,
                        "exact_name": best_match.name,
                        "base_price": best_match.get_current_price(),
                        "sku": best_match.sku,
                        "category": best_match.category.value if best_match.category else None,
                        "in_stock": best_match.is_in_stock(),
                        "match_confidence": self._calculate_match_confidence(item_name, best_match.name)
                    }
                    
                    # Check for variants if applicable
                    if best_match.has_variants:
                        variant_match = self._find_best_variant_match(best_match, item)
                        if variant_match:
                            enhanced_item["variant_id"] = variant_match.id
                            enhanced_item["variant_name"] = variant_match.variant_name
                            enhanced_item["base_price"] = best_match.get_current_price() + variant_match.price_adjustment
                    
                    enhanced_items.append(enhanced_item)
                else:
                    # No match found - keep as custom item
                    enhanced_items.append({
                        **item,
                        "product_id": None,
                        "is_custom": True,
                        "base_price": 0.0
                    })
            
            return enhanced_items
            
        except Exception as e:
            logger.error(f"Error matching products to catalog: {str(e)}")
            return items  # Return original items if matching fails
    
    async def process_message(self, customer_id: int, group_id: int, message: str, 
                            conversation_state: str = "idle", 
                            context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Process a customer message through the AI agent with security validation"""
        
        # 1. Security validation and sanitization
        try:
            # Validate message length and sanitize input
            if not message:
                message = ""
            
            # Apply security validation
            sanitized_message = SecurityValidator.sanitize_user_input(message)
            
            # Check if message was heavily filtered (possible attack)
            if len(sanitized_message) < len(message) * 0.3:
                logger.warning(f"Message heavily filtered for customer {customer_id}: {message[:100]}...")
                return {
                    "intent": Intent.UNKNOWN,
                    "action": "security_filtered",
                    "response": "I'm sorry, but I cannot process that message. Please rephrase your request."
                }
            
            # Check circuit breaker
            if not ai_circuit_breaker.call_allowed():
                logger.warning("AI circuit breaker is open - too many failures")
                return {
                    "intent": Intent.UNKNOWN,
                    "action": "service_unavailable",
                    "response": "AI assistant is temporarily unavailable due to high error rate. Please try again in a few minutes."
                }
            
            # Use sanitized message for processing
            message = sanitized_message
            
        except Exception as e:
            logger.error(f"Security validation failed: {str(e)}")
            return {
                "intent": Intent.UNKNOWN,
                "action": "security_error",
                "response": "Unable to process your message due to security validation. Please try again."
            }
        
        # 2. Check AI agent initialization
        if not self.llm or not self.graph:
            logger.warning("AI agent not initialized. Falling back to basic processing.")
            return {
                "intent": Intent.UNKNOWN,
                "action": "fallback",
                "response": "AI assistant temporarily unavailable. Please try again later."
            }
        
        try:
            # LangGraph v0.3+ pattern: Create thread-based config for conversation persistence
            thread_id = f"customer_{customer_id}"
            config = RunnableConfig(
                configurable={"thread_id": thread_id}
            ) if self.checkpointer else None
            
            # Create enhanced initial state with current message
            # LangGraph will automatically manage conversation history via checkpointer
            initial_state = AgentState(
                messages=[HumanMessage(content=message)],
                customer_id=customer_id,
                group_id=group_id,
                current_intent=Intent.UNKNOWN,
                conversation_state=conversation_state,
                context=context or {},
                last_action="",
                order_data=None,
                
                # LangGraph v0.3+ state fields
                thread_id=thread_id,
                session_metadata={
                    "customer_id": customer_id,
                    "group_id": group_id,
                    "start_time": datetime.utcnow().isoformat(),
                    "conversation_state": conversation_state
                },
                state_version="v2.0",
                error_context=None,
                conversation_summary=None,
                total_messages=0
            )
            
            # Run the conversation graph with LangGraph persistence
            result = await self.graph.ainvoke(initial_state, config=config)
            
            return {
                "intent": result["current_intent"],
                "action": result["last_action"],
                "order_data": result.get("order_data"),
                "conversation_state": result.get("conversation_state"),
                "context": result.get("context", {})
            }
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error processing message with AI agent: {error_message}")
            
            # Check for quota/rate limit specific errors
            if "quota" in error_message.lower() or "429" in error_message:
                return {
                    "intent": Intent.UNKNOWN,
                    "action": "quota_exceeded",
                    "response": "I'm currently at capacity due to high demand. Please provide your order details directly: item names, quantities, and any size/color preferences."
                }
            else:
                return {
                    "intent": Intent.UNKNOWN,
                    "action": "error",
                    "response": "I encountered an error processing your message. Please try again."
                }
    
    # NOTE: Conversation history management methods removed
    # LangGraph v0.3+ MemorySaver checkpointer handles conversation persistence automatically
    # No need for custom _load_conversation_history or _save_conversation_turn methods
    
    def _validate_and_clean_messages(self, messages: List) -> List:
        """
        Validate and clean messages according to Gemini API requirements
        Based on official documentation to prevent 'contents.parts must not be empty' errors
        """
        valid_messages = []
        
        for i, msg in enumerate(messages):
            try:
                # Log original message details for debugging
                logger.debug(f"Processing message {i}: {type(msg).__name__} with attributes: {dir(msg)}")
                
                # Get message content safely
                content = getattr(msg, 'content', '')
                logger.debug(f"Message {i} content type: {type(content)}, value: {repr(content)}")
                
                # Skip messages with no content attribute
                if not hasattr(msg, 'content'):
                    logger.warning(f"Message {i}: {type(msg).__name__} has no content attribute")
                    continue
                
                # Clean and validate content
                if isinstance(content, str):
                    content = content.strip()
                    if not content:
                        logger.warning(f"Message {i}: {type(msg).__name__} has empty content")
                        continue
                        
                    # Ensure minimum content length for Gemini
                    if len(content) < 3:
                        logger.warning(f"Message {i}: {type(msg).__name__} content too short: '{content}'")
                        continue
                        
                elif isinstance(content, list):
                    # Handle multimodal content (list format)
                    valid_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get('text', '').strip():
                            valid_parts.append(part)
                        elif isinstance(part, dict) and part.get('type') == 'image_url':
                            valid_parts.append(part)
                    
                    if not valid_parts:
                        logger.warning(f"Message {i}: {type(msg).__name__} has no valid content parts")
                        continue
                        
                    # Update content with valid parts only
                    content = valid_parts
                else:
                    logger.warning(f"Message {i}: {type(msg).__name__} has invalid content type: {type(content)}")
                    continue
                
                # Create new message with cleaned content
                # Convert SystemMessage to HumanMessage as Gemini doesn't support system messages
                try:
                    from langchain_core.messages import SystemMessage, HumanMessage
                    if isinstance(msg, SystemMessage):
                        # Convert system messages to human messages for Gemini compatibility
                        clean_msg = HumanMessage(content=content)
                        logger.debug(f"Converted SystemMessage to HumanMessage for Gemini compatibility")
                    else:
                        msg_type = type(msg)
                        clean_msg = msg_type(content=content)
                    valid_messages.append(clean_msg)
                    
                    if self.settings.ai_debug_mode:
                        content_preview = content[:50] if isinstance(content, str) else f"[{len(content)} parts]"
                        logger.debug(f"Valid message {i}: {type(msg).__name__} - Content: {content_preview}")
                except Exception as create_error:
                    logger.warning(f"Message {i}: Failed to create {type(msg).__name__} with cleaned content: {create_error}")
                    continue
                    
            except Exception as e:
                logger.warning(f"Message {i}: Error processing message: {e}")
                continue
        
        # Ensure we have at least one message for Gemini
        if not valid_messages:
            logger.error("No valid messages after cleaning - creating fallback human message")
            from langchain_core.messages import HumanMessage
            valid_messages.append(HumanMessage(content="Please help me with my order."))
        
        # Log final message count
        if self.settings.ai_debug_mode:
            logger.debug(f"Message validation: {len(messages)} -> {len(valid_messages)} valid messages")
            
        return valid_messages
    
    def _get_segment_discount(self, customer_segment: str) -> float:
        """Get discount percentage based on customer segment"""
        segment_discounts = {
            "vip": 15.0,
            "loyal": 10.0,
            "regular": 5.0,
            "new": 0.0,
            "at_risk": 20.0  # Special discount to retain at-risk customers
        }
        return segment_discounts.get(customer_segment.lower(), 0.0)
    
    def _find_similar_products(self, item_name: str, category: str = None, customer_id: int = None) -> List[Dict[str, Any]]:
        """Find similar products based on name and category"""
        try:
            # Simple similarity matching - in production, you'd use more sophisticated ML
            from app.models import Product
            
            query = self.db.query(Product).filter(Product.is_active == True)
            
            if category:
                # Convert string category to enum
                from app.models import ProductCategory
                try:
                    # Try to find matching enum value
                    category_enum = None
                    for cat in ProductCategory:
                        if cat.value.lower() == category.lower():
                            category_enum = cat
                            break
                    
                    if category_enum:
                        query = query.filter(Product.category == category_enum)
                except (ValueError, AttributeError):
                    # If category conversion fails, skip category filtering
                    logger.warning(f"Invalid category '{category}' provided, skipping category filter")
                    pass
            
            # Look for products with similar names
            from app.utils.sql_security import escape_sql_pattern
            safe_item_name = escape_sql_pattern(item_name)
            similar_products = query.filter(
                Product.name.ilike(f"%{safe_item_name}%", escape='\\')
            ).limit(5).all()
            
            result = []
            for product in similar_products:
                result.append({
                    "id": product.id,
                    "name": product.name,
                    "price": product.get_current_price(),
                    "category": product.category.value if product.category else None,
                    "similarity_reason": "name_match"
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error finding similar products: {str(e)}")
            return []
    
    def _calculate_match_confidence(self, search_name: str, product_name: str) -> float:
        """Calculate confidence score for product matching"""
        try:
            search_lower = search_name.lower().strip()
            product_lower = product_name.lower().strip()
            
            # Exact match
            if search_lower == product_lower:
                return 1.0
            
            # Contains match
            if search_lower in product_lower or product_lower in search_lower:
                return 0.8
            
            # Word overlap
            search_words = set(search_lower.split())
            product_words = set(product_lower.split())
            overlap = len(search_words & product_words)
            total_words = len(search_words | product_words)
            
            if total_words > 0:
                return overlap / total_words
            
            return 0.0
            
        except Exception:
            return 0.0
    
    def _find_best_variant_match(self, product: 'Product', item_data: Dict[str, Any]) -> Optional['ProductVariant']:
        """Find the best matching variant for a product"""
        try:
            if not product.has_variants:
                return None
            
            from app.models import ProductVariant
            
            # Get item attributes
            item_attributes = item_data.get("attributes", {})
            item_notes = item_data.get("notes", "").lower()
            
            # Find variants
            variants = self.db.query(ProductVariant).filter(
                ProductVariant.product_id == product.id,
                ProductVariant.is_active == True
            ).all()
            
            best_match = None
            best_score = 0.0
            
            for variant in variants:
                score = 0.0
                variant_options = variant.variant_options or {}
                
                # Match based on attributes
                for attr_key, attr_value in item_attributes.items():
                    if attr_key.lower() in variant_options:
                        if str(attr_value).lower() == str(variant_options[attr_key]).lower():
                            score += 1.0
                
                # Match based on notes
                for option_key, option_value in variant_options.items():
                    if str(option_value).lower() in item_notes:
                        score += 0.5
                
                if score > best_score:
                    best_score = score
                    best_match = variant
            
            return best_match
            
        except Exception as e:
            logger.error(f"Error finding best variant match: {str(e)}")
            return None

def get_ai_agent(db: Session) -> OrderBotAgent:
    """Get initialized AI agent instance"""
    return OrderBotAgent(db)