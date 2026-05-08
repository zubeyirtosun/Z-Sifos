import logging
import json
from typing import Annotated, List, Dict, Any, TypedDict, Union, Tuple
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from .intent_classifier import get_intent

logger = logging.getLogger(__name__)

# --- State Definition ---

class AgentState(TypedDict):
    # The list of messages in the conversation
    messages: Annotated[List[BaseMessage], lambda x, y: x + y]
    # The detected intent from IntentClassifier
    intent: str
    # Confidence score of the intent
    intent_score: float
    # Current active expert node
    active_expert: str
    # Results gathered by specialists
    data_pool: Dict[str, Any]
    # Final answer synthesis
    final_answer: str
    # Metadata for SSE (Accumulated)
    metadata: Annotated[List[Dict[str, Any]], lambda x, y: x + y]
    # Planning Flags
    planning_mode: bool
    plan_approved: bool
    execution_plan: str

# --- Nodes ---

def router_node(state: AgentState):
    """Analyzes the user input and routes to the correct specialist."""
    last_message_content = state["messages"][-1].content
    
    # Extract text if it's a multimodal list
    if isinstance(last_message_content, list):
        text_content = ""
        for part in last_message_content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_content += part.get("text", "")
        last_message_content = text_content
    
    intent_info = get_intent(last_message_content)
    
    intent = intent_info["intent"]
    score = intent_info["score"]
    
    # Simple routing logic
    next_node = "generalist" # default
    if intent == "SEARCH":
        next_node = "researcher"
    elif intent == "DOCUMENT":
        next_node = "doc_expert"
    elif intent == "TASK":
        next_node = "coder"

    # If planning is enabled and not yet approved, we shift to planner
    if state.get("planning_mode") and not state.get("plan_approved"):
        if intent in ["SEARCH", "TASK", "DOCUMENT"]:
            next_node = "planner"

    return {
        "intent": intent,
        "intent_score": score,
        "active_expert": next_node,
        "metadata": [{"type": "intent", "content": intent, "score": score}]
    }

def plan_node(state: AgentState):
    """Generates a step-by-step implementation plan based on the intent."""
    intent = state["intent"]
    logger.info(f"Generating plan for intent: {intent}")
    
    plan = f"### 📝 Uygulama Planı ({intent})\n"
    if intent == "SEARCH":
        plan += "1. DuckDuckGo üzerinden konuyla ilgili geniş bir arama yapılacak.\n2. En alakalı 3 kaynak seçilip içerikleri okunacak.\n3. Bulgular sentezlenip özetlenecek."
    elif intent == "TASK":
        plan += "1. İstek analiz edilecek.\n2. Gerekli kod yapısı oluşturulacak.\n3. Örnek uygulama ve test adımları sunulacak."
    elif intent == "DOCUMENT":
        plan += "1. Yüklenen belgeler taranacak.\n2. İlgili bölümler vektör veri tabanından çekilecek.\n3. Soruya belgeye dayalı cevap üretilecek."
        
    return {
        "execution_plan": plan,
        "metadata": [{"type": "plan", "content": plan}],
        "active_expert": "planner"
    }

def create_agent_node(agent_type: str):
    """Factory to create nodes that execute specific agent logic."""
    def agent_node(state: AgentState):
        logger.info(f"Executing {agent_type} specialist...")
        # In a full implementation, this node would invoke 
        # a specialized agent's predict_stream or predict method.
        # For our MVP, we signal the executor to focus on specific tools.
        return {
            "metadata": [{"type": "status", "content": f"Uzman Ajan ({agent_type}) devreye girdi..."}],
            "active_expert": agent_type
        }
    return agent_node

def synthesizer_node(state: AgentState):
    """Synthesizes results from specialists into a final answer."""
    # This node performs the 'hand-off' synthesis.
    # It takes data_pool results and crafts the final message.
    return {
        "metadata": [{"type": "status", "content": "Assistant synthesizing final answer..."}]
    }

# --- Graph Construction ---

def create_multi_agent_graph():
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("router", router_node)
    workflow.add_node("planner", plan_node)
    workflow.add_node("researcher", create_agent_node("search_expert"))
    workflow.add_node("doc_expert", create_agent_node("rag_expert"))
    workflow.add_node("coder", create_agent_node("code_expert"))
    workflow.add_node("generalist", synthesizer_node)
    
    # Define edges
    workflow.set_entry_point("router")
    
    workflow.add_conditional_edges(
        "router",
        lambda x: x["active_expert"],
        {
            "planner": "planner",
            "researcher": "researcher",
            "doc_expert": "doc_expert",
            "coder": "coder",
            "generalist": "generalist"
        }
    )
    
    # Planner stops execution to wait for approval (in LangGraph terms, it goes to END or we handle it via persistent state)
    # However, for this architecture, we let it hit END and the frontend will re-trigger with plan_approved=True
    workflow.add_edge("planner", END)
    
    workflow.add_edge("researcher", "generalist")
    workflow.add_edge("doc_expert", "generalist")
    workflow.add_edge("coder", "generalist")
    workflow.add_edge("generalist", END)
    
    return workflow.compile()

# Singleton instance
orchestrator = create_multi_agent_graph()
