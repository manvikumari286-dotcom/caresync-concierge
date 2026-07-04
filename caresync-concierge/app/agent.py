# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import re
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

import os
from mcp import StdioServerParameters
from google.adk.tools import McpToolset
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import Workflow, START, node
from google.adk.tools.agent_tool import AgentTool
from google.adk.events import Event, RequestInput
from app.config import config

# ---------------------------------------------------------------------------
# MCP Connection & Toolset
# ---------------------------------------------------------------------------

mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="uv",
        args=["run", "--project", "caresync-concierge", os.path.join(os.path.dirname(__file__), "mcp_server.py")],
    )
)

# ---------------------------------------------------------------------------
# State Schema
# ---------------------------------------------------------------------------

class CareSyncState(BaseModel):
    patient_query: str = ""
    pii_scrubbed_query: str = ""
    route_action: str = ""
    final_report: str = ""
    security_status: str = "PENDING"
    needs_human_approval: bool = False
    human_approval_decision: str = ""  # e.g., 'APPROVED', 'REJECTED'

# ---------------------------------------------------------------------------
# Specialized Agents
# ---------------------------------------------------------------------------

medication_agent = Agent(
    name="medication_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are a specialized Medication Assistant. You help patients log medications, check dosage instructions, "
        "and track refills. Summarize the user's medication log or confirm new entries. "
        "Use the patient's full name (default to 'John Doe' if not specified) to query their medications."
    ),
    tools=[mcp_toolset]
)

appointment_agent = Agent(
    name="appointment_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are a specialized Appointment Coordinator. You help patients coordinate doctor visits, "
        "manage schedules, and suggest calendar slots. If a user wants to book or cancel an appointment, "
        "clarify details and provide options. "
        "Use the patient's full name (default to 'John Doe' if not specified) to query their appointments."
    ),
    tools=[mcp_toolset]
)

symptom_agent = Agent(
    name="symptom_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are a specialized Symptom & Vitals Tracker. You help patients log symptoms (e.g. pain, fatigue) "
        "and vitals (e.g. blood pressure, glucose). Provide healthy, non-diagnostic insights and summaries. "
        "Use the patient's full name (default to 'John Doe' if not specified) to log symptoms."
    ),
    tools=[mcp_toolset]
)

# ---------------------------------------------------------------------------
# Orchestrator Agent
# ---------------------------------------------------------------------------

orchestrator = Agent(
    name="orchestrator",
    model=Gemini(model=config.model),
    instruction=(
        "You are the CareSync Concierge Orchestrator. Your job is to understand the patient's request and "
        "delegate it to the appropriate specialized sub-agent (Medication Assistant, Appointment Coordinator, "
        "or Symptom Tracker) using your tools. "
        "Once you have gathered the responses from the specialists, synthesize them into a friendly, clear, "
        "and concise final answer."
    ),
    tools=[
        AgentTool(agent=medication_agent),
        AgentTool(agent=appointment_agent),
        AgentTool(agent=symptom_agent)
    ]
)

# ---------------------------------------------------------------------------
# Workflow Nodes
# ---------------------------------------------------------------------------

logger = logging.getLogger("security_checkpoint")

def audit_log(severity: str, event_type: str, details: dict[str, Any]):
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "severity": severity,
        "event_type": event_type,
        "details": details
    }
    print(f"AUDIT_LOG: {json.dumps(log_entry)}")
    logger.log(getattr(logging, severity, logging.INFO), json.dumps(log_entry))


