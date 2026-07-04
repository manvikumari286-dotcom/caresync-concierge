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

import sys
import logging
import datetime
from typing import Any
from mcp.server.fastmcp import FastMCP

# Setup logging to stderr because stdout is reserved for JSON-RPC messages
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("caresync_mcp_server")

# Initialize the FastMCP Server
mcp = FastMCP("CareSync MCP Server")

# In-memory database representing patients' chronic disease records
PATIENTS_DB = {
    "John Doe": {
        "medications": [
            {"name": "Lisinopril", "dosage": "10mg", "frequency": "Once daily", "refill_date": "2026-07-20"},
            {"name": "Metformin", "dosage": "500mg", "frequency": "Twice daily with meals", "refill_date": "2026-08-01"}
        ],
        "appointments": [
            {"doctor": "Dr. Sarah Jenkins (Cardiologist)", "datetime": "2026-07-15T10:00:00", "location": "Suite 402, Cardio Clinic"},
            {"doctor": "Dr. Alan Mercer (Primary Care)", "datetime": "2026-08-05T14:30:00", "location": "Main Health Center"}
        ],
        "symptoms": [
            {"timestamp": "2026-07-01T08:00:00", "symptom": "Mild headache", "severity": 3, "notes": "Resolved after drinking water"},
            {"timestamp": "2026-07-04T20:00:00", "symptom": "Fatigue", "severity": 5, "notes": "Felt tired after light walking"}
        ]
    }
}


@mcp.tool()
def get_patient_medications(patient_name: str) -> str:
    """Retrieve the medication list, dosages, frequencies, and next refill dates for a patient.
    
    Args:
        patient_name: The full name of the patient.
    """
    logger.info(f"Fetching medications for patient: {patient_name}")
    patient = PATIENTS_DB.get(patient_name)
    if not patient:
        return f"Patient '{patient_name}' not found."
    
    meds = patient["medications"]
    if not meds:
        return f"No medications found for patient '{patient_name}'."
    
    lines = [f"Medications for {patient_name}:"]
    for med in meds:
        lines.append(f"- {med['name']} ({med['dosage']}): {med['frequency']} (Refill: {med['refill_date']})")
    return "\n".join(lines)


@mcp.tool()
def update_patient_medication(patient_name: str, med_name: str, dosage: str, frequency: str) -> str:
    """Add a new medication or update an existing medication's dosage and frequency for a patient.
    
    Args:
        patient_name: The full name of the patient.
        med_name: The name of the medication.
        dosage: The dosage (e.g. '10mg').
        frequency: How often the medication is taken (e.g. 'Once daily').
    """
    logger.info(f"Updating medication '{med_name}' for patient: {patient_name}")
    if patient_name not in PATIENTS_DB:
        PATIENTS_DB[patient_name] = {"medications": [], "appointments": [], "symptoms": []}
    
    meds = PATIENTS_DB[patient_name]["medications"]
    for med in meds:
        if med["name"].lower() == med_name.lower():
            med["dosage"] = dosage
            med["frequency"] = frequency
            med["refill_date"] = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
            return f"Updated medication '{med_name}' for {patient_name} to {dosage}, {frequency}."
            
    new_med = {
        "name": med_name,
        "dosage": dosage,
        "frequency": frequency,
        "refill_date": (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    }
    meds.append(new_med)
    return f"Successfully added medication '{med_name}' ({dosage}) to {patient_name}'s record."


@mcp.tool()
def get_appointments(patient_name: str) -> str:
    """Retrieve all upcoming doctor appointments and consultations for a patient.
    
    Args:
        patient_name: The full name of the patient.
    """
    logger.info(f"Fetching appointments for patient: {patient_name}")
    patient = PATIENTS_DB.get(patient_name)
    if not patient:
        return f"Patient '{patient_name}' not found."
    
    appts = patient["appointments"]
    if not appts:
        return f"No appointments found for patient '{patient_name}'."
    
    lines = [f"Upcoming appointments for {patient_name}:"]
    for appt in appts:
        lines.append(f"- {appt['doctor']} on {appt['datetime']} at {appt['location']}")
    return "\n".join(lines)


@mcp.tool()
def log_patient_symptom(patient_name: str, symptom: str, severity: int, notes: str) -> str:
    """Log a symptom entry with its severity level and notes for a patient.
    
    Args:
        patient_name: The full name of the patient.
        symptom: Description of the symptom (e.g. 'Nausea', 'Knee pain').
        severity: Severity score from 1 (mild) to 10 (severe).
        notes: Additional contextual notes.
    """
    logger.info(f"Logging symptom '{symptom}' for patient: {patient_name}")
    if patient_name not in PATIENTS_DB:
        PATIENTS_DB[patient_name] = {"medications": [], "appointments": [], "symptoms": []}
        
    symptom_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "symptom": symptom,
        "severity": severity,
        "notes": notes
    }
    PATIENTS_DB[patient_name]["symptoms"].append(symptom_entry)
    return f"Logged symptom '{symptom}' (Severity: {severity}/10) for {patient_name} successfully."


if __name__ == "__main__":
    mcp.run()
