"""
AI Agent Service using LangGraph and Gemini for intelligent conversation handling
"""
import json
import logging
from typing import Dict, Any, Optional, List, TypedDict, Union
from datetime import datetime
from enum import Enum

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from app.config import get_settings
from app.models import ConversationState, Customer, Order, Group, Product, BusinessType
from app.services.inventory_service import get_inventory_service
from app.services.analytics_service import get_analytics_service
from app.services.business_config_service import get_business_config_service
from app.services.rate_limiter import get_rate_limiter, rate_limited_api_call
from app.services.api_monitor import get_api_monitor
from sqlalchemy.orm import Session

settings = get_settings()
logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    """State for the AI agent conversation flow"""
    messages: List[Union[HumanMessage, AIMessage, SystemMessage]]
    customer_id: int
    group_id: int
    current_intent: str
    conversation_state: str
    context: Dict[str, Any]
    last_action: str
    order_data: Optional[Dict[str, Any]]

class Intent(str, Enum):
    """Customer intents the AI can detect"""
    PLACE_ORDER = "place_order"
    TRACK_ORDER = "track_order"
    CANCEL_ORDER = "cancel_order"
    CONTACT_SUPPORT = "contact_support"
    MPESA_PAYMENT = "mpesa_payment"
    CASH_PAYMENT = "cash_payment"
    GENERAL_INQUIRY = "general_inquiry"
    UNKNOWN = "unknown"

class OrderBotAgent:
    """
    LangGraph-based AI agent for handling WhatsApp order conversations
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.settings = settings
        
        # Initialize enhanced services
        self.inventory_service = get_inventory_service(db)
        self.analytics_service = get_analytics_service(db)
        self.business_config_service = get_business_config_service(db)
        self.rate_limiter = get_rate_limiter()
        self.api_monitor = get_api_monitor(db)
        
        # Initialize Gemini model
        if not self.settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY not set. AI agent will be disabled.")
            self.llm = None
            self.graph = None
            return
            
        self.llm = ChatGoogleGenerativeAI(
            model=self.settings.ai_model_name,
            google_api_key=self.settings.gemini_api_key,
            temperature=self.settings.ai_temperature,
            max_output_tokens=self.settings.ai_max_tokens,
            convert_system_message_to_human=True
        )
        
        # Initialize memory for conversation persistence
        self.memory = MemorySaver() if self.settings.ai_conversation_memory else None
        
        # Build the conversation graph
        self.graph = self._build_conversation_graph()
        
    def _build_conversation_graph(self) -> StateGraph:
        """Build the LangGraph conversation flow"""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("intent_detection", self._detect_intent_node)
        workflow.add_node("process_order", self._process_order_node)
        workflow.add_node("track_order", self._track_order_node)
        workflow.add_node("handle_payment", self._handle_payment_node)
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
                Intent.CONTACT_SUPPORT: "general_response",
                Intent.GENERAL_INQUIRY: "general_response",
                Intent.UNKNOWN: "general_response"
            }
        )
        
        # All processing nodes lead to END
        workflow.add_edge("process_order", END)
        workflow.add_edge("track_order", END)
        workflow.add_edge("handle_payment", END)
        workflow.add_edge("general_response", END)
        workflow.add_edge("error_handler", END)
        
        return workflow.compile(checkpointer=self.memory)
    
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
                raise ValueError("All messages are empty or invalid")
                
            # Use invoke for synchronous call wrapped in rate limiter
            response = self.llm.invoke(valid_messages)
            
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
            
            if "429" in error_message:
                error_code = "rate_limit_exceeded"
            elif "quota" in error_message.lower():
                error_code = "quota_exceeded"
            else:
                error_code = "api_error"
            
            logger.error(f"LLM API call failed: {str(e)}")
            
            # Return a fallback response
            class FallbackResponse:
                content = "I'm currently experiencing high traffic. Please try again in a moment."
            return FallbackResponse()
            
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
            response = await self._rate_limited_llm_call([
                SystemMessage(content=system_prompt),
                latest_message
            ], estimated_tokens=len(system_prompt) + len(latest_message.content))
            
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
    
    def _handle_payment_node(self, state: AgentState) -> AgentState:
        """Handle payment processing"""
        try:
            messages = state["messages"]
            latest_message = messages[-1] if messages else None
            intent = state["current_intent"]
            
            if intent == Intent.MPESA_PAYMENT and latest_message:
                # Extract M-Pesa transaction details
                transaction_details = self._extract_mpesa_details(latest_message.content)
                state["order_data"] = {
                    "payment_method": "mpesa",
                    "transaction_details": transaction_details
                }
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
        elif intent in [Intent.MPESA_PAYMENT, Intent.CASH_PAYMENT]:
            return Intent.MPESA_PAYMENT
        else:
            return Intent.GENERAL_INQUIRY
    
    def _build_intent_detection_prompt(self, customer: Customer, group: Group, state: AgentState) -> str:
        """Build context-aware prompt for intent detection"""
        group_name = group.name if group else "Our Business"
        customer_name = customer.name if customer else "Customer"
        
        # Ensure we have valid data for prompt construction
        conversation_state = state.get('conversation_state', 'initial') if state else 'initial'
        
        prompt = f"""You are an AI assistant for {group_name}, helping customers via WhatsApp.

