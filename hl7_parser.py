"""
╔══════════════════════════════════════════════════════════════════════╗
║              HL7 v2.x MESSAGE PARSER  —  Standalone                 ║
║                                                                      ║
║  Supports  : HL7 v2.3 / v2.4 / v2.5 / v2.6 / v2.7                  ║
║  Messages  : ADT, ORU, ORM, SIU, MDM, ACK                           ║
║  Segments  : MSH PID PV1 OBR OBX DG1 AL1 IN1 NTE EVN ORC RXA        ║
║  Requires  : Python 3.9+  —  zero external dependencies              ║
╚══════════════════════════════════════════════════════════════════════╝

QUICK START:
    from hl7_parser import HL7Parser

    parser = HL7Parser()
    result = parser.parse(raw_hl7_string)

    print(result.success)          # True / False
    print(result.message_type)     # e.g. "HL7_ADT_A01"
    print(result.summary)          # dict of key clinical fields
    print(result.to_json())        # full JSON output

Run as script for built-in demo:
    python hl7_parser.py
"""

import json
import re
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# RESULT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HL7ParseResult:
    success: bool
    message_type: str
    raw_data: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps({
            "success":      self.success,
            "message_type": self.message_type,
            "summary":      self.summary,
            "raw_data":     self.raw_data,
            "errors":       self.errors,
            "warnings":     self.warnings,
        }, indent=indent, default=str)

    def get_patient(self) -> dict:
        return self.summary.get("patient", {})

    def get_visit(self) -> dict:
        return self.summary.get("visit", {})

    def get_lab_results(self) -> dict:
        return self.summary.get("lab_results", {})

    def get_diagnoses(self) -> list:
        return self.summary.get("diagnoses", [])

    def get_allergies(self) -> list:
        return self.summary.get("allergies", [])

    def get_insurance(self) -> dict:
        return self.summary.get("insurance", {})


# ─────────────────────────────────────────────────────────────────────────────
# FIELD NAME MAPS  (segment → field index → human name)
# ─────────────────────────────────────────────────────────────────────────────

FIELD_NAMES = {
    "MSH": {
        1: "field_separator", 2: "encoding_characters", 3: "sending_application",
        4: "sending_facility", 5: "receiving_application", 6: "receiving_facility",
        7: "datetime", 8: "security", 9: "message_type", 10: "message_control_id",
        11: "processing_id", 12: "version_id",
    },
    "PID": {
        1: "set_id", 2: "patient_id", 3: "patient_identifier_list",
        5: "patient_name", 6: "mothers_maiden_name", 7: "date_of_birth",
        8: "sex", 10: "race", 11: "address", 13: "phone_home",
        14: "phone_business", 15: "primary_language", 16: "marital_status",
        17: "religion", 18: "account_number", 19: "ssn",
        22: "ethnic_group", 29: "patient_death_date",
    },
    "PV1": {
        2: "patient_class", 3: "assigned_location", 4: "admission_type",
        7: "attending_doctor", 8: "referring_doctor", 10: "hospital_service",
        17: "admitting_doctor", 18: "patient_type", 19: "visit_number",
        44: "admit_datetime", 45: "discharge_datetime",
    },
    "OBR": {
        1: "set_id", 2: "placer_order_number", 3: "filler_order_number",
        4: "universal_service_id", 6: "requested_datetime",
        7: "observation_datetime", 13: "relevant_clinical_info",
        14: "specimen_received_datetime", 16: "ordering_provider",
        22: "results_report_datetime", 24: "diagnostic_serv_sect_id",
        25: "result_status",
    },
    "OBX": {
        1: "set_id", 2: "value_type", 3: "observation_identifier",
        4: "observation_sub_id", 5: "observation_value", 6: "units",
        7: "reference_range", 8: "abnormal_flags",
        11: "observation_result_status", 14: "date_time_of_observation",
    },
    "DG1": {
        1: "set_id", 2: "diagnosis_coding_method", 3: "diagnosis_code",
        4: "diagnosis_description", 5: "diagnosis_datetime", 6: "diagnosis_type",
    },
    "AL1": {
        1: "set_id", 2: "allergen_type_code", 3: "allergen_code",
        4: "allergy_severity_code", 5: "allergy_reaction_code",
    },
    "IN1": {
        1: "set_id", 2: "insurance_plan_id", 3: "insurance_company_id",
        4: "insurance_company_name", 15: "plan_type",
        16: "name_of_insured", 36: "policy_number",
    },
    "ORC": {
        1: "order_control", 2: "placer_order_number", 3: "filler_order_number",
        5: "order_status", 9: "datetime_of_transaction", 12: "ordering_provider",
    },
    "RXA": {
        1: "give_sub_id_counter", 2: "administration_sub_id_counter",
        3: "date_time_start_of_administration", 4: "date_time_end_of_administration",
        5: "administered_code", 6: "administered_amount", 7: "administered_units",
        9: "administration_notes", 11: "administered_at_location",
        15: "substance_lot_number", 17: "substance_manufacturer_name",
    },
    "NTE": {1: "set_id", 2: "source_of_comment", 3: "comment"},
    "EVN": {1: "event_type_code", 2: "recorded_datetime", 3: "datetime_planned_event"},
}

