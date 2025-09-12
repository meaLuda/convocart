"""
Multi-Business-Type Configuration System
Adapts the OrderBot to work with any type of commerce business
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, time
from enum import Enum

from app.models import Group, BusinessType, ProductCategory
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class BusinessConfigService:
    """
    Service to configure the OrderBot for different business types
    """
    
    def __init__(self, db: Session):
        self.db = db
        
        # Business type configurations
        self.business_configs = {
            BusinessType.RESTAURANT: {
                "display_name": "Restaurant/Food Service",
                "categories": [ProductCategory.FOOD, ProductCategory.BEVERAGES],
                "features": ["menu_management", "table_booking", "delivery_tracking", "special_dietary"],
                "payment_methods": ["mpesa", "cash_on_delivery", "card"],
                "ai_personality": "friendly_chef",
                "typical_attributes": ["ingredients", "calories", "preparation_time", "spice_level", "dietary_info"],
                "order_flow": "restaurant_flow",
                "inventory_type": "perishable"
            },
            BusinessType.RETAIL: {
                "display_name": "Retail Store",
                "categories": [ProductCategory.CLOTHING, ProductCategory.ACCESSORIES, ProductCategory.PHYSICAL_PRODUCT],
                "features": ["size_variants", "color_options", "brand_filtering", "seasonal_collections"],
                "payment_methods": ["mpesa", "card", "bank_transfer", "cash_on_delivery"],
                "ai_personality": "helpful_assistant",
                "typical_attributes": ["size", "color", "material", "brand", "care_instructions"],
                "order_flow": "retail_flow",
                "inventory_type": "durable"
            },
            BusinessType.GROCERY: {
                "display_name": "Grocery Store",
                "categories": [ProductCategory.FOOD, ProductCategory.BEVERAGES, ProductCategory.HEALTH_PRODUCTS],
                "features": ["bulk_ordering", "fresh_produce", "expiry_tracking", "household_essentials"],
                "payment_methods": ["mpesa", "cash_on_delivery", "mobile_money"],
                "ai_personality": "efficient_grocer",
                "typical_attributes": ["weight", "unit", "expiry_date", "brand", "organic"],
                "order_flow": "grocery_flow",
                "inventory_type": "mixed"
            },
            BusinessType.PHARMACY: {
                "display_name": "Pharmacy",
                "categories": [ProductCategory.MEDICINES, ProductCategory.HEALTH_PRODUCTS],
                "features": ["prescription_handling", "dosage_info", "drug_interactions", "expiry_alerts"],
                "payment_methods": ["mpesa", "card", "insurance"],
                "ai_personality": "professional_pharmacist",
                "typical_attributes": ["dosage", "active_ingredient", "prescription_required", "expiry_date"],
                "order_flow": "pharmacy_flow",
                "inventory_type": "regulated"
            },
            BusinessType.ELECTRONICS: {
                "display_name": "Electronics Store",
                "categories": [ProductCategory.SMARTPHONES, ProductCategory.COMPUTERS],
                "features": ["technical_specs", "warranty_info", "compatibility_check", "trade_ins"],
                "payment_methods": ["mpesa", "card", "bank_transfer", "installments"],
                "ai_personality": "tech_expert",
                "typical_attributes": ["brand", "model", "specifications", "warranty", "compatibility"],
                "order_flow": "electronics_flow",
                "inventory_type": "high_value"
            },
            BusinessType.FASHION: {
                "display_name": "Fashion Boutique",
                "categories": [ProductCategory.CLOTHING, ProductCategory.ACCESSORIES],
                "features": ["size_guide", "style_matching", "trend_alerts", "personal_styling"],
                "payment_methods": ["mpesa", "card", "bank_transfer"],
                "ai_personality": "style_consultant",
                "typical_attributes": ["size", "color", "material", "brand", "season", "style"],
                "order_flow": "fashion_flow",
                "inventory_type": "seasonal"
            },
            BusinessType.SERVICES: {
                "display_name": "Service Provider",
                "categories": [ProductCategory.CONSULTATION, ProductCategory.DELIVERY, ProductCategory.SERVICE],
                "features": ["appointment_booking", "service_duration", "expert_matching", "location_services"],
                "payment_methods": ["mpesa", "card", "bank_transfer"],
                "ai_personality": "professional_consultant",
                "typical_attributes": ["duration", "location", "expertise_level", "availability"],
                "order_flow": "service_flow",
                "inventory_type": "capacity_based"
            },
            BusinessType.AUTOMOTIVE: {
                "display_name": "Auto Parts/Services",
                "categories": [ProductCategory.PHYSICAL_PRODUCT, ProductCategory.SERVICE],
                "features": ["part_compatibility", "vehicle_matching", "installation_services", "warranty"],
                "payment_methods": ["mpesa", "card", "bank_transfer", "cash_on_delivery"],
                "ai_personality": "auto_expert",
                "typical_attributes": ["compatibility", "part_number", "brand", "condition", "installation"],
                "order_flow": "automotive_flow",
                "inventory_type": "technical"
            },
            BusinessType.BEAUTY: {
                "display_name": "Beauty & Cosmetics",
                "categories": [ProductCategory.PHYSICAL_PRODUCT],
                "features": ["skin_type_matching", "shade_finder", "ingredient_info", "beauty_tips"],
                "payment_methods": ["mpesa", "card", "mobile_money"],
                "ai_personality": "beauty_advisor",
                "typical_attributes": ["shade", "skin_type", "ingredients", "brand", "cruelty_free"],
                "order_flow": "beauty_flow",
                "inventory_type": "cosmetic"
            },
            BusinessType.FITNESS: {
                "display_name": "Fitness/Sports",
                "categories": [ProductCategory.PHYSICAL_PRODUCT, ProductCategory.SERVICE],
                "features": ["size_fitting", "activity_matching", "training_programs", "equipment_guides"],
                "payment_methods": ["mpesa", "card", "bank_transfer"],
                "ai_personality": "fitness_coach",
                "typical_attributes": ["size", "activity_type", "fitness_level", "brand", "durability"],
                "order_flow": "fitness_flow",
                "inventory_type": "sports_equipment"
            },
            BusinessType.EDUCATION: {
                "display_name": "Education/Training",
                "categories": [ProductCategory.DIGITAL_PRODUCT, ProductCategory.SERVICE],
                "features": ["course_enrollment", "skill_assessment", "certification", "progress_tracking"],
                "payment_methods": ["mpesa", "card", "bank_transfer"],
                "ai_personality": "educational_advisor",
                "typical_attributes": ["level", "duration", "certification", "prerequisites", "language"],
                "order_flow": "education_flow",
                "inventory_type": "digital"
            },
            BusinessType.REAL_ESTATE: {
                "display_name": "Real Estate",
                "categories": [ProductCategory.SERVICE],
                "features": ["property_search", "virtual_tours", "financing_info", "legal_assistance"],
                "payment_methods": ["bank_transfer", "card", "financing"],
                "ai_personality": "property_advisor",
                "typical_attributes": ["location", "size", "price_range", "property_type", "amenities"],
                "order_flow": "real_estate_flow",
                "inventory_type": "property"
            },
            BusinessType.AGRICULTURE: {
                "display_name": "Agriculture/Farming",
                "categories": [ProductCategory.PHYSICAL_PRODUCT, ProductCategory.SERVICE],
                "features": ["seasonal_planning", "weather_info", "crop_advice", "equipment_rental"],
                "payment_methods": ["mpesa", "mobile_money", "cash_on_delivery", "seasonal_payment"],
                "ai_personality": "agricultural_advisor",
                "typical_attributes": ["season", "crop_type", "quantity", "delivery_time", "storage"],
                "order_flow": "agriculture_flow",
                "inventory_type": "agricultural"
            },
            BusinessType.GENERAL: {
                "display_name": "General Commerce",
                "categories": [ProductCategory.PHYSICAL_PRODUCT, ProductCategory.DIGITAL_PRODUCT, ProductCategory.SERVICE],
                "features": ["flexible_catalog", "custom_attributes", "multi_category", "adaptive_flow"],
                "payment_methods": ["mpesa", "card", "bank_transfer", "cash_on_delivery", "mobile_money"],
                "ai_personality": "helpful_assistant",
                "typical_attributes": ["brand", "model", "condition", "warranty", "specifications"],
                "order_flow": "general_flow",
                "inventory_type": "mixed"
            }
        }
    
    def configure_business(self, group_id: int, business_type: BusinessType, 
                          custom_settings: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Configure a business with settings optimized for its type
        """
        try:
            group = self.db.query(Group).filter(Group.id == group_id).first()
            if not group:
                return {"error": "Group not found"}
            
            # Get base configuration for business type
            base_config = self.business_configs.get(business_type, self.business_configs[BusinessType.GENERAL])
            
            # Update group with business type
            group.business_type = business_type
            
            # Configure business settings
            business_settings = {
                "features": base_config["features"],
                "inventory_type": base_config["inventory_type"],
                "order_flow": base_config["order_flow"],
                "typical_attributes": base_config["typical_attributes"],
                "ai_configuration": {
                    "personality": base_config["ai_personality"],
                    "custom_prompts": self._get_ai_prompts(business_type),
                    "business_specific_intents": self._get_business_intents(business_type)
                }
            }
            
            # Merge with custom settings if provided
            if custom_settings:
                business_settings.update(custom_settings)
            
            # Store settings
            group.business_settings = business_settings
            group.payment_methods = base_config["payment_methods"]
            group.ai_personality = self._generate_ai_personality_prompt(business_type, group.name)
            group.custom_prompts = self._get_ai_prompts(business_type)
            
            # Set default operating hours if not set
            if not group.operating_hours:
                group.operating_hours = self._get_default_operating_hours(business_type)
            
            self.db.commit()
            
            return {
                "success": True,
                "business_type": business_type.value,
                "configuration": business_settings,
                "features_enabled": base_config["features"],
                "recommended_categories": [cat.value for cat in base_config["categories"]],
                "payment_methods": base_config["payment_methods"]
            }
            
        except Exception as e:
            logger.error(f"Error configuring business: {str(e)}")
            self.db.rollback()
            return {"error": str(e)}
    
    def get_business_template(self, business_type: BusinessType) -> Dict[str, Any]:
        """
        Get configuration template for a business type
        """
        base_config = self.business_configs.get(business_type, self.business_configs[BusinessType.GENERAL])
        
        return {
            "business_type": business_type.value,
            "display_name": base_config["display_name"],
            "recommended_categories": [cat.value for cat in base_config["categories"]],
            "features": base_config["features"],
            "payment_methods": base_config["payment_methods"],
            "ai_personality": base_config["ai_personality"],
            "typical_product_attributes": base_config["typical_attributes"],
            "inventory_management": base_config["inventory_type"],
            "order_flow": base_config["order_flow"],
            "sample_products": self._get_sample_products(business_type),
            "setup_checklist": self._get_setup_checklist(business_type)
        }
    
    def customize_ai_personality(self, group_id: int, personality_traits: Dict[str, Any]) -> bool:
        """
        Customize AI personality for a specific business
        """
        try:
            group = self.db.query(Group).filter(Group.id == group_id).first()
            if not group:
                return False
            
            # Generate custom AI personality prompt
            base_personality = self.business_configs.get(
                group.business_type, 
                self.business_configs[BusinessType.GENERAL]
            )["ai_personality"]
            
            custom_prompt = self._generate_custom_personality_prompt(
                group.name, 
                group.business_type,
                personality_traits,
                base_personality
            )
            
            group.ai_personality = custom_prompt
            
            # Update custom prompts
            custom_prompts = group.custom_prompts or {}
            custom_prompts.update({
                "personality_traits": personality_traits,
                "custom_responses": personality_traits.get("custom_responses", {}),
                "communication_style": personality_traits.get("communication_style", "professional")
            })
            
            group.custom_prompts = custom_prompts
            self.db.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"Error customizing AI personality: {str(e)}")
            self.db.rollback()
            return False
    
    def get_business_specific_features(self, business_type: BusinessType) -> Dict[str, Any]:
        """
        Get features specific to a business type
        """
        config = self.business_configs.get(business_type, self.business_configs[BusinessType.GENERAL])
        
        return {
            "inventory_features": self._get_inventory_features(config["inventory_type"]),
            "order_features": self._get_order_features(config["order_flow"]),
            "ai_features": self._get_ai_features(config["ai_personality"]),
            "analytics_features": self._get_analytics_features(business_type),
            "payment_features": self._get_payment_features(config["payment_methods"])
        }
    
    def validate_business_setup(self, group_id: int) -> Dict[str, Any]:
        """
        Validate that a business is properly configured
        """
        try:
            group = self.db.query(Group).filter(Group.id == group_id).first()
            if not group:
                return {"valid": False, "error": "Group not found"}
            
            validation_results = {
                "valid": True,
                "warnings": [],
                "recommendations": []
            }
            
            # Check basic configuration
            if not group.business_type:
                validation_results["warnings"].append("Business type not set")
            
            if not group.welcome_message:
                validation_results["recommendations"].append("Set a welcome message for customers")
            
            if not group.contact_phone:
                validation_results["warnings"].append("Contact phone number not set")
            
            if not group.operating_hours:
                validation_results["recommendations"].append("Set operating hours for better customer experience")
            
            # Check business-specific requirements
            business_config = self.business_configs.get(group.business_type, {})
            
            if group.business_type in [BusinessType.RESTAURANT, BusinessType.PHARMACY]:
                if not group.delivery_areas:
                    validation_results["recommendations"].append("Set delivery areas for your business")
            
            if group.business_type == BusinessType.SERVICES:
                if not group.business_settings or "service_duration" not in group.business_settings:
                    validation_results["warnings"].append("Service duration settings not configured")
            
            # Check product catalog
            from app.models import Product
            product_count = self.db.query(Product).filter(
                Product.group_id == group_id,
                Product.is_active == True
            ).count()
            
            if product_count == 0:
                validation_results["warnings"].append("No products added to catalog")
            elif product_count < 5:
                validation_results["recommendations"].append("Consider adding more products to your catalog")
            
            # Overall validation
            validation_results["valid"] = len(validation_results["warnings"]) == 0
            validation_results["setup_score"] = self._calculate_setup_score(group, product_count)
            
            return validation_results
            
        except Exception as e:
            logger.error(f"Error validating business setup: {str(e)}")
            return {"valid": False, "error": str(e)}
    
    # ==========================================
    # PRIVATE HELPER METHODS
    # ==========================================
    
    def _get_ai_prompts(self, business_type: BusinessType) -> Dict[str, str]:
        """Get AI prompts specific to business type"""
        prompts = {
            BusinessType.RESTAURANT: {
                "order_taking": "I'm here to help you order delicious food! What would you like to try today?",
                "menu_inquiry": "Let me help you explore our menu. Are you looking for anything specific?",
                "dietary_requirements": "Do you have any dietary requirements or allergies I should know about?"
            },
            BusinessType.PHARMACY: {
                "medicine_inquiry": "I can help you find the medications you need. Do you have a prescription?",
                "health_advice": "For health advice, please consult with our pharmacist or your doctor.",
                "dosage_info": "Let me provide you with the dosage information for this medication."
            },
            BusinessType.FASHION: {
                "style_consultation": "I'd love to help you find the perfect style! What occasion are you shopping for?",
                "size_guidance": "Let me help you find the right size. What size do you usually wear?",
                "trend_info": "Here are some trending styles that might interest you."
            }
        }
        
        return prompts.get(business_type, {
            "general_greeting": "Hello! How can I help you today?",
            "product_inquiry": "I'd be happy to help you find what you're looking for.",
            "order_assistance": "Let me assist you with your order."
        })
    
    def _get_business_intents(self, business_type: BusinessType) -> List[str]:
        """Get business-specific intents for AI understanding"""
        intents = {
            BusinessType.RESTAURANT: ["menu_inquiry", "dietary_restrictions", "table_booking", "delivery_time"],
            BusinessType.PHARMACY: ["prescription_inquiry", "dosage_question", "drug_interaction", "health_advice"],
            BusinessType.FASHION: ["size_inquiry", "style_consultation", "color_options", "trend_inquiry"],
            BusinessType.ELECTRONICS: ["technical_specs", "compatibility_check", "warranty_info", "installation"],
            BusinessType.SERVICES: ["appointment_booking", "service_inquiry", "availability_check", "pricing_info"]
        }
        
        return intents.get(business_type, ["general_inquiry", "product_info", "pricing"])
    
    def _generate_ai_personality_prompt(self, business_type: BusinessType, business_name: str) -> str:
        """Generate AI personality prompt based on business type"""
        personality_templates = {
            BusinessType.RESTAURANT: f"You are a friendly assistant for {business_name}, a restaurant. You're knowledgeable about our menu, ingredients, and can help customers make delicious choices. Be warm, food-enthusiastic, and helpful with dietary requirements.",
            
            BusinessType.PHARMACY: f"You are a professional assistant for {business_name} pharmacy. You're knowledgeable about medications and health products, but always recommend consulting with pharmacists or doctors for medical advice. Be professional, caring, and health-focused.",
            
            BusinessType.FASHION: f"You are a style-conscious assistant for {business_name}. You're knowledgeable about fashion trends, sizes, and styling. Be fashionable, encouraging, and help customers find their perfect look.",
            
            BusinessType.ELECTRONICS: f"You are a tech-savvy assistant for {business_name}. You're knowledgeable about electronic products, specifications, and compatibility. Be precise, technical when needed, but explain things clearly.",
            
            BusinessType.SERVICES: f"You are a professional assistant for {business_name}. You're knowledgeable about our services, booking procedures, and can help schedule appointments. Be efficient, professional, and service-oriented."
        }
        
        return personality_templates.get(business_type, 
            f"You are a helpful assistant for {business_name}. You're knowledgeable about our products and services. Be professional, friendly, and assist customers with their needs."
        )
    
    def _get_default_operating_hours(self, business_type: BusinessType) -> Dict[str, Any]:
        """Get default operating hours based on business type"""
        hours_templates = {
            BusinessType.RESTAURANT: {
                "monday": {"open": "10:00", "close": "22:00"},
                "tuesday": {"open": "10:00", "close": "22:00"},
                "wednesday": {"open": "10:00", "close": "22:00"},
                "thursday": {"open": "10:00", "close": "22:00"},
                "friday": {"open": "10:00", "close": "23:00"},
                "saturday": {"open": "10:00", "close": "23:00"},
                "sunday": {"open": "12:00", "close": "21:00"}
            },
            BusinessType.PHARMACY: {
                "monday": {"open": "08:00", "close": "20:00"},
                "tuesday": {"open": "08:00", "close": "20:00"},
                "wednesday": {"open": "08:00", "close": "20:00"},
                "thursday": {"open": "08:00", "close": "20:00"},
                "friday": {"open": "08:00", "close": "20:00"},
                "saturday": {"open": "09:00", "close": "18:00"},
                "sunday": {"open": "10:00", "close": "16:00"}
            }
        }
        
        return hours_templates.get(business_type, {
            "monday": {"open": "09:00", "close": "18:00"},
            "tuesday": {"open": "09:00", "close": "18:00"},
            "wednesday": {"open": "09:00", "close": "18:00"},
            "thursday": {"open": "09:00", "close": "18:00"},
            "friday": {"open": "09:00", "close": "18:00"},
            "saturday": {"open": "09:00", "close": "17:00"},
            "sunday": {"closed": True}
        })
    
    def _get_sample_products(self, business_type: BusinessType) -> List[Dict[str, Any]]:
        """Get sample products for business type setup"""
        samples = {
            BusinessType.RESTAURANT: [
                {"name": "Chicken Pizza", "category": "food", "price": 1200, "description": "Delicious chicken pizza with fresh vegetables"},
                {"name": "Beef Burger", "category": "food", "price": 800, "description": "Juicy beef burger with fries"},
                {"name": "Fresh Juice", "category": "beverages", "price": 300, "description": "Freshly squeezed fruit juice"}
            ],
            BusinessType.FASHION: [
                {"name": "Cotton T-Shirt", "category": "clothing", "price": 1500, "description": "Comfortable cotton t-shirt"},
                {"name": "Denim Jeans", "category": "clothing", "price": 3500, "description": "Classic denim jeans"},
                {"name": "Leather Belt", "category": "accessories", "price": 2000, "description": "Genuine leather belt"}
            ]
        }
        
        return samples.get(business_type, [])
    
    def _get_setup_checklist(self, business_type: BusinessType) -> List[Dict[str, Any]]:
        """Get setup checklist for business type"""
        checklist = [
            {"task": "Set business information", "description": "Add business name, description, and contact details", "required": True},
            {"task": "Configure AI personality", "description": "Customize how your AI assistant interacts with customers", "required": False},
            {"task": "Add products/services", "description": "Build your product catalog", "required": True},
            {"task": "Set payment methods", "description": "Configure accepted payment options", "required": True},
            {"task": "Test the system", "description": "Test orders and customer interactions", "required": True}
        ]
        
        # Add business-specific checklist items
        if business_type == BusinessType.RESTAURANT:
            checklist.insert(2, {"task": "Set up menu categories", "description": "Organize your menu items", "required": True})
            checklist.insert(3, {"task": "Configure delivery areas", "description": "Set where you deliver", "required": False})
        
        elif business_type == BusinessType.PHARMACY:
            checklist.insert(2, {"task": "Set up medicine categories", "description": "Organize medicines and health products", "required": True})
            checklist.insert(3, {"task": "Configure prescription handling", "description": "Set up prescription verification process", "required": True})
        
        return checklist
    
    def _calculate_setup_score(self, group: Group, product_count: int) -> int:
        """Calculate setup completion score (0-100)"""
        score = 0
        
        # Basic info (30 points)
        if group.name: score += 5
        if group.description: score += 5
        if group.contact_phone: score += 10
        if group.contact_email: score += 5
        if group.welcome_message: score += 5
        
        # Business configuration (30 points)
        if group.business_type: score += 10
        if group.business_settings: score += 10
        if group.operating_hours: score += 5
        if group.payment_methods: score += 5
        
        # Products (30 points)
        if product_count > 0:
            score += min(30, product_count * 3)  # Up to 30 points for products
        
        # AI configuration (10 points)
        if group.ai_personality: score += 5
        if group.custom_prompts: score += 5
        
        return min(100, score)


def get_business_config_service(db: Session) -> BusinessConfigService:
    """Get business configuration service instance"""
    return BusinessConfigService(db)