Customer: {customer_name}
Current conversation state: {conversation_state}

Your task is to detect the customer's intent from their message. Respond with ONLY one of these intents:
- place_order: Customer wants to place a new order
- track_order: Customer wants to check order status
- cancel_order: Customer wants to cancel an order
- mpesa_payment: Customer is providing M-Pesa payment details/confirmation
- cash_payment: Customer chooses cash on delivery
- contact_support: Customer needs help or support
- general_inquiry: General questions about products/services
- unknown: Intent unclear

Consider the conversation context and respond with just the intent name."""

        # Validate prompt is not empty
        if not prompt or len(prompt.strip()) < 10:
            logger.error("Generated intent detection prompt is too short or empty")
            prompt = """You are a helpful AI assistant. Analyze the customer's message and respond with one of these intents: place_order, track_order, cancel_order, mpesa_payment, cash_payment, contact_support, general_inquiry, or unknown."""
        
        return prompt.strip()
    
    def _parse_intent_from_response(self, response: str) -> str:
        """Parse intent from Gemini response"""
        response_lower = response.lower().strip()
        
        intent_mapping = {
            "place_order": Intent.PLACE_ORDER,
            "track_order": Intent.TRACK_ORDER,
            "cancel_order": Intent.CANCEL_ORDER,
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
            
            response = await self._rate_limited_llm_call([SystemMessage(content=prompt)], 
                                                        estimated_tokens=len(prompt))
            
            # Try to parse JSON response
            try:
                order_data = json.loads(response.content)
                if order_data and "items" in order_data and order_data["items"]:
                    return order_data
            except json.JSONDecodeError:
                pass
                
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
            
            # Get customer analytics for personalization
            customer_profile = self.analytics_service.analyze_customer_behavior(customer.id, update_analytics=False)
            
            # Get business-specific AI personality
            ai_personality = group.ai_personality if group.ai_personality else self._get_default_personality(business_type)
            
            # Get customer recommendations
            recommendations = self.analytics_service.get_customer_recommendations(customer.id, limit=3)
            
            prompt = f"""{ai_personality}

Customer question: {message}

Customer context:
- Customer segment: {customer_profile.get('advanced_metrics', {}).get('customer_segment', 'new')}
- Previous orders: {customer_profile.get('basic_metrics', {}).get('total_orders', 0)}
- Preferred categories: {customer_profile.get('category_preferences', {}).get('dominant_category', 'none')}

Business context:
- Business type: {self._get_business_type_str(business_type)}
- Business name: {group_name}

If relevant, you can mention these personalized recommendations:
{', '.join([rec.get('name', '') for rec in recommendations[:2]])}

Generate a helpful, personalized response. Keep it:
- Under 200 words
- WhatsApp appropriate with your business personality
- Include personalized touches when relevant
- If you don't know something, suggest contacting support

Response:"""
            
            response = await self._rate_limited_llm_call([SystemMessage(content=prompt)], 
                                                        estimated_tokens=len(prompt))
            return response.content
            
        except Exception as e:
            logger.error(f"Error generating contextual response: {str(e)}")
            return "I apologize, but I'm having trouble processing your request right now. Please contact our support team for assistance."
    
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
            
            response = await self._rate_limited_llm_call([SystemMessage(content=prompt)], 
                                                        estimated_tokens=len(prompt))
            
            try:
                order_data = json.loads(response.content)
                if order_data and "items" in order_data and order_data["items"]:
                    # Enhance with product matching
                    enhanced_items = self._match_products_to_catalog(order_data["items"], state["group_id"])
                    order_data["items"] = enhanced_items
                    return order_data
            except json.JSONDecodeError:
                pass
                
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
                matching_products = self.db.query(Product).filter(
                    Product.group_id == group_id,
                    Product.is_active == True,
                    Product.name.ilike(f"%{item_name}%")
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
        """Process a customer message through the AI agent"""
        
        if not self.llm or not self.graph:
            logger.warning("AI agent not initialized. Falling back to basic processing.")
            return {
                "intent": Intent.UNKNOWN,
                "action": "fallback",
                "response": "AI assistant temporarily unavailable. Please try again later."
            }
        
        try:
            # Load conversation history for context
            conversation_history = self._load_conversation_history(customer_id, limit=10)
            
            # Add current message to history
            conversation_history.append(HumanMessage(content=message))
            
            # Create initial state with conversation history
            initial_state = AgentState(
                messages=conversation_history,
                customer_id=customer_id,
                group_id=group_id,
                current_intent=Intent.UNKNOWN,
                conversation_state=conversation_state,
                context=context or {},
                last_action="",
                order_data=None
            )
            
            # Create config for conversation memory
            config = RunnableConfig(
                configurable={"thread_id": f"customer_{customer_id}"}
            ) if self.memory else None
            
            # Run the conversation graph
            result = await self.graph.ainvoke(initial_state, config=config)
            
            return {
                "intent": result["current_intent"],
                "action": result["last_action"],
                "order_data": result.get("order_data"),
                "conversation_state": result.get("conversation_state"),
                "context": result.get("context", {})
            }
            
        except Exception as e:
            logger.error(f"Error processing message with AI agent: {str(e)}")
            return {
                "intent": Intent.UNKNOWN,
                "action": "error",
                "response": "I encountered an error processing your message. Please try again."
            }
    
    def _load_conversation_history(self, customer_id: int, limit: int = 10) -> List[Union[HumanMessage, AIMessage]]:
        """Load recent conversation history from session context"""
        try:
            # Import here to avoid circular imports
            from app.models import ConversationSession
            
            # Get current conversation session
            session = ConversationSession.get_or_create_session(self.db, customer_id)
            context = session.get_context() or {}
            
            # Get conversation history from context
            conversation_messages = context.get('conversation_history', [])
            
            # Convert to LangChain messages (keep last N messages)
            conversation_history = []
            recent_messages = conversation_messages[-limit:] if len(conversation_messages) > limit else conversation_messages
            
            for msg in recent_messages:
                content = msg.get('content', '').strip()
                if msg.get('role') == 'user' and content:  # Only add non-empty user messages
                    conversation_history.append(HumanMessage(content=content))
                elif msg.get('role') == 'assistant' and content:  # Only add non-empty assistant messages
                    conversation_history.append(AIMessage(content=content))
            
            if self.settings.ai_debug_mode:
                logger.info(f"Loaded {len(conversation_history)} messages from conversation history")
                
            return conversation_history
            
        except Exception as e:
            logger.error(f"Error loading conversation history: {str(e)}")
            return []
    
    def _save_conversation_turn(self, customer_id: int, user_message: str, assistant_response: str):
        """Save a conversation turn (user message + assistant response) to session context"""
        try:
            from app.models import ConversationSession
            
            # Get current conversation session
            session = ConversationSession.get_or_create_session(self.db, customer_id)
            context = session.get_context() or {}
            
            # Get or initialize conversation history
            conversation_history = context.get('conversation_history', [])
            
            # Add user message and assistant response
            conversation_history.append({
                'role': 'user',
                'content': user_message,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            conversation_history.append({
                'role': 'assistant', 
                'content': assistant_response,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            # Keep only last 20 messages (10 turns) to prevent context bloat
            if len(conversation_history) > 20:
                conversation_history = conversation_history[-20:]
            
            # Update session context
            context['conversation_history'] = conversation_history
            session.update_state(session.current_state, context)
            self.db.commit()
            
            if self.settings.ai_debug_mode:
                logger.info(f"Saved conversation turn for customer {customer_id}")
                
        except Exception as e:
            logger.error(f"Error saving conversation turn: {str(e)}")
            self.db.rollback()
    
    def _validate_and_clean_messages(self, messages: List) -> List:
        """
        Validate and clean messages according to Gemini API requirements
        Based on official documentation to prevent 'contents.parts must not be empty' errors
        """
        valid_messages = []
        
        for i, msg in enumerate(messages):
            # Get message content safely
            content = getattr(msg, 'content', '')
            
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
            # LangChain messages don't have _type attribute, they use class type directly
            try:
                msg_type = type(msg)
                clean_msg = msg_type(content=content)
                valid_messages.append(clean_msg)
                
                if self.settings.ai_debug_mode:
                    content_preview = content[:50] if isinstance(content, str) else f"[{len(content)} parts]"
                    logger.debug(f"Valid message {i}: {type(msg).__name__} - Content: {content_preview}")
            except Exception as create_error:
                logger.warning(f"Message {i}: Failed to create {type(msg).__name__} with cleaned content: {create_error}")
                continue
        
        # Ensure we have at least one message for Gemini
        if not valid_messages:
            logger.error("No valid messages after cleaning - creating fallback human message")
            from langchain_core.messages import HumanMessage
            valid_messages.append(HumanMessage(content="Hello"))
        
        # Log final message count
        if self.settings.ai_debug_mode:
            logger.debug(f"Message validation: {len(messages)} -> {len(valid_messages)} valid messages")
            
        return valid_messages

def get_ai_agent(db: Session) -> OrderBotAgent:
    """Get initialized AI agent instance"""
    return OrderBotAgent(db)