# Abnormal flag severity mapping
ABNORMAL_FLAGS = {
    "H":  ("abnormal", "High"),
    "HH": ("critical",  "Critical High"),
    "L":  ("abnormal", "Low"),
    "LL": ("critical",  "Critical Low"),
    "A":  ("abnormal", "Abnormal"),
    "AA": ("critical",  "Critical Abnormal"),
    "HU": ("abnormal", "Significantly High"),
    "LU": ("abnormal", "Significantly Low"),
    ">":  ("abnormal", "Above absolute high"),
    "<":  ("abnormal", "Below absolute low"),
}

# Patient class codes
PATIENT_CLASS = {
    "I": "Inpatient",
    "O": "Outpatient",
    "E": "Emergency",
    "R": "Recurring Patient",
    "P": "Preadmit",
    "B": "Obstetrics",
    "C": "Commercial Account",
    "N": "Not Applicable",
    "U": "Unknown",
}


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PARSER
# ─────────────────────────────────────────────────────────────────────────────

class HL7Parser:
    """
    Parses HL7 v2.x pipe-delimited messages.

    Usage:
        parser = HL7Parser()
        result = parser.parse(message_string)
    """

    def __init__(self):
        self.FIELD_SEP     = "|"
        self.COMPONENT_SEP = "^"
        self.REPEAT_SEP    = "~"
        self.ESCAPE_CHAR   = "\\"
        self.SUBCOMP_SEP   = "&"
        self._segments: dict = {}
        self._segment_list: list = []

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self, message: str) -> HL7ParseResult:
        """
        Parse a raw HL7 v2.x message string.

        Args:
            message:  Raw HL7 pipe-delimited message (CRLF or LF line endings)

        Returns:
            HL7ParseResult
        """
        errors   = []
        warnings = []

        try:
            # Normalise line endings — HL7 uses CR (\r) as segment terminator
            message = message.strip().replace("\r\n", "\r").replace("\n", "\r")
            lines   = [l for l in message.split("\r") if l.strip()]

            if not lines:
                return HL7ParseResult(False, "HL7_UNKNOWN", errors=["Empty message"])

            if not re.match(r"^MSH.", lines[0]):
                return HL7ParseResult(
                    False, "HL7_UNKNOWN",
                    errors=["Message must start with MSH segment"]
                )

            # Detect delimiters from MSH
            msh_raw = lines[0]
            if len(msh_raw) > 3:
                self.FIELD_SEP = msh_raw[3]
            if len(msh_raw) > 7:
                enc = msh_raw[4:8]
                if len(enc) >= 1: self.COMPONENT_SEP = enc[0]
                if len(enc) >= 2: self.REPEAT_SEP    = enc[1]
                if len(enc) >= 3: self.ESCAPE_CHAR   = enc[2]
                if len(enc) >= 4: self.SUBCOMP_SEP   = enc[3]

            # Parse all segments
            self._segments     = {}
            self._segment_list = []

            for line in lines:
                seg = self._parse_segment(line)
                if seg:
                    name = seg["segment_name"]
                    self._segment_list.append(seg)

                    if name in self._segments:
                        existing = self._segments[name]
                        if isinstance(existing, list):
                            existing.append(seg)
                        else:
                            self._segments[name] = [existing, seg]
                    else:
                        self._segments[name] = seg

            # Determine message type from MSH-9
            msg_type_field = self._get_field("MSH", 9)
            msg_type  = self._comp(msg_type_field, 0)
            msg_event = self._comp(msg_type_field, 1)
            msg_struct = self._comp(msg_type_field, 2)

            label = f"HL7_{msg_type}"
            if msg_event:
                label += f"_{msg_event}"

            raw_data = {
                "message_type": msg_type,
                "event":        msg_event,
                "structure":    msg_struct,
                "segments":     self._segments,
                "segment_order": [s["segment_name"] for s in self._segment_list],
            }

            summary = self._build_summary(msg_type, warnings)

            return HL7ParseResult(
                success=True,
                message_type=label,
                raw_data=raw_data,
                summary=summary,
                errors=errors,
                warnings=warnings,
            )

        except Exception as e:
            return HL7ParseResult(False, "HL7_UNKNOWN", errors=[f"Parse error: {str(e)}"])

    def get_segment(self, name: str) -> Optional[dict]:
        """Return the first occurrence of a named segment."""
        seg = self._segments.get(name)
        if isinstance(seg, list):
            return seg[0]
        return seg

    def get_all_segments(self, name: str) -> list:
        """Return all occurrences of a repeating segment (OBX, DG1, AL1…)."""
        seg = self._segments.get(name, [])
        if isinstance(seg, dict):
            return [seg]
        return seg

    # ── Parsing helpers ───────────────────────────────────────────────────────

    def _parse_segment(self, line: str) -> Optional[dict]:
        """Parse one HL7 segment line into a structured dict."""
        line = line.strip()
        if not line:
            return None

        parts    = line.split(self.FIELD_SEP)
        seg_name = parts[0].strip()

        if len(seg_name) != 3 or not seg_name.isalnum():
            return None

        fields     = {}
        name_map   = FIELD_NAMES.get(seg_name, {})
        start      = 2 if seg_name == "MSH" else 1

        for i, value in enumerate(parts[start:], start=start):
            fields[i] = value
            if i in name_map:
                fields[name_map[i]] = value

        return {"segment_name": seg_name, "raw": line, "fields": fields}

    def _get_field(self, seg_name: str, index: int) -> str:
        """Safely fetch a field value from a named segment."""
        seg = self.get_segment(seg_name)
        if not seg:
            return ""
        return seg.get("fields", {}).get(index, "")

    def _comp(self, value: str, idx: int) -> str:
        """Extract component at index from a ^ delimited field."""
        if not value:
            return ""
        parts = value.split(self.COMPONENT_SEP)
        return parts[idx].strip() if idx < len(parts) else ""

    def _repeat(self, value: str) -> list:
        """Split a repeating field on ~ delimiter."""
        if not value:
            return []
        return [v.strip() for v in value.split(self.REPEAT_SEP) if v.strip()]

    def _ts(self, value: str) -> Optional[str]:
        """Parse an HL7 timestamp string to ISO 8601."""
        if not value:
            return None
        value = value.strip().split("+")[0]
        for fmt, length in [("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)]:
            if len(value) >= length:
                try:
                    return datetime.strptime(value[:length], fmt).isoformat()
                except ValueError:
                    continue
        return value

    # ── Clinical summary builder ──────────────────────────────────────────────

    def _build_summary(self, msg_type: str, warnings: list) -> dict:
        """Build a structured clinical summary from all parsed segments."""
        summary = {}

        # ── Message header ────────────────────────────────────────────────────
        summary["message"] = {
            "type":              msg_type,
            "event":             self._comp(self._get_field("MSH", 9), 1),
            "control_id":        self._get_field("MSH", 10),
            "datetime":          self._ts(self._get_field("MSH", 7)),
            "sending_application": self._get_field("MSH", 3),
            "sending_facility":  self._get_field("MSH", 4),
            "receiving_application": self._get_field("MSH", 5),
            "receiving_facility": self._get_field("MSH", 6),
            "version":           self._get_field("MSH", 12),
            "processing_id":     self._get_field("MSH", 11),
        }

        # ── Patient identity (PID) ─────────────────────────────────────────────
        if "PID" in self._segments:
            name_f  = self._get_field("PID", 5)
            addr_f  = self._get_field("PID", 11)
            pid3    = self._get_field("PID", 3)

            # Support multiple identifiers in PID-3 (~ repeated)
            identifiers = []
            for rep in self._repeat(pid3) or [pid3]:
                id_val  = self._comp(rep, 0)
                id_type = self._comp(rep, 4) or self._comp(rep, 3)
                if id_val:
                    identifiers.append({"value": id_val, "type": id_type})

            mrn = next((i["value"] for i in identifiers if i["type"] in ("MR", "PI", "")), "")
            if not mrn and identifiers:
                mrn = identifiers[0]["value"]

            summary["patient"] = {
                "mrn":           mrn,
                "identifiers":   identifiers,
                "full_name":     f"{self._comp(name_f,1)} {self._comp(name_f,2)} {self._comp(name_f,0)}".strip(),
                "family_name":   self._comp(name_f, 0),
                "given_name":    self._comp(name_f, 1),
                "middle_name":   self._comp(name_f, 2),
                "name_suffix":   self._comp(name_f, 4),
                "date_of_birth": self._ts(self._get_field("PID", 7)),
                "sex":           self._get_field("PID", 8),
                "race":          self._get_field("PID", 10),
                "ethnicity":     self._get_field("PID", 22),
                "marital_status":self._get_field("PID", 16),
                "language":      self._get_field("PID", 15),
                "ssn":           self._get_field("PID", 19),
                "account_number":self._comp(self._get_field("PID", 18), 0),
                "address": {
                    "street":  self._comp(addr_f, 0),
                    "city":    self._comp(addr_f, 2),
                    "state":   self._comp(addr_f, 3),
                    "zip":     self._comp(addr_f, 4),
                    "country": self._comp(addr_f, 5),
                },
                "phone_home":     self._get_field("PID", 13),
                "phone_business": self._get_field("PID", 14),
                "death_date":     self._ts(self._get_field("PID", 29)),
            }

        # ── Visit / Encounter (PV1) ───────────────────────────────────────────
        if "PV1" in self._segments:
            loc_f        = self._get_field("PV1", 3)
            attending_f  = self._get_field("PV1", 7)
            referring_f  = self._get_field("PV1", 8)
            admitting_f  = self._get_field("PV1", 17)
            pat_class    = self._get_field("PV1", 2)

            summary["visit"] = {
                "patient_class":       pat_class,
                "patient_class_name":  PATIENT_CLASS.get(pat_class, pat_class),
                "location": {
                    "point_of_care": self._comp(loc_f, 0),
                    "room":          self._comp(loc_f, 1),
                    "bed":           self._comp(loc_f, 2),
                    "facility":      self._comp(loc_f, 3),
                    "status":        self._comp(loc_f, 4),
                    "type":          self._comp(loc_f, 5),
                },
                "admission_type":    self._get_field("PV1", 4),
                "hospital_service":  self._get_field("PV1", 10),
                "patient_type":      self._get_field("PV1", 18),
                "visit_number":      self._comp(self._get_field("PV1", 19), 0),
                "admit_datetime":    self._ts(self._get_field("PV1", 44)),
                "discharge_datetime":self._ts(self._get_field("PV1", 45)),
                "attending_doctor":  self._parse_xcn(attending_f),
                "referring_doctor":  self._parse_xcn(referring_f),
                "admitting_doctor":  self._parse_xcn(admitting_f),
            }

        # ── Lab order / results (OBR + OBX) ──────────────────────────────────
        if "OBR" in self._segments or "OBX" in self._segments:
            obr    = self.get_segment("OBR") or {}
            obr_f  = obr.get("fields", {})
            svc_f  = obr_f.get(4, "")

            obx_list = self.get_all_segments("OBX")
            observations = [self._parse_obx(obx) for obx in obx_list]

            summary["lab_results"] = {
                "placer_order_number": obr_f.get(2, ""),
                "filler_order_number": obr_f.get(3, ""),
                "service": {
                    "code":   self._comp(svc_f, 0),
                    "text":   self._comp(svc_f, 1),
                    "system": self._comp(svc_f, 2),
                },
                "ordering_provider":    self._parse_xcn(obr_f.get(16, "")),
                "observation_datetime": self._ts(obr_f.get(7, "")),
                "result_status":        obr_f.get(25, ""),
                "diagnostic_service":   obr_f.get(24, ""),
                "observations":         observations,
                "total_count":          len(observations),
                "abnormal_count":       sum(1 for o in observations if o.get("is_abnormal")),
                "critical_count":       sum(1 for o in observations if o.get("severity") == "critical"),
            }

            # Add notes from NTE segments
            nte_list = self.get_all_segments("NTE")
            if nte_list:
                notes = []
                for nte in nte_list:
                    nte_f = nte.get("fields", {})
                    comment = nte_f.get(3, "")
                    if comment:
                        notes.append(comment)
                if notes:
                    summary["lab_results"]["notes"] = notes

        # ── Diagnoses (DG1) ───────────────────────────────────────────────────
        dg1_list = self.get_all_segments("DG1")
        if dg1_list:
            diagnoses = []
            for dg1 in dg1_list:
                dg1_f   = dg1.get("fields", {})
                code_f  = dg1_f.get(3, "")
                diagnoses.append({
                    "code":          self._comp(code_f, 0),
                    "description":   self._comp(code_f, 1),
                    "coding_system": self._comp(code_f, 2),
                    "diagnosis_type":dg1_f.get(6, ""),
                    "datetime":      self._ts(dg1_f.get(5, "")),
                    "set_id":        dg1_f.get(1, ""),
                })
            summary["diagnoses"] = diagnoses

        # ── Allergies (AL1) ───────────────────────────────────────────────────
        al1_list = self.get_all_segments("AL1")
        if al1_list:
            allergies = []
            for al1 in al1_list:
                al1_f    = al1.get("fields", {})
                allergen = al1_f.get(3, "")
                reactions = [r.strip() for r in al1_f.get(5, "").split(self.REPEAT_SEP) if r.strip()]
                allergies.append({
                    "allergen_type": al1_f.get(2, ""),
                    "allergen_code": self._comp(allergen, 0),
                    "allergen_name": self._comp(allergen, 1) or self._comp(allergen, 0),
                    "severity":      al1_f.get(4, ""),
                    "reactions":     reactions,
                })
            summary["allergies"] = allergies

        # ── Insurance (IN1) ───────────────────────────────────────────────────
        if "IN1" in self._segments:
            in1_f = self.get_segment("IN1").get("fields", {})
            summary["insurance"] = {
                "plan_id":        self._comp(in1_f.get(2, ""), 0),
                "company_id":     self._comp(in1_f.get(3, ""), 0),
                "company_name":   in1_f.get(4, ""),
                "plan_type":      in1_f.get(15, ""),
                "insured_name":   in1_f.get(16, ""),
                "policy_number":  in1_f.get(36, ""),
            }

        # ── Medication (RXA) ─────────────────────────────────────────────────
        rxa_list = self.get_all_segments("RXA")
        if rxa_list:
            medications = []
            for rxa in rxa_list:
                rxa_f = rxa.get("fields", {})
                drug_f = rxa_f.get(5, "")
                medications.append({
                    "drug_code":     self._comp(drug_f, 0),
                    "drug_name":     self._comp(drug_f, 1),
                    "amount":        rxa_f.get(6, ""),
                    "units":         self._comp(rxa_f.get(7, ""), 1),
                    "administered_at": self._ts(rxa_f.get(3, "")),
                    "lot_number":    rxa_f.get(15, ""),
                    "manufacturer":  self._comp(rxa_f.get(17, ""), 1),
                })
            summary["medications"] = medications

        return summary

    def _parse_xcn(self, value: str) -> dict:
        """Parse an XCN (Extended Composite ID and Name for Persons) field."""
        if not value:
            return {}
        return {
            "id":          self._comp(value, 0),
            "family_name": self._comp(value, 1),
            "given_name":  self._comp(value, 2),
            "middle_name": self._comp(value, 3),
            "suffix":      self._comp(value, 4),
            "prefix":      self._comp(value, 5),
            "full_name":   f"{self._comp(value,5)} {self._comp(value,2)} {self._comp(value,3)} {self._comp(value,1)}".strip(),
        }

    def _parse_obx(self, obx: dict) -> dict:
        """Parse a single OBX segment into a clean observation dict."""
        f        = obx.get("fields", {})
        obs_id   = f.get(3, "")
        flag     = f.get(8, "").strip()
        flag_info = ABNORMAL_FLAGS.get(flag, ("normal", "Normal"))

        return {
            "set_id":     f.get(1, ""),
            "value_type": f.get(2, ""),
            "identifier": {
                "code":   self._comp(obs_id, 0),
                "text":   self._comp(obs_id, 1),
                "system": self._comp(obs_id, 2),
            },
            "sub_id":         f.get(4, ""),
            "value":          f.get(5, ""),
            "units":          self._comp(f.get(6, ""), 0),
            "reference_range":f.get(7, ""),
            "abnormal_flag":  flag,
            "is_abnormal":    flag in ABNORMAL_FLAGS,
            "severity":       flag_info[0],
            "flag_description": flag_info[1],
            "status":         f.get(11, ""),
            "datetime":       self._ts(f.get(14, "")),
        }


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE MESSAGES
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_ADT = (
    "MSH|^~\\&|EPIC|MEMORIAL_HOSPITAL|LABSYS|RECEIVING|20240315143022||ADT^A01^ADT_A01|MSG001234|P|2.5\r"
    "EVN|A01|20240315143022\r"
    "PID|1||MR123456^^^MEMORIAL^MR~SSN111223333^^^USSSA^SS||SMITH^JOHN^WILLIAM^JR^MR||19850322|M||2106-3|"
    "123 MAIN ST^APT 4B^CHICAGO^IL^60601^USA||312-555-7890|312-555-1234|ENG|M|CHR|ACC789012|||N\r"
    "PV1|1|I|ICU^101^A^MEMORIAL||||12345^JOHNSON^EMILY^M^^^DR|||CARD|||||ADM|"
    "20240315143000||||||||||||||||||||||||20240315143000\r"
    "DG1|1|ICD10|I21.9^Acute myocardial infarction, unspecified^ICD10CM||20240315143000|A\r"
    "DG1|2|ICD10|I10^Essential hypertension^ICD10CM||20240315000000|A\r"
    "DG1|3|ICD10|E78.5^Hyperlipidemia, unspecified^ICD10CM||20200601|C\r"
    "AL1|1|DA|7980^Penicillin^RxNorm|SV|RASH~HIVES~ANAPHYLAXIS\r"
    "AL1|2|FA|1160580^Peanuts^SCT|MO|URTICARIA\r"
    "IN1|1|BCBS001^BlueCross BlueShield PPO^HL70072|INS001^BCBS Illinois|"
    "BlueCross BlueShield of Illinois|||||||||||PPO|SMITH^JOHN|||||||||||||||POL987654321\r"
)

SAMPLE_ORU = (
    "MSH|^~\\&|LABSYS|MEMORIAL_LAB|EHR|MEMORIAL|20240315160000||ORU^R01^ORU_R01|LAB5678|P|2.5\r"
    "PID|1||MR123456^^^MEMORIAL^MR||SMITH^JOHN^WILLIAM||19850322|M\r"
    "OBR|1|ORD001|FILL001|CBC^Complete Blood Count^L|||20240315155000|||||||"
    "20240315155500|BLOOD^Venous Blood|12345^JOHNSON^EMILY^^^DR||||||20240315160000|||F\r"
    "OBX|1|NM|718-7^Hemoglobin^LN||8.2|g/dL|13.5-17.5|L|||F|||20240315160000\r"
    "OBX|2|NM|4544-3^Hematocrit^LN||25.1|%|41-53|LL|||F|||20240315160000\r"
    "OBX|3|NM|6690-2^WBC [#/volume] in Blood^LN||11.5|10*3/uL|4.5-11.0|H|||F|||20240315160000\r"
    "OBX|4|NM|777-3^Platelets [#/volume] in Blood^LN||185|10*3/uL|150-400||||F|||20240315160000\r"
    "OBX|5|NM|26515-7^Platelets^LN||2.2|%|0.5-1.5|H|||F|||20240315160000\r"
    "NTE|1||CRITICAL VALUES CALLED TO DR. JOHNSON AT 16:05 BY LAB TECH MILLER\r"
    "NTE|2||SPECIMEN QUALITY: ACCEPTABLE\r"
)


# ─────────────────────────────────────────────────────────────────────────────
# DEMO
# ─────────────────────────────────────────────────────────────────────────────

def demo():
    parser = HL7Parser()
    sep    = "=" * 68

    print(sep)
    print("  HL7 v2.x PARSER  —  DEMO")
    print(sep)

    # ── TEST 1: ADT^A01 Patient Admission ─────────────────────────────────────
    print("\n" + "─" * 68)
    print("  TEST 1 — ADT^A01  (Patient Admission)")
    print("─" * 68)

    r = parser.parse(SAMPLE_ADT)
    print(f"  Success       : {r.success}")
    print(f"  Message Type  : {r.message_type}")

    pt = r.get_patient()
    print(f"\n  PATIENT")
    print(f"    Name        : {pt.get('full_name')}")
    print(f"    MRN         : {pt.get('mrn')}")
    print(f"    DOB         : {pt.get('date_of_birth')}")
    print(f"    Sex         : {pt.get('sex')}")
    print(f"    Race        : {pt.get('race')}")
    print(f"    Phone (Home): {pt.get('phone_home')}")
    addr = pt.get('address', {})
    print(f"    Address     : {addr.get('street')}, {addr.get('city')}, {addr.get('state')} {addr.get('zip')}")

    v = r.get_visit()
    print(f"\n  VISIT")
    print(f"    Class       : {v.get('patient_class')} — {v.get('patient_class_name')}")
    loc = v.get('location', {})
    print(f"    Location    : {loc.get('point_of_care')} / Room {loc.get('room')} / Bed {loc.get('bed')}")
    att = v.get('attending_doctor', {})
    print(f"    Attending   : {att.get('prefix')} {att.get('given_name')} {att.get('family_name')} (ID: {att.get('id')})")
    print(f"    Admitted    : {v.get('admit_datetime')}")
    print(f"    Service     : {v.get('hospital_service')}")

    print(f"\n  DIAGNOSES ({len(r.get_diagnoses())})")
    for dx in r.get_diagnoses():
        print(f"    [{dx.get('diagnosis_type','?')}] {dx.get('code'):<12} {dx.get('description')}")

    print(f"\n  ALLERGIES ({len(r.get_allergies())})")
    for al in r.get_allergies():
        print(f"    {al.get('allergen_name'):<20} Severity: {al.get('severity'):<5}  Reactions: {', '.join(al.get('reactions', []))}")

    ins = r.get_insurance()
    print(f"\n  INSURANCE")
    print(f"    Company     : {ins.get('company_name')}")
    print(f"    Plan Type   : {ins.get('plan_type')}")
    print(f"    Policy #    : {ins.get('policy_number')}")

    # ── TEST 2: ORU^R01 Lab Results ──────────────────────────────────────────
    print("\n" + "─" * 68)
    print("  TEST 2 — ORU^R01  (Lab Results)")
    print("─" * 68)

    r2 = parser.parse(SAMPLE_ORU)
    print(f"  Success       : {r2.success}")
    print(f"  Message Type  : {r2.message_type}")

    lab = r2.get_lab_results()
    svc = lab.get("service", {})
    pvd = lab.get("ordering_provider", {})
    print(f"\n  LAB ORDER")
    print(f"    Test        : {svc.get('text')} ({svc.get('code')})")
    print(f"    Ordered By  : {pvd.get('given_name')} {pvd.get('family_name')}")
    print(f"    Status      : {lab.get('result_status')}")
    print(f"    Collected   : {lab.get('observation_datetime')}")
    print(f"    Abnormal    : {lab.get('abnormal_count')}/{lab.get('total_count')} results")
    print(f"    Critical    : {lab.get('critical_count')} results")

    print(f"\n  {'TEST':<30}  {'VALUE':<12}  {'UNIT':<12}  {'RANGE':<15}  FLAG")
    print(f"  {'─'*30}  {'─'*12}  {'─'*12}  {'─'*15}  {'─'*8}")
    for obs in lab.get("observations", []):
        flag = f"⚠ {obs['abnormal_flag']} [{obs['severity'].upper()}]" if obs.get("is_abnormal") else "✓ Normal"
        print(f"  {obs['identifier']['text']:<30}  {obs['value']:<12}  {obs['units']:<12}  {obs['reference_range']:<15}  {flag}")

    if lab.get("notes"):
        print(f"\n  NOTES")
        for note in lab["notes"]:
            print(f"    • {note}")

    # ── JSON output ───────────────────────────────────────────────────────────
    print(f"\n{'─' * 68}")
    print("  JSON OUTPUT SAMPLE  (ADT message summary only)")
    print("─" * 68)
    print(json.dumps(r.summary, indent=2, default=str))

    print(f"\n{sep}")
    print("  Done. Import HL7Parser in your own code to use.")
    print(sep)


if __name__ == "__main__":
    demo()
