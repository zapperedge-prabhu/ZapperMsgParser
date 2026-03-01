"""
╔══════════════════════════════════════════════════════════════════════╗
║           C-CDA DOCUMENT PARSER  -  Standalone                      ║
║                                                                      ║
║  Supports  : C-CDA R2.1 / CDA R2                                     ║
║  Doc Types : CCD · H&P · Discharge Summary · Progress Note          ║
║              Referral Note · Operative Note · Imaging Report         ║
║  Sections  : Allergies · Medications · Problems · Vitals · Labs     ║
║              Procedures · Immunizations · Social History · Family   ║
║              History · Encounters · Plan of Care · Payers + more    ║
║  Requires  : Python 3.9+  -  zero external dependencies              ║
╚══════════════════════════════════════════════════════════════════════╝

QUICK START:
    from ccda_parser import CCDAParser

    parser = CCDAParser()
    result = parser.parse_file("patient.xml")       # from file
    result = parser.parse_string(xml_string)        # from string

    print(result.success)                           # True / False
    print(result.document_type)                     # e.g. "Continuity of Care Document (CCD)"
    print(result.section_names())                   # sections found
    print(result.get_all_allergies())               # list of allergy dicts
    print(result.to_json())                         # full JSON output

Run as script for built-in demo:
    python ccda_parser.py
"""


import xml.etree.ElementTree as ET
import json
import re
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, field


# =============================================================================
# CCDA TEMPLATE IDs (LOINC / OID based section identifiers)
# =============================================================================

SECTION_TEMPLATES = {
    # Allergies
    "2.16.840.1.113883.10.20.22.2.6.1":  "allergies",
    "2.16.840.1.113883.10.20.22.2.6":    "allergies",
    # Medications
    "2.16.840.1.113883.10.20.22.2.1.1":  "medications",
    "2.16.840.1.113883.10.20.22.2.1":    "medications",
    # Problems / Active Diagnoses
    "2.16.840.1.113883.10.20.22.2.5.1":  "problems",
    "2.16.840.1.113883.10.20.22.2.5":    "problems",
    # Vital Signs
    "2.16.840.1.113883.10.20.22.2.4.1":  "vital_signs",
    "2.16.840.1.113883.10.20.22.2.4":    "vital_signs",
    # Results / Lab
    "2.16.840.1.113883.10.20.22.2.3.1":  "results",
    "2.16.840.1.113883.10.20.22.2.3":    "results",
    # Procedures
    "2.16.840.1.113883.10.20.22.2.7.1":  "procedures",
    "2.16.840.1.113883.10.20.22.2.7":    "procedures",
    # Immunizations
    "2.16.840.1.113883.10.20.22.2.2.1":  "immunizations",
    "2.16.840.1.113883.10.20.22.2.2":    "immunizations",
    # Social History
    "2.16.840.1.113883.10.20.22.2.17":   "social_history",
    # Family History
    "2.16.840.1.113883.10.20.22.2.15":   "family_history",
    # Encounters
    "2.16.840.1.113883.10.20.22.2.22.1": "encounters",
    "2.16.840.1.113883.10.20.22.2.22":   "encounters",
    # Plan of Care
    "2.16.840.1.113883.10.20.22.2.10":   "plan_of_care",
    # Functional Status
    "2.16.840.1.113883.10.20.22.2.14":   "functional_status",
    # Mental Status
    "2.16.840.1.113883.10.20.22.2.56":   "mental_status",
    # Payers / Insurance
    "2.16.840.1.113883.10.20.22.2.18":   "payers",
    # Medical Equipment
    "2.16.840.1.113883.10.20.22.2.23":   "medical_equipment",
    # Discharge Diagnoses
    "2.16.840.1.113883.10.20.22.2.24":   "discharge_diagnosis",
    # Discharge Instructions
    "2.16.840.1.113883.10.20.22.2.41":   "discharge_instructions",
    # Reason for Visit
    "2.16.840.1.113883.10.20.22.2.12":   "reason_for_visit",
    # Chief Complaint
    "2.16.840.1.113883.10.20.22.2.13":   "chief_complaint",
    # Assessment
    "2.16.840.1.113883.10.20.22.2.9":    "assessment",
    # Advance Directives
    "2.16.840.1.113883.10.20.22.2.21":   "advance_directives",
    # Nutrition
    "2.16.840.1.113883.10.20.22.2.57":   "nutrition",
}

# LOINC codes for document types
DOCUMENT_TYPES = {
    "34133-9":  "Continuity of Care Document (CCD)",
    "11488-4":  "Consultation Note",
    "18842-5":  "Discharge Summary",
    "34117-2":  "History and Physical",
    "11506-3":  "Progress Note",
    "57133-1":  "Referral Note",
    "11504-8":  "Operative Note",
    "18748-4":  "Diagnostic Imaging Report",
    "34109-9":  "Evaluation and Management Note",
    "51851-4":  "Administrative Note",
}

# HL7 namespaces used in CDA
NS = {
    "cda":  "urn:hl7-org:v3",
    "xsi":  "http://www.w3.org/2001/XMLSchema-instance",
    "sdtc": "urn:hl7-org:sdtc",
}


# =============================================================================
# RESULT DATA STRUCTURE
# =============================================================================

@dataclass
class CCDAParseResult:
    success: bool
    document_type: str
    patient: dict = field(default_factory=dict)
    author: dict = field(default_factory=dict)
    custodian: dict = field(default_factory=dict)
    document_meta: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps({
            "success": self.success,
            "document_type": self.document_type,
            "document_meta": self.document_meta,
            "patient": self.patient,
            "author": self.author,
            "custodian": self.custodian,
            "sections": self.sections,
            "errors": self.errors,
            "warnings": self.warnings,
        }, indent=indent, default=str)

    def section_names(self) -> list:
        """Return list of sections found in this document."""
        return list(self.sections.keys())

    def get_section(self, name: str) -> Optional[dict]:
        """Get a specific section by name."""
        return self.sections.get(name)

    def get_all_medications(self) -> list:
        return self.sections.get("medications", {}).get("entries", [])

    def get_all_problems(self) -> list:
        return self.sections.get("problems", {}).get("entries", [])

    def get_all_allergies(self) -> list:
        return self.sections.get("allergies", {}).get("entries", [])

    def get_all_results(self) -> list:
        return self.sections.get("results", {}).get("entries", [])

    def get_all_vitals(self) -> list:
        return self.sections.get("vital_signs", {}).get("entries", [])


# =============================================================================
# MAIN CCDA PARSER
# =============================================================================