@node(name="security_checkpoint")
async def security_checkpoint(ctx: Any, node_input: Any) -> Event:
    query = str(node_input or "")
    ctx.state["patient_query"] = query
    
    # 1. PII Scrubbing (Email, Phone, medical ID)
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    phone_pattern = r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
    mrn_pattern = r'\bMRN-\d{5,8}\b'
    
    scrubbed = query
    scrubbed = re.sub(email_pattern, "[EMAIL_REDACTED]", scrubbed)
    scrubbed = re.sub(phone_pattern, "[PHONE_REDACTED]", scrubbed)
    scrubbed = re.sub(mrn_pattern, "[MRN_REDACTED]", scrubbed)
    
    ctx.state["pii_scrubbed_query"] = scrubbed
    
    # 2. Prompt Injection Detection
    injection_keywords = [
        "ignore prior", "ignore instructions", "ignore above", 
        "system prompt", "override instructions", "bypass security",
        "you must instead", "forget your system"
    ]
    
    has_injection = any(kw in query.lower() for kw in injection_keywords)
    if has_injection:
        audit_log("CRITICAL", "PROMPT_INJECTION_DETECTED", {"query": query})
        ctx.state["final_report"] = "Security Block: Prompt injection attempt detected. Request denied."
        ctx.state["security_status"] = "BLOCKED"
        return Event(route="SECURITY_EVENT")
    
    # 3. Domain-specific rule (Healthcare context check)
    healthcare_keywords = [
        "health", "med", "appointment", "doctor", "symptom", "pain", "refill", 
        "glucose", "blood", "vitals", "clinic", "fever", "cough", "dose", "pill",
        "log", "schedule", "visit", "physician", "checkup", "patient", "care"
    ]
    is_healthcare = any(kw in query.lower() for kw in healthcare_keywords)
    if not is_healthcare:
        audit_log("WARNING", "OUT_OF_DOMAIN_QUERY", {"query": scrubbed})
        ctx.state["final_report"] = "CareSync Concierge is specialized in chronic disease management and healthcare concierge tasks. Please ask a healthcare-related question."
        ctx.state["security_status"] = "OFF_DOMAIN"
        return Event(route="SECURITY_EVENT")
        
    audit_log("INFO", "SECURITY_PASS", {"scrubbed_query": scrubbed})
    ctx.state["security_status"] = "PASS"
    return Event(route="PASS")


@node(name="orchestrator_node", rerun_on_resume=True)
async def orchestrator_node(ctx: Any, node_input: Any) -> Event:
    query = ctx.state.get("pii_scrubbed_query") or ctx.state.get("patient_query") or ""
    
    # If appointment scheduling, require human confirmation first
    is_appointment_request = any(kw in query.lower() for kw in ["schedule", "book", "cancel", "appointment", "visit", "doctor"])
    
    if is_appointment_request and ctx.state.get("human_approval_decision") != "APPROVED":
        ctx.state["needs_human_approval"] = True
        return Event(route="NEEDS_REVIEW")
        
    # Delegate query to orchestrator agent
    orchestrator_response = await ctx.run_node(orchestrator, node_input=query)
    
    # Prefix notice if scheduling was rejected
    if ctx.state.get("human_approval_decision") == "REJECTED":
        final_text = f"Notice: Appointment scheduling request was not confirmed by user.\n\n{orchestrator_response}"
    else:
        final_text = orchestrator_response
        
    ctx.state["final_report"] = final_text
    return Event(route="COMPLETE")


@node(name="human_approval_node", rerun_on_resume=True)
async def human_approval_node(ctx: Any, node_input: Any) -> Event:
    interrupt_id = "appointment_approval"
    
    # If resuming and response is in resume_inputs, process it
    if ctx.resume_inputs and interrupt_id in ctx.resume_inputs:
        decision = ctx.resume_inputs.get(interrupt_id)
        if str(decision).lower() in ["yes", "approve", "approved", "confirm"]:
            ctx.state["human_approval_decision"] = "APPROVED"
        else:
            ctx.state["human_approval_decision"] = "REJECTED"
            
        ctx.state["needs_human_approval"] = False
        yield Event(output="Approval processed.")
        return
        
    # Yield RequestInput to pause workflow and ask user
    yield RequestInput(
        interrupt_id=interrupt_id,
        message="Please approve or reject the doctor appointment scheduling request (Reply 'yes' or 'no').",
        response_schema=str
    )


@node(name="final_output_node")
async def final_output_node(ctx: Any, node_input: Any) -> str:
    return ctx.state.get("final_report") or "No output generated."


# ---------------------------------------------------------------------------
# Workflow Orchestration Graph
# ---------------------------------------------------------------------------

root_agent = Workflow(
    name="root_agent",
    edges=[
        ("START", security_checkpoint),
        (security_checkpoint, {"PASS": orchestrator_node, "SECURITY_EVENT": final_output_node}),
        (orchestrator_node, {"NEEDS_REVIEW": human_approval_node, "COMPLETE": final_output_node}),
        (human_approval_node, orchestrator_node)
    ],
    state_schema=CareSyncState
)

app = App(
    root_agent=root_agent,
    name="app",
)
