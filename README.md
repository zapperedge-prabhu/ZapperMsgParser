# MsgParser

A collection of three standalone Python parsers for the most common healthcare message formats — **HL7 v2.x**, **FHIR R4**, and **C-CDA**.

- Zero external dependencies (standard library only)
- Python 3.9 or newer
- Each parser lives in a single file — copy what you need

---

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [HL7 v2.x Parser](#hl7-v2x-parser)
- [FHIR R4 Parser](#fhir-r4-parser)
- [C-CDA Parser](#c-cda-parser)
- [Running the Built-in Demos](#running-the-built-in-demos)
- [Error Handling](#error-handling)
- [Output Format](#output-format)

---

## Overview

| Parser | File | Standard | Input Format |
|---|---|---|---|
| HL7 Parser | `hl7_parser.py` | HL7 v2.3 – v2.7 | Pipe-delimited text |
| FHIR Parser | `fhir_parser.py` | FHIR R4 (4.0.1) | JSON string or dict |
| C-CDA Parser | `ccda_parser.py` | C-CDA R2.1 / CDA R2 | XML file or string |

---

## Requirements

- Python 3.9 or newer
- No third-party packages required

---

## Installation

Clone the repository:

```bash
git clone https://github.com/your-org/msgparser.git
cd msgparser
```

No `pip install` step is needed. The parsers use only the Python standard library.

---

## Quick Start

```python
from hl7_parser  import HL7Parser
from fhir_parser import FHIRParser
from ccda_parser import CCDAParser

# --- HL7 ---
hl7    = HL7Parser()
result = hl7.parse(raw_hl7_string)

# --- FHIR ---
fhir   = FHIRParser()
result = fhir.parse(json_string_or_dict)

# --- C-CDA ---
ccda   = CCDAParser()
result = ccda.parse_file("patient.xml")
# or from a string:
result = ccda.parse_string(xml_string)

# All parsers share the same conventions:
print(result.success)    # True / False
print(result.to_json())  # Full structured JSON output
```

---

## HL7 v2.x Parser

### Supported Message Types

| Code | Description |
|---|---|
| ADT | Admit / Discharge / Transfer |
| ORU | Observation Result (lab results) |
| ORM | Order Message |
| SIU | Scheduling Information |
| MDM | Medical Document Management |
| ACK | Acknowledgement |

### Supported Segments

`MSH` `PID` `PV1` `OBR` `OBX` `DG1` `AL1` `IN1` `NTE` `EVN` `ORC` `RXA`

### Usage

```python
from hl7_parser import HL7Parser

parser = HL7Parser()
result = parser.parse(raw_hl7_string)

print(result.success)        # True / False
print(result.message_type)   # e.g. "HL7_ADT_A01"
print(result.warnings)       # list of non-fatal issues
print(result.errors)         # list of parse errors
```

### Result Object — `HL7ParseResult`

| Attribute | Type | Description |
|---|---|---|
| `success` | `bool` | Whether the message parsed without errors |
| `message_type` | `str` | Detected message type (e.g. `HL7_ADT_A01`) |
| `summary` | `dict` | Structured clinical data |
| `raw_data` | `dict` | All parsed segments, keyed by segment name |
| `errors` | `list` | Fatal parse errors |
| `warnings` | `list` | Non-fatal warnings |

### Convenience Methods

```python
result.get_patient()      # → dict  (name, MRN, DOB, sex, address, phone)
result.get_visit()        # → dict  (class, location, attending, service)
result.get_diagnoses()    # → list  (code, description, type)
result.get_allergies()    # → list  (allergen, reaction, severity)
result.get_lab_results()  # → dict  (observations, ordering provider, status)
result.get_insurance()    # → dict  (company, plan type, policy number)
result.to_json()          # → str   (full JSON output)
```

### Example

```python
from hl7_parser import HL7Parser

hl7_message = (
    "MSH|^~\\&|HIS|HOSPITAL|LAB|DEPT|20240315120000||ADT^A01|MSG001|P|2.5\r"
    "PID|1||MR123456^^^HOSP^MR||SMITH^JOHN^WILLIAM||19850322|M|||123 MAIN ST^^CHICAGO^IL^60601\r"
    "PV1|1|I|ICU^101^A||||12345^JOHNSON^EMILY|||CARD\r"
    "DG1|1||I21.9^Acute myocardial infarction^ICD10|"
)

parser = HL7Parser()
result = parser.parse(hl7_message)

if result.success:
    pt = result.get_patient()
    print(pt["family_name"], pt["given_name"])  # SMITH JOHN

    for dx in result.get_diagnoses():
        print(dx["code"], dx["description"])
```

---

## FHIR R4 Parser

### Supported Resource Types

`Patient` · `Observation` · `Encounter` · `DiagnosticReport` · `MedicationRequest` · `Condition` · `AllergyIntolerance` · `Procedure` · `Immunization` · `Bundle` · `Practitioner` · `Organization` · `Coverage`

### Usage

```python
from fhir_parser import FHIRParser

parser = FHIRParser()

# From a JSON string
result = parser.parse(json_string)

# From a Python dict
result = parser.parse(fhir_dict)

# Parse a list of resources in one call
results = parser.parse_batch([resource1, resource2, resource3])
```

### Result Object — `FHIRParseResult`

| Attribute | Type | Description |
|---|---|---|
| `success` | `bool` | Whether the resource parsed without errors |
| `resource_type` | `str` | Detected FHIR resource type (e.g. `Patient`) |
| `summary` | `dict` | Normalised clinical data |
| `raw_data` | `dict` | Original parsed JSON as a dict |
| `errors` | `list` | Fatal parse errors |
| `warnings` | `list` | Non-fatal warnings |

```python
result.to_json()   # → str  (full JSON output)
```

### What Each Resource Summary Contains

**Patient**
- Name (family, given, prefix), identifiers (MRN, SSN), birth date, gender
- Address, phone, email
- Language, marital status, managing organization, general practitioner

**Observation**
- Code (LOINC), value and units, reference range, interpretation
- Status, effective date, subject reference

**Encounter**
- Class, status, period (start / end)
- Participants, diagnosis list, location, reason

**DiagnosticReport**
- Code, status, effective date
- Results (referenced observations), conclusion

**MedicationRequest**
- Medication name and code, status, intent
- Dosage instructions, route, frequency, prescriber

**Condition**
- Code (ICD-10), clinical status, severity, onset date, note

**AllergyIntolerance**
- Allergen, type, category, criticality
- Reactions and severity

**Bundle**
- Bundle type, timestamp, entry count
- Summary of resource types contained

### Example

```python
import json
from fhir_parser import FHIRParser

patient_json = {
    "resourceType": "Patient",
    "id": "pt-001",
    "name": [{"use": "official", "family": "Smith", "given": ["John"]}],
    "birthDate": "1985-03-22",
    "gender": "male"
}

parser = FHIRParser()
result = parser.parse(patient_json)

if result.success:
    print(result.resource_type)            # Patient
    print(result.summary["family_name"])   # Smith
    print(result.summary["birth_date"])    # 1985-03-22
```

### Batch Parsing a Bundle

```python
resources = [patient_dict, observation_dict, condition_dict]
results = parser.parse_batch(resources)

for r in results:
    print(r.resource_type, r.success)
```

---

## C-CDA Parser

### Supported Document Types

| LOINC Code | Document Type |
|---|---|
| 34133-9 | Continuity of Care Document (CCD) |
| 11488-4 | Consultation Note |
| 18842-5 | Discharge Summary |
| 34117-2 | History and Physical |
| 11506-3 | Progress Note |
| 57133-1 | Referral Note |
| 11504-8 | Operative Note |
| 18748-4 | Diagnostic Imaging Report |
| 34109-9 | Evaluation and Management Note |
| 51851-4 | Administrative Note |

### Supported Sections

`Allergies` · `Medications` · `Problems / Diagnoses` · `Vital Signs` · `Lab Results` · `Procedures` · `Immunizations` · `Social History` · `Family History` · `Encounters` · `Plan of Care` · `Payers / Insurance` · `Medical Equipment` · `Discharge Diagnosis` · `Discharge Instructions` · `Chief Complaint` · `Assessment` · `Advance Directives` · `Nutrition` · and more

### Usage

```python
from ccda_parser import CCDAParser

parser = CCDAParser()

# Parse from a file path
result = parser.parse_file("patient.xml")

# Parse from an XML string
result = parser.parse_string(xml_string)
```

### Result Object — `CCDAParseResult`

| Attribute | Type | Description |
|---|---|---|
| `success` | `bool` | Whether the document parsed without errors |
| `document_type` | `str` | Detected document type (e.g. `Continuity of Care Document (CCD)`) |
| `patient` | `dict` | Patient demographics |
| `author` | `dict` | Authoring provider / system |
| `custodian` | `dict` | Custodian organisation |
| `document_meta` | `dict` | Document ID, effective time, confidentiality |
| `sections` | `dict` | All parsed sections, keyed by section name |
| `errors` | `list` | Fatal parse errors |
| `warnings` | `list` | Non-fatal warnings |

### Convenience Methods

```python
result.section_names()         # → list  of section keys found in the document
result.get_section("vitals")   # → dict  for any section by name

result.get_all_medications()   # → list  of medication entries
result.get_all_problems()      # → list  of problem / diagnosis entries
result.get_all_allergies()     # → list  of allergy entries
result.get_all_results()       # → list  of lab result panels
result.get_all_vitals()        # → list  of vital sign groups

result.to_json()               # → str   full JSON output
```

### Section Name Reference

Use these keys with `get_section()` or to check `section_names()`:

```
allergies          medications        problems           vital_signs
results            procedures         immunizations      social_history
family_history     encounters         plan_of_care       payers
functional_status  mental_status      medical_equipment  discharge_diagnosis
discharge_instructions  reason_for_visit  chief_complaint   assessment
advance_directives nutrition
```

### Example

```python
from ccda_parser import CCDAParser

parser = CCDAParser()
result = parser.parse_file("patient_ccd.xml")

if result.success:
    print(result.document_type)
    print("Sections found:", result.section_names())

    # Patient demographics
    pt = result.patient
    print(pt["name"], pt["dob"], pt["gender"])

    # Medications
    for med in result.get_all_medications():
        print(med["medication"], med["dose"], med["route"])

    # Allergies
    for allergy in result.get_all_allergies():
        print(allergy["allergen"], allergy["reaction"], allergy["severity"])

    # Lab results
    for panel in result.get_all_results():
        print(f"Panel: {panel['panel']} ({panel['panel_datetime']})")
        for obs in panel["observations"]:
            flag = " [ABNORMAL]" if obs["is_abnormal"] else ""
            print(f"  {obs['test']}: {obs['display']}{flag}")

    # Full JSON dump
    print(result.to_json())
```

---

## Running the Built-in Demos

Each parser ships with a self-contained demo using realistic synthetic data. No external files are needed.

```bash
# Run all demos at once
python main.py

# Run individual demos
python hl7_parser.py
python fhir_parser.py
python ccda_parser.py
```

---

## Error Handling

All parsers catch exceptions internally and return a result object — they never raise on bad input.

```python
result = parser.parse("this is not valid HL7")

if not result.success:
    for err in result.errors:
        print("Error:", err)
    for warn in result.warnings:
        print("Warning:", warn)
```

Errors are populated for malformed or unrecognised input. Warnings are used for recoverable issues such as missing optional fields or unrecognised section codes.

---

## Output Format

Every result object exposes a `to_json()` method that returns a consistently structured JSON string:

```json
{
  "success": true,
  "message_type": "HL7_ADT_A01",
  "summary": { ... },
  "raw_data": { ... },
  "errors": [],
  "warnings": []
}
```

For C-CDA the top-level keys are `document_type`, `patient`, `author`, `custodian`, `document_meta`, and `sections` instead of `summary` and `raw_data`.

---

## License

MIT