class CCDAParser:
    """
    Parses C-CDA R2.1 / CDA R2 XML documents.

    Handles all standard document sections using templateId-based routing.
    Works with both file paths and raw XML strings.
    """

    def __init__(self):
        self._root = None
        self._ns = "urn:hl7-org:v3"
        self._warnings = []
        self._errors = []

    # ── Public Entry Points ────────────────────────────────────────────────────

    def parse_file(self, filepath: str) -> CCDAParseResult:
        """Parse a CCDA XML file from disk."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return self.parse_string(f.read())
        except FileNotFoundError:
            return CCDAParseResult(False, "UNKNOWN", errors=[f"File not found: {filepath}"])
        except Exception as e:
            return CCDAParseResult(False, "UNKNOWN", errors=[f"File read error: {str(e)}"])

    def parse_string(self, xml_string: str) -> CCDAParseResult:
        """Parse a CCDA XML string."""
        self._warnings = []
        self._errors = []

        try:
            # Register ALL namespaces before parsing - critical for xsi:type attributes
            ET.register_namespace("xsi",  "http://www.w3.org/2001/XMLSchema-instance")
            ET.register_namespace("cda",  "urn:hl7-org:v3")
            ET.register_namespace("sdtc", "urn:hl7-org:sdtc")
            for prefix, uri in NS.items():
                ET.register_namespace(prefix, uri)

            xml_string = xml_string.strip()

            # Parse XML
            root = ET.fromstring(xml_string)
            self._root = root

            # Detect namespace from root tag
            if root.tag.startswith("{"):
                self._ns = root.tag.split("}")[0].lstrip("{")

            # Validate this is a ClinicalDocument
            local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
            if local != "ClinicalDocument":
                return CCDAParseResult(
                    False, "UNKNOWN",
                    errors=[f"Root element must be ClinicalDocument, found: {local}"]
                )

            # Extract all top-level elements
            doc_meta    = self._parse_document_meta(root)
            patient     = self._parse_patient(root)
            author      = self._parse_author(root)
            custodian   = self._parse_custodian(root)
            sections    = self._parse_all_sections(root)

            return CCDAParseResult(
                success=True,
                document_type=doc_meta.get("document_type", "ClinicalDocument"),
                document_meta=doc_meta,
                patient=patient,
                author=author,
                custodian=custodian,
                sections=sections,
                warnings=self._warnings,
                errors=self._errors,
            )

        except ET.ParseError as e:
            return CCDAParseResult(False, "UNKNOWN", errors=[f"XML parse error: {str(e)}"])
        except Exception as e:
            return CCDAParseResult(False, "UNKNOWN", errors=[f"Unexpected error: {str(e)}"])

    # ── XML Helpers ────────────────────────────────────────────────────────────

    def _tag(self, name: str) -> str:
        """Return fully-qualified tag name with namespace."""
        return f"{{{self._ns}}}{name}"

    def _find(self, element, path: str) -> Optional[ET.Element]:
        """Find a child element using local tag names (namespace-aware)."""
        parts = path.split("/")
        current = element
        for part in parts:
            if current is None:
                return None
            # Handle attribute selectors like [@root='value']
            attr_match = re.match(r"(\w+)\[@(\w+)='([^']+)'\]", part)
            if attr_match:
                tag, attr, val = attr_match.groups()
                found = None
                for child in current:
                    ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if ctag == tag and child.get(attr) == val:
                        found = child
                        break
                current = found
            else:
                current = current.find(self._tag(part))
        return current

    def _findall(self, element, path: str) -> list:
        """Find all matching child elements."""
        parts = path.split("/")
        if len(parts) == 1:
            return element.findall(self._tag(parts[0]))

        # Multi-level: find parent then get all children
        parent_path = "/".join(parts[:-1])
        child_tag = parts[-1]
        parent = self._find(element, parent_path)
        if parent is None:
            return []
        return parent.findall(self._tag(child_tag))

    def _findall_direct(self, element, tag: str) -> list:
        """Find all direct children with the given tag."""
        return element.findall(self._tag(tag))

    def _attr(self, element, attr: str, default: str = "") -> str:
        """Get element attribute safely."""
        if element is None:
            return default
        return element.get(attr, default)

    def _text(self, element, path: str = None, default: str = "") -> str:
        """Get text content of an element or child."""
        if path:
            el = self._find(element, path)
        else:
            el = element
        if el is None:
            return default
        return (el.text or "").strip() or default

    def _parse_ts(self, value: str) -> Optional[str]:
        """Parse HL7 timestamp to ISO 8601."""
        if not value:
            return None
        value = value.strip().split("+")[0].split("-")[0] if len(value) > 8 else value.strip()
        formats = [
            ("%Y%m%d%H%M%S", 14),
            ("%Y%m%d%H%M", 12),
            ("%Y%m%d", 8),
        ]
        for fmt, length in formats:
            if len(value) >= length:
                try:
                    return datetime.strptime(value[:length], fmt).isoformat()
                except ValueError:
                    continue
        return value

    def _get_ts(self, element, path: str = None) -> Optional[str]:
        """Get and parse a timestamp element value attribute."""
        el = self._find(element, path) if path else element
        if el is None:
            return None
        return self._parse_ts(el.get("value", ""))

    def _extract_code(self, element) -> dict:
        """Extract a code element into {code, codeSystem, displayName, originalText}."""
        if element is None:
            return {}
        result = {
            "code":        element.get("code", ""),
            "code_system": element.get("codeSystem", ""),
            "code_system_name": element.get("codeSystemName", ""),
            "display":     element.get("displayName", ""),
        }
        # Try originalText if no displayName
        if not result["display"]:
            orig = self._find(element, "originalText")
            if orig is not None:
                result["display"] = (orig.text or "").strip()
        return result

    def _extract_name(self, name_el) -> dict:
        """Extract a CDA name element."""
        if name_el is None:
            return {}
        given_parts = [g.text or "" for g in name_el.findall(self._tag("given"))]
        family_el = self._find(name_el, "family")
        prefix_el = self._find(name_el, "prefix")
        suffix_el = self._find(name_el, "suffix")

        family = (family_el.text or "").strip() if family_el is not None else ""
        given  = " ".join(p.strip() for p in given_parts if p.strip())
        prefix = (prefix_el.text or "").strip() if prefix_el is not None else ""
        suffix = (suffix_el.text or "").strip() if suffix_el is not None else ""

        full = f"{prefix} {given} {family} {suffix}".strip()
        full = re.sub(r"\s+", " ", full)

        return {"full": full, "family": family, "given": given, "prefix": prefix, "suffix": suffix}

    def _extract_address(self, addr_el) -> dict:
        """Extract a CDA address (addr) element."""
        if addr_el is None:
            return {}

        def get_text(tag):
            el = self._find(addr_el, tag)
            return (el.text or "").strip() if el is not None else ""

        street_lines = [
            (el.text or "").strip()
            for el in addr_el.findall(self._tag("streetAddressLine"))
        ]

        return {
            "use":         addr_el.get("use", ""),
            "street":      street_lines,
            "city":        get_text("city"),
            "state":       get_text("state"),
            "postal_code": get_text("postalCode"),
            "country":     get_text("country"),
        }

    def _extract_telecom(self, elements: list) -> list:
        """Extract a list of telecom elements."""
        result = []
        for t in elements:
            value = t.get("value", "")
            use   = t.get("use", "")
            system = "phone" if value.startswith("tel:") else \
                     "email" if value.startswith("mailto:") else \
                     "fax"   if use in ("WP", "HP") and "fax" in use.lower() else "other"
            clean_value = re.sub(r"^(tel:|mailto:)", "", value)
            result.append({"system": system, "value": clean_value, "use": use})
        return result

    def _extract_effective_time(self, element) -> dict:
        """Extract effectiveTime - handles single value, low/high, and center."""
        et = self._find(element, "effectiveTime")
        if et is None:
            return {}

        # Single point in time
        if et.get("value"):
            return {"datetime": self._parse_ts(et.get("value", ""))}

        # Interval (low/high)
        low  = self._find(et, "low")
        high = self._find(et, "high")
        center = self._find(et, "center")

        result = {}
        if low  is not None: result["start"] = self._parse_ts(low.get("value", ""))
        if high is not None: result["end"]   = self._parse_ts(high.get("value", ""))
        if center is not None: result["datetime"] = self._parse_ts(center.get("value", ""))

        return result

    def _extract_value(self, element) -> dict:
        """Extract a value element (handles PQ, CD, ST, INT, REAL, TS types)."""
        value_el = None
        for child in element:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "value":
                value_el = child
                break

        if value_el is None:
            return {}

        # xsi:type can appear as "{http://www.w3.org/2001/XMLSchema-instance}type"
        # or as plain "type" attribute depending on parser behavior
        xsi_type = (
            value_el.get("{http://www.w3.org/2001/XMLSchema-instance}type")
            or value_el.get("xsi:type")
            or value_el.get("type")
            or ""
        )

        val_type = xsi_type.split(":")[-1] if ":" in xsi_type else xsi_type

        if val_type == "PQ":
            return {
                "type":    "quantity",
                "value":   value_el.get("value", ""),
                "unit":    value_el.get("unit", ""),
                "display": f"{value_el.get('value', '')} {value_el.get('unit', '')}".strip(),
            }
        elif val_type == "CD":
            return {"type": "coded", **self._extract_code(value_el)}
        elif val_type == "ST":
            return {"type": "string", "value": (value_el.text or "").strip(), "display": (value_el.text or "").strip()}
        elif val_type in ("INT", "REAL"):
            return {"type": val_type.lower(), "value": value_el.get("value", ""), "display": value_el.get("value", "")}
        elif val_type == "TS":
            return {"type": "timestamp", "value": self._parse_ts(value_el.get("value", ""))}
        elif val_type == "IVL_PQ":
            low  = self._find(value_el, "low")
            high = self._find(value_el, "high")
            return {
                "type": "range",
                "low":  f"{low.get('value', '')} {low.get('unit', '')}".strip() if low is not None else "",
                "high": f"{high.get('value', '')} {high.get('unit', '')}".strip() if high is not None else "",
            }
        else:
            raw = value_el.get("value") or (value_el.text or "").strip()
            return {"type": "unknown", "value": raw, "display": raw}

    def _get_section_narrative(self, section_el) -> str:
        """Extract the human-readable narrative text from a section."""
        text_el = self._find(section_el, "text")
        if text_el is None:
            return ""
        # Collect all text content recursively
        return " ".join(text_el.itertext()).strip()

    # ── Document-level Parsers ─────────────────────────────────────────────────

    def _parse_document_meta(self, root) -> dict:
        """Parse document-level metadata: ID, type, dates, title."""
        doc_id_el    = self._find(root, "id")
        code_el      = self._find(root, "code")
        title_el     = self._find(root, "title")
        effective_el = self._find(root, "effectiveTime")
        conf_el      = self._find(root, "confidentialityCode")
        lang_el      = self._find(root, "languageCode")

        code = self._extract_code(code_el)
        doc_type_code = code.get("code", "")
        doc_type_name = DOCUMENT_TYPES.get(doc_type_code, code.get("display", "ClinicalDocument"))

        # Template IDs at document level
        template_ids = [
            el.get("root", "") for el in root.findall(self._tag("templateId"))
        ]

        return {
            "document_id":    self._attr(doc_id_el, "root"),
            "document_type":  doc_type_name,
            "loinc_code":     doc_type_code,
            "title":          (title_el.text or "").strip() if title_el is not None else "",
            "effective_date": self._parse_ts(self._attr(effective_el, "value")) if effective_el is not None else None,
            "confidentiality": self._attr(conf_el, "code"),
            "language":       self._attr(lang_el, "code"),
            "template_ids":   template_ids,
            "set_id":         self._attr(self._find(root, "setId"), "root"),
            "version":        self._attr(self._find(root, "versionNumber"), "value"),
        }

    def _parse_patient(self, root) -> dict:
        """Parse the recordTarget/patientRole/patient block."""
        patient_role = self._find(root, "recordTarget/patientRole")
        if patient_role is None:
            self._warnings.append("No recordTarget/patientRole found")
            return {}

        patient_el = self._find(patient_role, "patient")

        # Identifiers (MRN, SSN, etc.)
        ids = []
        for id_el in patient_role.findall(self._tag("id")):
            ids.append({
                "root":      id_el.get("root", ""),
                "extension": id_el.get("extension", ""),
                "assigningAuthority": id_el.get("assigningAuthorityName", ""),
            })

        # Name
        name_el = self._find(patient_el, "name") if patient_el is not None else None
        name = self._extract_name(name_el)

        # Address
        addr_el = self._find(patient_role, "addr")
        address = self._extract_address(addr_el)

        # Telecom
        telecom_els = patient_role.findall(self._tag("telecom"))
        telecom = self._extract_telecom(telecom_els)

        if patient_el is None:
            return {"identifiers": ids, "name": name, "address": address, "telecom": telecom}

        # Demographics from patient element
        gender_el = self._find(patient_el, "administrativeGenderCode")
        dob_el    = self._find(patient_el, "birthTime")
        race_el   = self._find(patient_el, "raceCode")
        ethnicity_el = self._find(patient_el, "ethnicGroupCode")
        marital_el = self._find(patient_el, "maritalStatusCode")
        lang_el   = self._find(patient_el, "languageCommunication/languageCode")

        # Guardian
        guardian_el = self._find(patient_el, "guardian")
        guardian = {}
        if guardian_el is not None:
            gname = self._find(guardian_el, "guardianPerson/name")
            guardian = {
                "name": self._extract_name(gname),
                "relationship": self._extract_code(self._find(guardian_el, "code")),
                "address": self._extract_address(self._find(guardian_el, "addr")),
                "telecom": self._extract_telecom(guardian_el.findall(self._tag("telecom"))),
            }

        return {
            "identifiers": ids,
            "mrn": next((i["extension"] for i in ids if i.get("extension")), ""),
            "name": name,
            "date_of_birth": self._parse_ts(self._attr(dob_el, "value")) if dob_el is not None else None,
            "gender": self._attr(gender_el, "displayName") or self._attr(gender_el, "code"),
            "race": self._attr(race_el, "displayName") or self._attr(race_el, "code"),
            "ethnicity": self._attr(ethnicity_el, "displayName") or self._attr(ethnicity_el, "code"),
            "marital_status": self._attr(marital_el, "displayName") or self._attr(marital_el, "code"),
            "language": self._attr(lang_el, "code") if lang_el is not None else "",
            "address": address,
            "telecom": telecom,
            "guardian": guardian,
        }

    def _parse_author(self, root) -> dict:
        """Parse the author block (clinician/system that created the document)."""
        author_el = self._find(root, "author")
        if author_el is None:
            return {}

        time_el = self._find(author_el, "time")
        assigned_el = self._find(author_el, "assignedAuthor")
        if assigned_el is None:
            return {}

        # Author could be a person or a device
        person_el = self._find(assigned_el, "assignedPerson")
        device_el = self._find(assigned_el, "assignedAuthoringDevice")

        author_id_el = self._find(assigned_el, "id")
        org_el = self._find(assigned_el, "representedOrganization")

        result = {
            "id":            self._attr(author_id_el, "extension") or self._attr(author_id_el, "root"),
            "authored_date": self._parse_ts(self._attr(time_el, "value")) if time_el is not None else None,
            "address": self._extract_address(self._find(assigned_el, "addr")),
            "telecom": self._extract_telecom(assigned_el.findall(self._tag("telecom"))),
        }

        if person_el is not None:
            name_el = self._find(person_el, "name")
            result["type"] = "person"
            result["name"] = self._extract_name(name_el)
        elif device_el is not None:
            result["type"] = "device"
            result["software_name"] = self._text(device_el, "softwareName")
            result["manufacturer"] = self._text(device_el, "manufacturerModelName")

        if org_el is not None:
            result["organization"] = {
                "id":   self._attr(self._find(org_el, "id"), "extension"),
                "name": self._text(org_el, "name"),
                "address": self._extract_address(self._find(org_el, "addr")),
                "telecom": self._extract_telecom(org_el.findall(self._tag("telecom"))),
            }

        return result

    def _parse_custodian(self, root) -> dict:
        """Parse the custodian block (organization responsible for the document)."""
        org_el = self._find(root, "custodian/assignedCustodian/representedCustodianOrganization")
        if org_el is None:
            return {}
        return {
            "id":   self._attr(self._find(org_el, "id"), "extension"),
            "name": self._text(org_el, "name"),
            "address": self._extract_address(self._find(org_el, "addr")),
            "telecom": self._extract_telecom(org_el.findall(self._tag("telecom"))),
        }

    # ── Section Router ─────────────────────────────────────────────────────────

    def _parse_all_sections(self, root) -> dict:
        """Find all sections in the document body and route each to the right parser."""
        sections = {}

        # Navigate to structuredBody
        body = self._find(root, "component/structuredBody")
        if body is None:
            # Try nonXMLBody
            nonxml = self._find(root, "component/nonXMLBody")
            if nonxml is not None:
                self._warnings.append("Document has nonXMLBody - no structured sections to parse")
            else:
                self._warnings.append("No structuredBody found")
            return sections

        # Iterate all section components
        for comp in body.findall(self._tag("component")):
            section_el = self._find(comp, "section")
            if section_el is None:
                continue

            # Identify section by templateId
            section_name = self._identify_section(section_el)

            # Also try LOINC code-based identification
            if not section_name:
                code_el = self._find(section_el, "code")
                section_name = self._identify_section_by_code(code_el)

            if not section_name:
                section_name = f"unknown_section_{len(sections)}"

            section_data = self._parse_section(section_el, section_name)
            sections[section_name] = section_data

        return sections

    def _identify_section(self, section_el) -> Optional[str]:
        """Identify section type from templateId elements."""
        for tid_el in section_el.findall(self._tag("templateId")):
            root_val = tid_el.get("root", "")
            if root_val in SECTION_TEMPLATES:
                return SECTION_TEMPLATES[root_val]
        return None

    def _identify_section_by_code(self, code_el) -> Optional[str]:
        """Identify section by LOINC code as fallback."""
        if code_el is None:
            return None
        loinc_map = {
            "48765-2": "allergies",
            "10160-0": "medications",
            "11450-4": "problems",
            "8716-3":  "vital_signs",
            "30954-2": "results",
            "47519-4": "procedures",
            "11369-6": "immunizations",
            "29762-2": "social_history",
            "10157-6": "family_history",
            "46240-8": "encounters",
            "18776-5": "plan_of_care",
            "47420-5": "functional_status",
            "48768-6": "payers",
            "46264-8": "medical_equipment",
        }
        code = code_el.get("code", "")
        return loinc_map.get(code)

    def _parse_section(self, section_el, section_name: str) -> dict:
        """Route a section to its specific parser."""
        parsers = {
            "allergies":           self._parse_allergies_section,
            "medications":         self._parse_medications_section,
            "problems":            self._parse_problems_section,
            "vital_signs":         self._parse_vitals_section,
            "results":             self._parse_results_section,
            "procedures":          self._parse_procedures_section,
            "immunizations":       self._parse_immunizations_section,
            "social_history":      self._parse_social_history_section,
            "family_history":      self._parse_family_history_section,
            "encounters":          self._parse_encounters_section,
            "plan_of_care":        self._parse_plan_of_care_section,
            "payers":              self._parse_payers_section,
            "functional_status":   self._parse_generic_section,
            "mental_status":       self._parse_generic_section,
            "medical_equipment":   self._parse_generic_section,
            "discharge_diagnosis": self._parse_generic_section,
            "chief_complaint":     self._parse_text_only_section,
            "reason_for_visit":    self._parse_text_only_section,
            "assessment":          self._parse_text_only_section,
            "discharge_instructions": self._parse_text_only_section,
            "advance_directives":  self._parse_generic_section,
            "nutrition":           self._parse_generic_section,
        }

        # Get section code and title
        code_el  = self._find(section_el, "code")
        title_el = self._find(section_el, "title")
        base = {
            "section_name": section_name,
            "title": (title_el.text or "").strip() if title_el is not None else section_name.replace("_", " ").title(),
            "code": self._extract_code(code_el),
        }

        parser_fn = parsers.get(section_name, self._parse_generic_section)
        parsed = parser_fn(section_el)
        base.update(parsed)
        return base

    # ── Section-specific Parsers ───────────────────────────────────────────────

    def _parse_allergies_section(self, section_el) -> dict:
        """Parse allergies and intolerances section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            # Act > entryRelationship > observation pattern
            act = self._find(entry, "act")
            if act is None:
                continue

            # Get the allergy observation
            obs = self._find(act, "entryRelationship/observation")
            if obs is None:
                continue

            # Allergen substance
            participant = self._find(obs, "participant/participantRole/playingEntity")
            allergen_code = self._extract_code(self._find(participant, "code")) if participant is not None else {}
            allergen_name = allergen_code.get("display", "")
            if not allergen_name and participant is not None:
                name_el = self._find(participant, "name")
                allergen_name = (name_el.text or "").strip() if name_el is not None else ""

            # Allergy type (drug, food, environment)
            allergy_type = self._extract_code(self._find(obs, "code"))

            # Status
            status_obs = None
            for er in obs.findall(self._tag("entryRelationship")):
                type_code = er.get("typeCode", "")
                inner_obs = self._find(er, "observation")
                if inner_obs is not None:
                    template_ids = [t.get("root", "") for t in inner_obs.findall(self._tag("templateId"))]
                    if "2.16.840.1.113883.10.20.22.4.28" in template_ids:
                        status_obs = inner_obs
                        break

            status = ""
            if status_obs is not None:
                status_val = self._find(status_obs, "value")
                status = self._attr(status_val, "displayName") or self._attr(status_val, "code")

            # Severity
            severity = ""
            for er in obs.findall(self._tag("entryRelationship")):
                inner_obs = self._find(er, "observation")
                if inner_obs is not None:
                    tids = [t.get("root", "") for t in inner_obs.findall(self._tag("templateId"))]
                    if "2.16.840.1.113883.10.20.22.4.8" in tids:
                        sev_val = self._find(inner_obs, "value")
                        severity = self._attr(sev_val, "displayName") or self._attr(sev_val, "code")
                        break

            # Reactions
            reactions = []
            for er in obs.findall(self._tag("entryRelationship")):
                inner_obs = self._find(er, "observation")
                if inner_obs is not None:
                    tids = [t.get("root", "") for t in inner_obs.findall(self._tag("templateId"))]
                    if "2.16.840.1.113883.10.20.22.4.9" in tids:
                        rxn_code = self._extract_code(self._find(inner_obs, "value"))
                        if rxn_code.get("display"):
                            reactions.append(rxn_code["display"])

            effective = self._extract_effective_time(act)

            entries.append({
                "allergen": allergen_name,
                "allergen_code": allergen_code,
                "allergy_type": allergy_type.get("display", allergy_type.get("code", "")),
                "status": status,
                "severity": severity,
                "reactions": reactions,
                "onset": effective.get("start") or effective.get("datetime"),
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_medications_section(self, section_el) -> dict:
        """Parse medications section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            substance_admin = self._find(entry, "substanceAdministration")
            if substance_admin is None:
                continue

            # Drug name and code
            manuf_product = self._find(substance_admin, "consumable/manufacturedProduct")
            drug_code_el  = self._find(manuf_product, "manufacturedMaterial/code") if manuf_product is not None else None
            drug_code     = self._extract_code(drug_code_el)
            drug_name     = drug_code.get("display", "")

            # Translation code (e.g., RxNorm)
            if not drug_name and drug_code_el is not None:
                translation = self._find(drug_code_el, "translation")
                if translation is not None:
                    drug_name = self._attr(translation, "displayName")

            # Lot number / brand name
            brand_el = self._find(manuf_product, "manufacturedMaterial/name") if manuf_product is not None else None
            brand_name = (brand_el.text or "").strip() if brand_el is not None else ""

            # Dose quantity
            dose_el = self._find(substance_admin, "doseQuantity")
            dose = {}
            if dose_el is not None:
                dose = {
                    "value": dose_el.get("value", ""),
                    "unit":  dose_el.get("unit", ""),
                    "display": f"{dose_el.get('value', '')} {dose_el.get('unit', '')}".strip(),
                }

            # Route
            route_el = self._find(substance_admin, "routeCode")
            route = self._extract_code(route_el)

            # Frequency
            rate_el = self._find(substance_admin, "rateQuantity")
            rate = {}
            if rate_el is not None:
                rate = {"value": rate_el.get("value", ""), "unit": rate_el.get("unit", "")}

            # Timing (period) - iterate all effectiveTime elements and look for period child
            timing_period = None
            for et_el in substance_admin.findall(self._tag("effectiveTime")):
                period_el = self._find(et_el, "period")
                if period_el is not None:
                    timing_period = period_el
                    break

            frequency = {}
            if timing_period is not None:
                frequency = {
                    "value": timing_period.get("value", ""),
                    "unit":  timing_period.get("unit", ""),
                }

            # Duration (start/end)
            duration = {}
            for et_el in substance_admin.findall(self._tag("effectiveTime")):
                low  = self._find(et_el, "low")
                high = self._find(et_el, "high")
                if low is not None or high is not None:
                    duration = {
                        "start": self._parse_ts(low.get("value", ""))  if low  is not None else None,
                        "end":   self._parse_ts(high.get("value", "")) if high is not None else None,
                    }
                    break

            # Status
            status_el = self._find(substance_admin, "statusCode")
            status = self._attr(status_el, "code")

            # Instructions / sig
            instructions = ""
            for er in substance_admin.findall(self._tag("entryRelationship")):
                act = self._find(er, "act")
                if act is not None:
                    tids = [t.get("root", "") for t in act.findall(self._tag("templateId"))]
                    if "2.16.840.1.113883.10.20.22.4.20" in tids:
                        text_el = self._find(act, "text")
                        if text_el is not None:
                            instructions = (text_el.text or "").strip()
                        break

            # Prescriber
            prescriber = {}
            author_el = self._find(substance_admin, "author/assignedAuthor")
            if author_el is not None:
                person_el = self._find(author_el, "assignedPerson/name")
                prescriber = {"name": self._extract_name(person_el)}

            entries.append({
                "drug_name":    drug_name,
                "brand_name":   brand_name,
                "drug_code":    drug_code,
                "status":       status,
                "dose":         dose,
                "route":        route.get("display", route.get("code", "")),
                "frequency":    frequency,
                "duration":     duration,
                "instructions": instructions,
                "prescriber":   prescriber,
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_problems_section(self, section_el) -> dict:
        """Parse problems / diagnoses / conditions section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            act = self._find(entry, "act")
            if act is None:
                continue

            obs = self._find(act, "entryRelationship/observation")
            if obs is None:
                continue

            # Problem code
            value_el = self._find(obs, "value")
            problem_code = self._extract_code(value_el)

            # Status
            status_obs = None
            for er in obs.findall(self._tag("entryRelationship")):
                inner = self._find(er, "observation")
                if inner is not None:
                    tids = [t.get("root", "") for t in inner.findall(self._tag("templateId"))]
                    if "2.16.840.1.113883.10.20.22.4.6" in tids:
                        status_obs = inner
                        break

            status = ""
            if status_obs is not None:
                sv = self._find(status_obs, "value")
                status = self._attr(sv, "displayName") or self._attr(sv, "code")

            # Problem type
            problem_type = self._extract_code(self._find(obs, "code"))

            effective = self._extract_effective_time(obs)

            # Age at onset (if present)
            age_obs = None
            for er in obs.findall(self._tag("entryRelationship")):
                inner = self._find(er, "observation")
                if inner is not None:
                    tids = [t.get("root", "") for t in inner.findall(self._tag("templateId"))]
                    if "2.16.840.1.113883.10.20.22.4.31" in tids:
                        age_obs = inner
                        break
            age_at_onset = ""
            if age_obs is not None:
                age_val = self._find(age_obs, "value")
                if age_val is not None:
                    age_at_onset = f"{age_val.get('value', '')} {age_val.get('unit', '')}".strip()

            entries.append({
                "problem":      problem_code.get("display", ""),
                "problem_code": problem_code,
                "problem_type": problem_type.get("display", problem_type.get("code", "")),
                "status":       status,
                "onset":        effective.get("start") or effective.get("datetime"),
                "resolution":   effective.get("end"),
                "age_at_onset": age_at_onset,
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_vitals_section(self, section_el) -> dict:
        """Parse vital signs section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            organizer = self._find(entry, "organizer")
            if organizer is None:
                continue

            # Vital signs panel datetime
            panel_time = self._get_ts(organizer, "effectiveTime")

            # Each individual vital sign observation
            vitals_in_panel = []
            for comp in organizer.findall(self._tag("component")):
                obs = self._find(comp, "observation")
                if obs is None:
                    continue

                vital_code = self._extract_code(self._find(obs, "code"))
                value = self._extract_value(obs)
                obs_time = self._get_ts(obs, "effectiveTime")

                # Interpretation
                interp_el = self._find(obs, "interpretationCode")
                interpretation = self._attr(interp_el, "displayName") or self._attr(interp_el, "code")

                vitals_in_panel.append({
                    "vital":          vital_code.get("display", vital_code.get("code", "")),
                    "code":           vital_code,
                    "value":          value.get("value", ""),
                    "unit":           value.get("unit", ""),
                    "display":        value.get("display", ""),
                    "datetime":       obs_time or panel_time,
                    "interpretation": interpretation,
                })

            if vitals_in_panel:
                entries.append({
                    "panel_datetime": panel_time,
                    "vitals": vitals_in_panel,
                })

        # Also create a flat list of the most recent reading per vital type
        latest = {}
        for panel in entries:
            for v in panel.get("vitals", []):
                key = v.get("vital", "")
                if key and (key not in latest or v.get("datetime", "") > latest[key].get("datetime", "")):
                    latest[key] = v

        return {
            "entries": entries,
            "count": len(entries),
            "latest_readings": latest,
        }

    def _parse_results_section(self, section_el) -> dict:
        """Parse lab results section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            organizer = self._find(entry, "organizer")
            if organizer is None:
                continue

            # Panel/battery code
            panel_code = self._extract_code(self._find(organizer, "code"))
            panel_time = self._get_ts(organizer, "effectiveTime")
            panel_status_el = self._find(organizer, "statusCode")
            panel_status = self._attr(panel_status_el, "code")

            observations = []
            for comp in organizer.findall(self._tag("component")):
                obs = self._find(comp, "observation")
                if obs is None:
                    continue

                result_code = self._extract_code(self._find(obs, "code"))
                value = self._extract_value(obs)
                obs_time = self._get_ts(obs, "effectiveTime")

                status_el = self._find(obs, "statusCode")
                status = self._attr(status_el, "code")

                # Interpretation
                interp_el = self._find(obs, "interpretationCode")
                interpretation = self._attr(interp_el, "displayName") or self._attr(interp_el, "code")
                is_abnormal = interpretation in ("H", "HH", "L", "LL", "A", "AA", "HU", "LU")

                # Reference range
                ref_range = {}
                ref_el = self._find(obs, "referenceRange/observationRange")
                if ref_el is not None:
                    text_el = self._find(ref_el, "text")
                    rr_value = self._find(ref_el, "value")
                    if text_el is not None:
                        ref_range["text"] = (text_el.text or "").strip()
                    if rr_value is not None:
                        low_el  = self._find(rr_value, "low")
                        high_el = self._find(rr_value, "high")
                        if low_el is not None:
                            ref_range["low"]  = f"{low_el.get('value', '')} {low_el.get('unit', '')}".strip()
                        if high_el is not None:
                            ref_range["high"] = f"{high_el.get('value', '')} {high_el.get('unit', '')}".strip()

                observations.append({
                    "test":           result_code.get("display", result_code.get("code", "")),
                    "code":           result_code,
                    "value":          value.get("value", ""),
                    "unit":           value.get("unit", ""),
                    "display":        value.get("display", ""),
                    "status":         status,
                    "datetime":       obs_time or panel_time,
                    "interpretation": interpretation,
                    "is_abnormal":    is_abnormal,
                    "reference_range": ref_range,
                })

            entries.append({
                "panel":         panel_code.get("display", panel_code.get("code", "")),
                "panel_code":    panel_code,
                "panel_status":  panel_status,
                "panel_datetime": panel_time,
                "observations":  observations,
                "abnormal_count": sum(1 for o in observations if o.get("is_abnormal")),
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_procedures_section(self, section_el) -> dict:
        """Parse procedures section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            # Can be procedure, act, or observation
            proc_el = (self._find(entry, "procedure") or
                       self._find(entry, "act") or
                       self._find(entry, "observation"))
            if proc_el is None:
                continue

            proc_code = self._extract_code(self._find(proc_el, "code"))
            effective = self._extract_effective_time(proc_el)
            status_el = self._find(proc_el, "statusCode")
            status    = self._attr(status_el, "code")

            # Body site
            target_site = self._find(proc_el, "targetSiteCode")
            body_site = self._extract_code(target_site)

            # Performer
            performer = {}
            perf_el = self._find(proc_el, "performer/assignedEntity")
            if perf_el is not None:
                pname = self._find(perf_el, "assignedPerson/name")
                performer = {
                    "name": self._extract_name(pname),
                    "id": self._attr(self._find(perf_el, "id"), "extension"),
                }

            # Specimen (if lab procedure)
            specimen = {}
            spec_el = self._find(proc_el, "specimen/specimenRole/specimenPlayingEntity/code")
            if spec_el is not None:
                specimen = self._extract_code(spec_el)

            entries.append({
                "procedure":  proc_code.get("display", proc_code.get("code", "")),
                "code":       proc_code,
                "status":     status,
                "datetime":   effective.get("datetime") or effective.get("start"),
                "body_site":  body_site.get("display", body_site.get("code", "")),
                "performer":  performer,
                "specimen":   specimen,
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_immunizations_section(self, section_el) -> dict:
        """Parse immunizations section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            substance_admin = self._find(entry, "substanceAdministration")
            if substance_admin is None:
                continue

            # Vaccine code
            manuf_product = self._find(substance_admin, "consumable/manufacturedProduct")
            vaccine_code_el = self._find(manuf_product, "manufacturedMaterial/code") if manuf_product is not None else None
            vaccine_code = self._extract_code(vaccine_code_el)

            effective = self._extract_effective_time(substance_admin)
            status_el = self._find(substance_admin, "statusCode")
            status    = self._attr(status_el, "code")

            # Negation - "not given"
            not_given = substance_admin.get("negationInd", "false").lower() == "true"

            # Dose number / series
            dose_qty = self._find(substance_admin, "doseQuantity")
            dose = f"{dose_qty.get('value', '')} {dose_qty.get('unit', '')}".strip() if dose_qty is not None else ""

            # Reaction observation
            reaction = ""
            for er in substance_admin.findall(self._tag("entryRelationship")):
                obs = self._find(er, "observation")
                if obs is not None:
                    tids = [t.get("root", "") for t in obs.findall(self._tag("templateId"))]
                    if "2.16.840.1.113883.10.20.22.4.9" in tids:
                        rxn_val = self._find(obs, "value")
                        if rxn_val is not None:
                            reaction = self._attr(rxn_val, "displayName")
                        break

            entries.append({
                "vaccine":    vaccine_code.get("display", vaccine_code.get("code", "")),
                "code":       vaccine_code,
                "status":     status,
                "date":       effective.get("datetime") or effective.get("start"),
                "dose":       dose,
                "not_given":  not_given,
                "reaction":   reaction,
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_social_history_section(self, section_el) -> dict:
        """Parse social history section (smoking, alcohol, occupation, etc.)."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            obs = self._find(entry, "observation")
            if obs is None:
                continue

            social_code = self._extract_code(self._find(obs, "code"))
            value = self._extract_value(obs)
            effective = self._extract_effective_time(obs)

            entries.append({
                "category":  social_code.get("display", social_code.get("code", "")),
                "code":      social_code,
                "value":     value.get("display", value.get("value", "")),
                "start":     effective.get("start") or effective.get("datetime"),
                "end":       effective.get("end"),
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_family_history_section(self, section_el) -> dict:
        """Parse family history section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            organizer = self._find(entry, "organizer")
            if organizer is None:
                continue

            # Relationship
            subject_el = self._find(organizer, "subject/relatedSubject")
            relationship = self._extract_code(self._find(subject_el, "code")) if subject_el else {}

            # Subject name (if present)
            subject_name_el = self._find(subject_el, "subject/name") if subject_el else None
            subject_name = self._extract_name(subject_name_el)

            # Subject DOB / age
            subject_dob_el = self._find(subject_el, "subject/birthTime") if subject_el else None
            subject_dob = self._parse_ts(self._attr(subject_dob_el, "value")) if subject_dob_el is not None else None

            # Conditions
            conditions = []
            for comp in organizer.findall(self._tag("component")):
                obs = self._find(comp, "observation")
                if obs is None:
                    continue

                condition_code = self._extract_code(self._find(obs, "value"))
                effective = self._extract_effective_time(obs)

                # Death indicator
                deceased = False
                for er in obs.findall(self._tag("entryRelationship")):
                    inner = self._find(er, "observation")
                    if inner is not None:
                        tids = [t.get("root", "") for t in inner.findall(self._tag("templateId"))]
                        if "2.16.840.1.113883.10.20.22.4.47" in tids:
                            deceased = True
                            break

                conditions.append({
                    "condition":   condition_code.get("display", condition_code.get("code", "")),
                    "code":        condition_code,
                    "onset":       effective.get("start") or effective.get("datetime"),
                    "caused_death": deceased,
                })

            entries.append({
                "relationship":      relationship.get("display", relationship.get("code", "")),
                "relationship_code": relationship,
                "subject_name":      subject_name,
                "subject_dob":       subject_dob,
                "conditions":        conditions,
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_encounters_section(self, section_el) -> dict:
        """Parse encounters section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            encounter = self._find(entry, "encounter")
            if encounter is None:
                continue

            enc_code = self._extract_code(self._find(encounter, "code"))
            effective = self._extract_effective_time(encounter)
            id_el = self._find(encounter, "id")

            # Performer / provider
            performer = {}
            perf_el = self._find(encounter, "performer/assignedEntity")
            if perf_el is not None:
                pname = self._find(perf_el, "assignedPerson/name")
                org_name_el = self._find(perf_el, "representedOrganization/name")
                performer = {
                    "name": self._extract_name(pname),
                    "organization": (org_name_el.text or "").strip() if org_name_el is not None else "",
                }

            # Diagnoses associated with encounter
            diagnoses = []
            for er in encounter.findall(self._tag("entryRelationship")):
                act = self._find(er, "act")
                if act is not None:
                    obs = self._find(act, "entryRelationship/observation")
                    if obs is not None:
                        dx_code = self._extract_code(self._find(obs, "value"))
                        if dx_code.get("display") or dx_code.get("code"):
                            diagnoses.append(dx_code)

            # Location
            location = {}
            part_el = self._find(encounter, "participant/participantRole")
            if part_el is not None:
                loc_name_el = self._find(part_el, "playingEntity/name")
                location = {
                    "id":   self._attr(self._find(part_el, "id"), "extension"),
                    "name": (loc_name_el.text or "").strip() if loc_name_el is not None else "",
                    "address": self._extract_address(self._find(part_el, "addr")),
                }

            entries.append({
                "encounter_type":  enc_code.get("display", enc_code.get("code", "")),
                "code":            enc_code,
                "id":              self._attr(id_el, "extension") or self._attr(id_el, "root"),
                "start":           effective.get("start") or effective.get("datetime"),
                "end":             effective.get("end"),
                "performer":       performer,
                "location":        location,
                "diagnoses":       diagnoses,
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_plan_of_care_section(self, section_el) -> dict:
        """Parse plan of care / goals section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            # Can be observation, act, substanceAdministration, procedure, supply, encounter
            for elem_type in ("observation", "act", "substanceAdministration", "procedure", "supply"):
                plan_el = self._find(entry, elem_type)
                if plan_el is not None:
                    plan_code = self._extract_code(self._find(plan_el, "code"))
                    effective = self._extract_effective_time(plan_el)
                    mood = plan_el.get("moodCode", "")

                    entries.append({
                        "plan_item":  plan_code.get("display", plan_code.get("code", "")),
                        "code":       plan_code,
                        "type":       elem_type,
                        "mood":       mood,  # INT=intended, RQO=requested, GOL=goal
                        "scheduled":  effective.get("start") or effective.get("datetime"),
                    })
                    break

        return {"entries": entries, "count": len(entries)}

    def _parse_payers_section(self, section_el) -> dict:
        """Parse payers / insurance section."""
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            act = self._find(entry, "act")
            if act is None:
                continue

            effective = self._extract_effective_time(act)

            # Payer organization
            payer = {}
            payer_perf = self._find(act, "performer/assignedEntity")
            if payer_perf is not None:
                org_name_el = self._find(payer_perf, "representedOrganization/name")
                payer = {
                    "id":   self._attr(self._find(payer_perf, "id"), "extension"),
                    "name": (org_name_el.text or "").strip() if org_name_el is not None else "",
                    "telecom": self._extract_telecom(payer_perf.findall(self._tag("telecom"))),
                }

            # Beneficiary (patient)
            beneficiary = {}
            part_el = self._find(act, "participant[@typeCode='COV']/participantRole")
            if part_el is not None:
                id_el = self._find(part_el, "id")
                beneficiary = {
                    "member_id": self._attr(id_el, "extension"),
                    "relationship": self._attr(self._find(part_el, "code"), "displayName"),
                }

            # Guarantor
            guarantor = {}
            guar_el = self._find(act, "participant[@typeCode='HLD']/participantRole")
            if guar_el is not None:
                gname = self._find(guar_el, "playingEntity/name")
                guarantor = {"name": self._extract_name(gname)}

            # Policy number
            policy_act = self._find(act, "entryRelationship/act")
            policy_number = ""
            if policy_act is not None:
                pol_id = self._find(policy_act, "id")
                policy_number = self._attr(pol_id, "extension") or self._attr(pol_id, "root")

            entries.append({
                "payer":          payer,
                "policy_number":  policy_number,
                "beneficiary":    beneficiary,
                "guarantor":      guarantor,
                "coverage_start": effective.get("start") or effective.get("datetime"),
                "coverage_end":   effective.get("end"),
            })

        return {"entries": entries, "count": len(entries)}

    def _parse_text_only_section(self, section_el) -> dict:
        """Parse sections that only have narrative text (chief complaint, assessment, etc.)."""
        narrative = self._get_section_narrative(section_el)
        return {"narrative": narrative}

    def _parse_generic_section(self, section_el) -> dict:
        """Generic fallback parser - extracts entries and narrative."""
        narrative = self._get_section_narrative(section_el)
        entries = []

        for entry in section_el.findall(self._tag("entry")):
            for elem_type in ("observation", "act", "procedure", "substanceAdministration", "supply"):
                el = self._find(entry, elem_type)
                if el is not None:
                    code = self._extract_code(self._find(el, "code"))
                    value = self._extract_value(el)
                    effective = self._extract_effective_time(el)
                    entries.append({
                        "type":    elem_type,
                        "code":    code,
                        "value":   value,
                        "time":    effective,
                    })
                    break

        return {"narrative": narrative, "entries": entries, "count": len(entries)}


# =============================================================================
# DEMO / TEST WITH SYNTHETIC CCDA DOCUMENT
# =============================================================================

SAMPLE_CCDA = """<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

  <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>
  <templateId root="2.16.840.1.113883.10.20.22.1.2" extension="2015-08-01"/>
  <id root="2.16.840.1.113883.19.5.99999.1" extension="TT988"/>
  <code code="34133-9" codeSystem="2.16.840.1.113883.6.1"
        codeSystemName="LOINC" displayName="Summarization of Episode Note"/>
  <title>Continuity of Care Document</title>
  <effectiveTime value="20240315143022-0500"/>
  <confidentialityCode code="N" codeSystem="2.16.840.1.113883.5.25"/>
  <languageCode code="en-US"/>
  <setId root="2.16.840.1.113883.19.5.99999.19"/>
  <versionNumber value="1"/>

  <recordTarget>
    <patientRole>
      <id root="2.16.840.1.113883.19.5.99999.2" extension="998991701"/>
      <id root="2.16.840.1.113883.4.1" extension="111-00-2330"/>
      <addr use="HP">
        <streetAddressLine>1357 Amber Drive</streetAddressLine>
        <city>Beaverton</city>
        <state>OR</state>
        <postalCode>97867</postalCode>
        <country>US</country>
      </addr>
      <telecom use="HP" value="tel:+15035559999"/>
      <telecom use="HP" value="mailto:amy.shaw@email.com"/>
      <patient>
        <name use="L">
          <given>Amy</given>
          <given>V</given>
          <family>Shaw</family>
        </name>
        <administrativeGenderCode code="F" codeSystem="2.16.840.1.113883.5.1" displayName="Female"/>
        <birthTime value="19880329"/>
        <maritalStatusCode code="M" codeSystem="2.16.840.1.113883.5.2" displayName="Married"/>
        <raceCode code="2106-3" codeSystem="2.16.840.1.113883.6.238" displayName="White"/>
        <ethnicGroupCode code="2186-5" codeSystem="2.16.840.1.113883.6.238" displayName="Not Hispanic or Latino"/>
        <languageCommunication>
          <languageCode code="en"/>
        </languageCommunication>
      </patient>
    </patientRole>
  </recordTarget>

  <author>
    <time value="20240315143022-0500"/>
    <assignedAuthor>
      <id extension="99999999" root="2.16.840.1.113883.4.6"/>
      <addr use="WP">
        <streetAddressLine>1002 Healthcare Dr.</streetAddressLine>
        <city>Portland</city>
        <state>OR</state>
        <postalCode>97005</postalCode>
      </addr>
      <telecom use="WP" value="tel:+15035554444"/>
      <assignedPerson>
        <name>
          <prefix>Dr.</prefix>
          <given>Henry</given>
          <family>Seven</family>
        </name>
      </assignedPerson>
      <representedOrganization>
        <id root="2.16.840.1.113883.19.5.9999.1393"/>
        <name>Community Health Clinic</name>
        <telecom use="WP" value="tel:+15035554444"/>
        <addr use="WP">
          <streetAddressLine>1002 Healthcare Dr.</streetAddressLine>
          <city>Portland</city><state>OR</state><postalCode>97005</postalCode>
        </addr>
      </representedOrganization>
    </assignedAuthor>
  </author>

  <custodian>
    <assignedCustodian>
      <representedCustodianOrganization>
        <id extension="99999999" root="2.16.840.1.113883.4.6"/>
        <name>Community Health and Hospitals</name>
        <telecom use="WP" value="tel:+15035554444"/>
        <addr use="WP">
          <streetAddressLine>1002 Healthcare Dr.</streetAddressLine>
          <city>Portland</city><state>OR</state><postalCode>97005</postalCode>
        </addr>
      </representedCustodianOrganization>
    </assignedCustodian>
  </custodian>

  <component>
    <structuredBody>

      <!-- ALLERGIES -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.6.1" extension="2015-08-01"/>
          <code code="48765-2" codeSystem="2.16.840.1.113883.6.1" displayName="Allergies and Adverse Reactions"/>
          <title>ALLERGIES AND ADVERSE REACTIONS</title>
          <text>Penicillin - severe rash, hives. NKDA otherwise.</text>
          <entry typeCode="DRIV">
            <act classCode="ACT" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.30" extension="2015-08-01"/>
              <id root="36e3e930-7b14-11db-9fe1-0800200c9a66"/>
              <code code="CONC" codeSystem="2.16.840.1.113883.5.6"/>
              <statusCode code="active"/>
              <effectiveTime><low value="20070501"/></effectiveTime>
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.7" extension="2014-06-09"/>
                  <id root="4adc1020-7b14-11db-9fe1-0800200c9a66"/>
                  <code code="ASSERTION" codeSystem="2.16.840.1.113883.5.4"/>
                  <statusCode code="completed"/>
                  <effectiveTime><low value="20070501"/></effectiveTime>
                  <value xsi:type="CD" code="416098002"
                         codeSystem="2.16.840.1.113883.6.96"
                         displayName="Drug allergy (disorder)"/>
                  <participant typeCode="CSM">
                    <participantRole classCode="MANU">
                      <playingEntity classCode="MMAT">
                        <code code="7980" codeSystem="2.16.840.1.113883.6.88"
                              codeSystemName="RxNorm" displayName="Penicillin"/>
                      </playingEntity>
                    </participantRole>
                  </participant>
                  <entryRelationship typeCode="SUBJ" inversionInd="true">
                    <observation classCode="OBS" moodCode="EVN">
                      <templateId root="2.16.840.1.113883.10.20.22.4.8" extension="2014-06-09"/>
                      <code code="SEV" codeSystem="2.16.840.1.113883.5.4" displayName="Severity Observation"/>
                      <statusCode code="completed"/>
                      <value xsi:type="CD" code="24484000"
                             codeSystem="2.16.840.1.113883.6.96" displayName="Severe"/>
                    </observation>
                  </entryRelationship>
                  <entryRelationship typeCode="MFST" inversionInd="true">
                    <observation classCode="OBS" moodCode="EVN">
                      <templateId root="2.16.840.1.113883.10.20.22.4.9" extension="2014-06-09"/>
                      <code code="ASSERTION" codeSystem="2.16.840.1.113883.5.4"/>
                      <statusCode code="completed"/>
                      <value xsi:type="CD" code="247472004"
                             codeSystem="2.16.840.1.113883.6.96" displayName="Hives"/>
                    </observation>
                  </entryRelationship>
                </observation>
              </entryRelationship>
            </act>
          </entry>
        </section>
      </component>

      <!-- MEDICATIONS -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.1.1" extension="2014-06-09"/>
          <code code="10160-0" codeSystem="2.16.840.1.113883.6.1" displayName="History of Medication use"/>
          <title>MEDICATIONS</title>
          <text>Atorvastatin 40mg daily. Lisinopril 10mg daily.</text>
          <entry typeCode="DRIV">
            <substanceAdministration classCode="SBADM" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.16" extension="2014-06-09"/>
              <id root="cdbd5b0e-6ccd-11db-9fe1-0800200c9a66"/>
              <statusCode code="active"/>
              <effectiveTime xsi:type="IVL_TS">
                <low value="20230101"/>
                <high nullFlavor="UNK"/>
              </effectiveTime>
              <routeCode code="C38288" codeSystem="2.16.840.1.113883.3.26.1.1"
                         displayName="Oral Route of Administration"/>
              <doseQuantity value="40" unit="mg"/>
              <consumable>
                <manufacturedProduct classCode="MANU">
                  <templateId root="2.16.840.1.113883.10.20.22.4.23" extension="2014-06-09"/>
                  <manufacturedMaterial>
                    <code code="617312" codeSystem="2.16.840.1.113883.6.88"
                          codeSystemName="RxNorm" displayName="Atorvastatin 40 MG Oral Tablet"/>
                  </manufacturedMaterial>
                </manufacturedProduct>
              </consumable>
            </substanceAdministration>
          </entry>
          <entry typeCode="DRIV">
            <substanceAdministration classCode="SBADM" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.16" extension="2014-06-09"/>
              <id root="cdbd5b0e-6ccd-11db-9fe1-0800200c9a67"/>
              <statusCode code="active"/>
              <effectiveTime xsi:type="IVL_TS">
                <low value="20220601"/>
                <high nullFlavor="UNK"/>
              </effectiveTime>
              <routeCode code="C38288" codeSystem="2.16.840.1.113883.3.26.1.1"
                         displayName="Oral Route of Administration"/>
              <doseQuantity value="10" unit="mg"/>
              <consumable>
                <manufacturedProduct classCode="MANU">
                  <templateId root="2.16.840.1.113883.10.20.22.4.23" extension="2014-06-09"/>
                  <manufacturedMaterial>
                    <code code="314076" codeSystem="2.16.840.1.113883.6.88"
                          codeSystemName="RxNorm" displayName="Lisinopril 10 MG Oral Tablet"/>
                  </manufacturedMaterial>
                </manufacturedProduct>
              </consumable>
            </substanceAdministration>
          </entry>
        </section>
      </component>

      <!-- PROBLEMS -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.5.1" extension="2015-08-01"/>
          <code code="11450-4" codeSystem="2.16.840.1.113883.6.1" displayName="Problem list"/>
          <title>PROBLEMS</title>
          <text>Essential Hypertension. Hyperlipidemia.</text>
          <entry typeCode="DRIV">
            <act classCode="ACT" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.3" extension="2015-08-01"/>
              <id root="ec8a6ff8-ed4b-4f7e-82c3-e98e58b45de7"/>
              <code code="CONC" codeSystem="2.16.840.1.113883.5.6"/>
              <statusCode code="active"/>
              <effectiveTime><low value="20110801"/></effectiveTime>
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.4" extension="2015-08-01"/>
                  <id root="ab1791b0-5c71-11db-b0de-0800200c9a66"/>
                  <code code="55607006" codeSystem="2.16.840.1.113883.6.96" displayName="Problem"/>
                  <statusCode code="completed"/>
                  <effectiveTime><low value="20110801"/></effectiveTime>
                  <value xsi:type="CD" code="59621000"
                         codeSystem="2.16.840.1.113883.6.96"
                         displayName="Essential hypertension"/>
                  <entryRelationship typeCode="REFR">
                    <observation classCode="OBS" moodCode="EVN">
                      <templateId root="2.16.840.1.113883.10.20.22.4.6" extension="2014-06-09"/>
                      <code code="33999-4" codeSystem="2.16.840.1.113883.6.1" displayName="Status"/>
                      <statusCode code="completed"/>
                      <value xsi:type="CD" code="55561003"
                             codeSystem="2.16.840.1.113883.6.96" displayName="Active"/>
                    </observation>
                  </entryRelationship>
                </observation>
              </entryRelationship>
            </act>
          </entry>
          <entry typeCode="DRIV">
            <act classCode="ACT" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.3" extension="2015-08-01"/>
              <id root="ec8a6ff8-ed4b-4f7e-82c3-e98e58b45de8"/>
              <code code="CONC" codeSystem="2.16.840.1.113883.5.6"/>
              <statusCode code="active"/>
              <effectiveTime><low value="20130301"/></effectiveTime>
              <entryRelationship typeCode="SUBJ">
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.4" extension="2015-08-01"/>
                  <code code="55607006" codeSystem="2.16.840.1.113883.6.96" displayName="Problem"/>
                  <statusCode code="completed"/>
                  <effectiveTime><low value="20130301"/></effectiveTime>
                  <value xsi:type="CD" code="55822004"
                         codeSystem="2.16.840.1.113883.6.96" displayName="Hyperlipidemia"/>
                </observation>
              </entryRelationship>
            </act>
          </entry>
        </section>
      </component>

      <!-- VITAL SIGNS -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.4.1" extension="2015-08-01"/>
          <code code="8716-3" codeSystem="2.16.840.1.113883.6.1" displayName="Vital Signs"/>
          <title>VITAL SIGNS</title>
          <text>BP 132/86, HR 76, Temp 98.5F, Wt 185lbs, BMI 27.3</text>
          <entry typeCode="DRIV">
            <organizer classCode="CLUSTER" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.26" extension="2015-08-01"/>
              <id root="c6f88321-67ad-11db-bd13-0800200c9a66"/>
              <code code="74728-7" codeSystem="2.16.840.1.113883.6.1" displayName="Vital signs panel"/>
              <statusCode code="completed"/>
              <effectiveTime value="20240315"/>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.27" extension="2014-06-09"/>
                  <code code="8480-6" codeSystem="2.16.840.1.113883.6.1" displayName="Systolic blood pressure"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240315"/>
                  <value xsi:type="PQ" value="132" unit="mm[Hg]"/>
                  <interpretationCode code="N" codeSystem="2.16.840.1.113883.5.83"/>
                </observation>
              </component>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.27" extension="2014-06-09"/>
                  <code code="8462-4" codeSystem="2.16.840.1.113883.6.1" displayName="Diastolic blood pressure"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240315"/>
                  <value xsi:type="PQ" value="86" unit="mm[Hg]"/>
                  <interpretationCode code="N" codeSystem="2.16.840.1.113883.5.83"/>
                </observation>
              </component>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.27" extension="2014-06-09"/>
                  <code code="8867-4" codeSystem="2.16.840.1.113883.6.1" displayName="Heart rate"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240315"/>
                  <value xsi:type="PQ" value="76" unit="/min"/>
                </observation>
              </component>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.27" extension="2014-06-09"/>
                  <code code="8310-5" codeSystem="2.16.840.1.113883.6.1" displayName="Body temperature"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240315"/>
                  <value xsi:type="PQ" value="98.5" unit="[degF]"/>
                </observation>
              </component>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.27" extension="2014-06-09"/>
                  <code code="29463-7" codeSystem="2.16.840.1.113883.6.1" displayName="Body weight"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240315"/>
                  <value xsi:type="PQ" value="185" unit="[lb_av]"/>
                </observation>
              </component>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.27" extension="2014-06-09"/>
                  <code code="39156-5" codeSystem="2.16.840.1.113883.6.1" displayName="Body mass index (BMI)"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240315"/>
                  <value xsi:type="PQ" value="27.3" unit="kg/m2"/>
                </observation>
              </component>
            </organizer>
          </entry>
        </section>
      </component>

      <!-- LAB RESULTS -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.3.1" extension="2015-08-01"/>
          <code code="30954-2" codeSystem="2.16.840.1.113883.6.1" displayName="Relevant diagnostic tests"/>
          <title>RESULTS</title>
          <text>Lipid Panel: Total Chol 210 (High), LDL 138 (High), HDL 52, TG 100.</text>
          <entry typeCode="DRIV">
            <organizer classCode="BATTERY" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.1" extension="2015-08-01"/>
              <id root="7d5a02b0-67a5-11db-bd13-0800200c9a66"/>
              <code code="57698-3" codeSystem="2.16.840.1.113883.6.1" displayName="Lipid panel with direct LDL"/>
              <statusCode code="completed"/>
              <effectiveTime value="20240310"/>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.2" extension="2015-08-01"/>
                  <code code="2093-3" codeSystem="2.16.840.1.113883.6.1" displayName="Cholesterol [Mass/volume] in Serum"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240310"/>
                  <value xsi:type="PQ" value="210" unit="mg/dL"/>
                  <interpretationCode code="H" codeSystem="2.16.840.1.113883.5.83" displayName="High"/>
                  <referenceRange>
                    <observationRange>
                      <text>100-199</text>
                      <value xsi:type="IVL_PQ">
                        <low value="100" unit="mg/dL"/>
                        <high value="199" unit="mg/dL"/>
                      </value>
                    </observationRange>
                  </referenceRange>
                </observation>
              </component>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.2" extension="2015-08-01"/>
                  <code code="13457-7" codeSystem="2.16.840.1.113883.6.1" displayName="Cholesterol in LDL"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240310"/>
                  <value xsi:type="PQ" value="138" unit="mg/dL"/>
                  <interpretationCode code="H" codeSystem="2.16.840.1.113883.5.83" displayName="High"/>
                  <referenceRange>
                    <observationRange>
                      <text>0-99</text>
                      <value xsi:type="IVL_PQ">
                        <low value="0" unit="mg/dL"/>
                        <high value="99" unit="mg/dL"/>
                      </value>
                    </observationRange>
                  </referenceRange>
                </observation>
              </component>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.2" extension="2015-08-01"/>
                  <code code="2085-9" codeSystem="2.16.840.1.113883.6.1" displayName="Cholesterol in HDL"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240310"/>
                  <value xsi:type="PQ" value="52" unit="mg/dL"/>
                  <interpretationCode code="N" codeSystem="2.16.840.1.113883.5.83" displayName="Normal"/>
                </observation>
              </component>
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <templateId root="2.16.840.1.113883.10.20.22.4.2" extension="2015-08-01"/>
                  <code code="2571-8" codeSystem="2.16.840.1.113883.6.1" displayName="Triglycerides"/>
                  <statusCode code="completed"/>
                  <effectiveTime value="20240310"/>
                  <value xsi:type="PQ" value="100" unit="mg/dL"/>
                  <interpretationCode code="N" codeSystem="2.16.840.1.113883.5.83" displayName="Normal"/>
                </observation>
              </component>
            </organizer>
          </entry>
        </section>
      </component>

      <!-- SOCIAL HISTORY -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.17" extension="2015-08-01"/>
          <code code="29762-2" codeSystem="2.16.840.1.113883.6.1" displayName="Social History"/>
          <title>SOCIAL HISTORY</title>
          <text>Never smoker. Occasional alcohol use.</text>
          <entry typeCode="DRIV">
            <observation classCode="OBS" moodCode="EVN">
              <templateId root="2.16.840.1.113883.10.20.22.4.78" extension="2014-06-09"/>
              <id root="9b56c25d-9104-45f3-9f2d-19de6b9b7e33"/>
              <code code="72166-2" codeSystem="2.16.840.1.113883.6.1" displayName="Tobacco smoking status NHIS"/>
              <statusCode code="completed"/>
              <effectiveTime>
                <low value="20030101"/>
                <high nullFlavor="UNK"/>
              </effectiveTime>
              <value xsi:type="CD" code="266919005"
                     codeSystem="2.16.840.1.113883.6.96"
                     displayName="Never smoked tobacco"/>
            </observation>
          </entry>
        </section>
      </component>

      <!-- IMMUNIZATIONS -->
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.2.1" extension="2015-08-01"/>
          <code code="11369-6" codeSystem="2.16.840.1.113883.6.1" displayName="History of Immunization"/>
          <title>IMMUNIZATIONS</title>
          <text>Influenza 2023.</text>
          <entry typeCode="DRIV">
            <substanceAdministration classCode="SBADM" moodCode="EVN" negationInd="false">
              <templateId root="2.16.840.1.113883.10.20.22.4.52" extension="2015-08-01"/>
              <id root="e6f1da9f-ff89-4f43-a8ee-85685a8b56aa"/>
              <statusCode code="completed"/>
              <effectiveTime value="20231015"/>
              <consumable>
                <manufacturedProduct classCode="MANU">
                  <templateId root="2.16.840.1.113883.10.20.22.4.54" extension="2014-06-09"/>
                  <manufacturedMaterial>
                    <code code="140" codeSystem="2.16.840.1.113883.12.292"
                          codeSystemName="CVX"
                          displayName="Influenza, seasonal, injectable, preservative free"/>
                  </manufacturedMaterial>
                </manufacturedProduct>
              </consumable>
            </substanceAdministration>
          </entry>
        </section>
      </component>

    </structuredBody>
  </component>
</ClinicalDocument>"""


def demo():
    parser = CCDAParser()
    result = parser.parse_string(SAMPLE_CCDA)

    SEP = "=" * 70

    print(SEP)
    print("CCDA PARSER - DEMO")
    print(SEP)

    print(f"\n  Success:        {result.success}")
    print(f"  Document Type:  {result.document_type}")
    print(f"  Sections Found: {result.section_names()}")
    if result.warnings:
        print(f"  Warnings:       {result.warnings}")

    # Document Meta
    meta = result.document_meta
    print(f"\n{'─'*70}")
    print("DOCUMENT METADATA")
    print(f"{'─'*70}")
    print(f"  ID:             {meta.get('document_id')}")
    print(f"  Title:          {meta.get('title')}")
    print(f"  Effective Date: {meta.get('effective_date')}")
    print(f"  Confidentiality:{meta.get('confidentiality')}")
    print(f"  Language:       {meta.get('language')}")
    print(f"  Version:        {meta.get('version')}")

    # Patient
    pt = result.patient
    print(f"\n{'─'*70}")
    print("PATIENT DEMOGRAPHICS")
    print(f"{'─'*70}")
    print(f"  Name:           {pt.get('name', {}).get('full')}")
    print(f"  DOB:            {pt.get('date_of_birth')}")
    print(f"  Gender:         {pt.get('gender')}")
    print(f"  Race:           {pt.get('race')}")
    print(f"  Ethnicity:      {pt.get('ethnicity')}")
    print(f"  Marital Status: {pt.get('marital_status')}")
    print(f"  MRN:            {pt.get('mrn')}")
    addr = pt.get('address', {})
    print(f"  Address:        {', '.join(addr.get('street', []))} {addr.get('city')}, {addr.get('state')} {addr.get('postal_code')}")
    for t in pt.get('telecom', []):
        print(f"  {t.get('system', 'contact').title()}: {t.get('value')}")

    # Author
    auth = result.author
    print(f"\n{'─'*70}")
    print("AUTHOR")
    print(f"{'─'*70}")
    print(f"  Name:           {auth.get('name', {}).get('full')}")
    print(f"  Authored:       {auth.get('authored_date')}")
    print(f"  Organization:   {auth.get('organization', {}).get('name')}")

    # Custodian
    cust = result.custodian
    print(f"\n{'─'*70}")
    print("CUSTODIAN")
    print(f"{'─'*70}")
    print(f"  Organization:   {cust.get('name')}")

    # Allergies
    print(f"\n{'─'*70}")
    print("ALLERGIES")
    print(f"{'─'*70}")
    for al in result.get_all_allergies():
        print(f"  • {al.get('allergen'):<25} Type: {al.get('allergy_type'):<20} "
              f"Severity: {al.get('severity'):<10} Reactions: {al.get('reactions')}")

    # Medications
    print(f"\n{'─'*70}")
    print("MEDICATIONS")
    print(f"{'─'*70}")
    for med in result.get_all_medications():
        dose = med.get('dose', {})
        print(f"  • {med.get('drug_name'):<40} {dose.get('display', ''):<15} "
              f"Route: {med.get('route'):<10} Status: {med.get('status')}")

    # Problems
    print(f"\n{'─'*70}")
    print("PROBLEMS / DIAGNOSES")
    print(f"{'─'*70}")
    for prob in result.get_all_problems():
        code = prob.get('problem_code', {})
        print(f"  • {prob.get('problem'):<40} Code: {code.get('code'):<12} "
              f"Status: {prob.get('status'):<10} Onset: {prob.get('onset')}")

    # Vital Signs (latest readings)
    print(f"\n{'─'*70}")
    print("VITAL SIGNS (Latest Readings)")
    print(f"{'─'*70}")
    latest = result.get_section("vital_signs", ) or {}
    for name, v in (latest.get("latest_readings", {}) if isinstance(latest, dict) else {}).items():
        print(f"  • {name:<35} {v.get('display', ''):<15}")

    # Lab Results
    print(f"\n{'─'*70}")
    print("LAB RESULTS")
    print(f"{'─'*70}")
    for panel in result.get_all_results():
        print(f"  Panel: {panel.get('panel')} ({panel.get('panel_datetime')})")
        for obs in panel.get('observations', []):
            flag = " ⚠ HIGH" if obs.get('is_abnormal') else ""
            ref = obs.get('reference_range', {})
            ref_str = f"Ref: {ref.get('text', ref.get('low','') + '-' + ref.get('high',''))}" if ref else ""
            print(f"    - {obs.get('test'):<35} {obs.get('display'):<15} {ref_str}{flag}")

    # Social History
    print(f"\n{'─'*70}")
    print("SOCIAL HISTORY")
    print(f"{'─'*70}")
    social = result.get_section("social_history") or {}
    for entry in social.get("entries", []):
        print(f"  • {entry.get('category'):<30} {entry.get('value')}")

    # Immunizations
    print(f"\n{'─'*70}")
    print("IMMUNIZATIONS")
    print(f"{'─'*70}")
    immuno = result.get_section("immunizations") or {}
    for imm in immuno.get("entries", []):
        print(f"  • {imm.get('vaccine'):<45} Date: {imm.get('date')}")

    print(f"\n{SEP}")
    print("Full JSON output available via result.to_json()")
    print(SEP)


if __name__ == "__main__":
    demo()
