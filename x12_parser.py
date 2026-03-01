"""
╔══════════════════════════════════════════════════════════════════════════╗
║         X12 EDI HEALTHCARE TRANSACTION PARSERS  -  Standalone           ║
║                                                                          ║
║  Transactions:                                                           ║
║    MO4  (277CA) - Claims Acknowledgment / Status                        ║
║    837I         - Institutional Claims (hospital/facility)               ║
║    837P         - Professional Claims (physician/practitioner)           ║
║    837D         - Dental Claims                                          ║
║    835          - Healthcare Payment / Remittance Advice                 ║
║                                                                          ║
║  Requires : Python 3.9+  -  zero external dependencies                   ║
╚══════════════════════════════════════════════════════════════════════════╝

QUICK START:
    from x12_parser import X12Parser

    parser = X12Parser()

    # Auto-detect transaction type and parse
    result = parser.parse(raw_x12_string)

    # Or parse specific type
    result = parser.parse_837p(raw_x12_string)
    result = parser.parse_835(raw_x12_string)

    print(result.success)           # True / False
    print(result.transaction_type)  # e.g. "837P"
    print(result.summary)           # structured clinical/financial data
    print(result.to_json())         # full JSON

Run as script for built-in demo:
    python x12_parser.py
"""

import json
import re
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, field


# =============================================================================
# REFERENCE TABLES
# =============================================================================

# X12 segment delimiters (defaults, overridden from ISA)
DEFAULT_ELEMENT_SEP   = "*"
DEFAULT_SEGMENT_SEP   = "~"
DEFAULT_COMPONENT_SEP = ":"

# ISA element 16 defines component separator; ISA ends with segment terminator
# Typical X12: ISA*00* ... *:~

# Transaction Set IDs
TRANSACTION_TYPES = {
    "270": "Eligibility Inquiry",
    "271": "Eligibility Response",
    "276": "Claim Status Request",
    "277": "Claim Status Response / Acknowledgment (MO4)",
    "278": "Prior Authorization",
    "820": "Payment Order/Remittance Advice",
    "834": "Benefit Enrollment",
    "835": "Healthcare Payment / Remittance Advice",
    "837": "Healthcare Claim",
    "999": "Implementation Acknowledgment",
}

# 837 sub-types by GS/ST hierarchical level
CLAIM_SUBTYPES = {
    "HealthCare": {
        "CH":  "837P - Professional",
        "HC":  "837I - Institutional",
        "HS":  "837D - Dental",
    }
}

# Claim frequency codes
CLAIM_FREQUENCY = {
    "1": "Original",
    "2": "Interim - First Claim",
    "3": "Interim - Continuing Claim",
    "4": "Interim - Last Claim",
    "5": "Late Charge",
    "7": "Replacement of Prior Claim",
    "8": "Void/Cancel of Prior Claim",
}

# Service type codes (270/271)
SERVICE_TYPES = {
    "1":  "Medical Care",
    "2":  "Surgical",
    "3":  "Consultation",
    "4":  "Diagnostic X-Ray",
    "5":  "Diagnostic Lab",
    "33": "Chiropractic",
    "35": "Dental Care",
    "47": "Hospital",
    "48": "Hospital - Inpatient",
    "50": "Hospital - Outpatient",
    "73": "Dialysis",
    "86": "Emergency Services",
    "98": "Professional (Physician) Visit - Office",
    "30": "Plan Coverage and General Benefits",
    "UC": "Urgent Care",
    "AK": "Durable Medical Equipment",
}

# Claim status category codes (277)
STATUS_CATEGORY = {
    "A0": "Acknowledged/Accepted",
    "A1": "Acknowledgment/Returned as Unprocessable Claim",
    "A2": "Acknowledgment/Rejected for Missing Info",
    "A3": "Acknowledgment/Rejected for Invalid Info",
    "A4": "Acknowledgment/Rejected - Entity not found",
    "A6": "Acknowledgment/Rejected - Missing Provider Agreement",
    "A7": "Acknowledgment/Rejected - Authorization Required",
    "A8": "Acknowledgment/Rejected - In Process",
    "DR": "Pended - Response not available",
    "E0": "Response not possible - System Status",
    "F0": "Finalized",
    "F1": "Finalized/Payment - The claim/line has been paid.",
    "F2": "Finalized/Denial - The claim/line has been denied.",
    "F3": "Finalized/Revised - Adjudication information was revised.",
    "F4": "Finalized/Adjudication Complete",
    "P0": "Pending",
    "P1": "Pending - Requires information",
    "P2": "Pending - Suspended",
    "R0": "Requests for information",
    "R3": "Returned as Unprocessable Claim",
}

# Claim adjustment reason codes (835 CAS)
ADJ_REASON_CODES = {
    "1":   "Deductible Amount",
    "2":   "Coinsurance Amount",
    "3":   "Co-payment Amount",
    "4":   "The procedure code is inconsistent with the modifier",
    "5":   "The procedure code/bill type is inconsistent with the place of service",
    "6":   "The procedure/revenue code is inconsistent with the patient's age",
    "7":   "The procedure/revenue code is inconsistent with the patient's sex",
    "8":   "The procedure code is inconsistent with the provider type",
    "9":   "The diagnosis is inconsistent with the patient's age",
    "10":  "The diagnosis is inconsistent with the patient's sex",
    "11":  "The diagnosis is inconsistent with the procedure",
    "12":  "The diagnosis is inconsistent with the provider type",
    "13":  "The date of death precedes the date of service",
    "16":  "Claim/service lacks information which is needed for adjudication",
    "18":  "Exact duplicate claim/service",
    "19":  "Expenses incurred prior to coverage",
    "20":  "Expenses incurred after coverage terminated",
    "21":  "This service was partially or fully furnished by another provider",
    "22":  "This care may be covered by another payer",
    "23":  "Charges exceed our fee schedule",
    "24":  "Charges are covered under a capitation agreement",
    "26":  "Expenses incurred prior to coverage",
    "27":  "Expenses incurred after coverage terminated",
    "29":  "The time limit for filing has expired",
    "45":  "Charge exceeds fee schedule/maximum allowable or contracted/legislated fee arrangement",
    "49":  "This is a non-covered service because it is a routine/preventive exam",
    "50":  "These are non-covered services",
    "51":  "These are non-covered services - not medically necessary",
    "52":  "The referring/prescribing/rendering provider is not eligible to refer/prescribe/order",
    "53":  "Services by an immediate relative or a member of the same household are not covered",
    "54":  "Multiple physicians/assistants are not covered in this case",
    "55":  "Claim/service denied. Plan procedures not followed",
    "56":  "Claim/service denied",
    "57":  "Plan procedures not followed - prior authorization not obtained",
    "58":  "Treatment was deemed by the payer to have been rendered in an inappropriate or invalid place of service",
    "59":  "Processed based on multiple or concurrent procedure rules",
    "96":  "Non-covered charge(s)",
    "97":  "The benefit for this service is included in the payment/allowance",
    "100": "Payment made to patient/insured/responsible party",
    "109": "Claim/service not covered by this payer/contractor",
    "119": "Benefit maximum for this time period or occurrence has been reached",
    "125": "Submission/billing error(s)",
    "129": "Prior processing information appears incorrect",
    "131": "Claim specific negotiated discount",
    "132": "Prearranged demonstration project adjustment",
    "133": "The disposition of this service line is pending further review",
    "139": "Contracted funding agreement - Subscriber is employed by the Provider",
    "140": "Patient/Insured health identification number and name do not match",
    "143": "Portion of payment deferred",
    "144": "Incentive adjustment",
    "146": "Diagnosis was invalid for the date(s) of service reported",
    "147": "Provider contracted/negotiated rate expired or not on file",
    "148": "Information from another provider was not provided or was insufficient/incomplete",
    "149": "Lifetime benefit maximum has been reached for this service/benefit category",
    "150": "Payer deems the information submitted does not support this level of service",
    "151": "Payment adjusted because the payer deems the information submitted does not support this many/frequency of services",
    "152": "Payer deems the information submitted does not support this length of service",
    "153": "Payer deems the information submitted does not support this dosage",
    "154": "Payer deems the information submitted does not support this day's supply",
    "155": "This claim/service has been identified as a readmission",
    "157": "Service/procedure was provided as a result of an act of war",
    "158": "Service/procedure was provided outside of the United States",
    "163": "Attachment/other documentation referenced on the claim was not received",
    "164": "Attachment/other documentation referenced on the claim was not received in a timely fashion",
    "165": "Referral absent or exceeded",
    "166": "These services were submitted after this plan's coordination of benefits cutoff date",
    "167": "This (these) diagnosis(es) is (are) not covered",
    "169": "Alternate benefit has been provided",
    "170": "Payment is denied when performed/billed by this type of provider",
    "171": "Payment is denied when performed/billed by this type of provider in this type of facility",
    "172": "Payment is adjusted when performed/billed by a specialist",
    "173": "Payment is adjusted when performed/billed by this type of provider",
    "174": "Payment is adjusted when performed/billed by this type of provider in this type of facility",
    "175": "Claim/service was not covered by the demonstration project",
    "176": "Services not related to the primary diagnosis",
    "177": "Patient has not met the required eligibility requirements",
    "178": "Claim/service has been adjudicated for inpatient benefits",
    "179": "Patient has not met the Spenddown requirement",
    "180": "Claim/service denied based on the accreditation status of the rendering/treating provider",
    "181": "Identification of the provider or insured; or the provider's/insured's agreement with the Plan is not on file",
    "182": "Procedure modifier was invalid on the date of service",
    "183": "The referring provider is not eligible to refer the service billed",
    "184": "The prescribing/ordering provider is not eligible to prescribe/order the service billed",
    "185": "Claim/service denied because a hospital refused to provide necessary information",
    "186": "Level of care change adjustment",
    "187": "Consumer Spending Account payments (HRA, FSA, Flex Spending)",
    "188": "This product/procedure requires that a specific diagnosis be used for reimbursement",
    "189": "Not otherwise classified or not otherwise specified income is not covered",
    "190": "Payment is included in the allowance for a Skilled Nursing Facility (SNF) stay",
    "191": "Not a work related injury/illness and thus not the liability of the Workers' Compensation carrier",
    "192": "Non standard adjustment code from paper remittance",
    "193": "Original payment decision is being maintained",
    "194": "Claim/service denied - claim not appealed timely",
    "195": "Plan procedures not followed",
    "197": "Precertification/authorization/notification/pre-treatment absent",
    "198": "Precertification/authorization exceeded",
    "199": "Revenue code and Procedure code do not match",
    "200": "Expenses incurred during lapse in coverage",
    "201": "Workers' Compensation case settled. Patient is responsible for amount of this claim/service through WC 'Medicare set aside arrangement' or other agreement",
    "202": "Non-covered personal comfort or convenience services",
    "203": "Discontinued or reduced service",
    "204": "This service/equipment/drug is not covered under the patient's current benefit plan",
    "222": "Exceeds the contracted maximum number of hours/days/units by this provider for this period",
    "223": "Adjustment code for mandated federal, state or local law/regulation that is not already covered by another code and is mandated before a new code can be created",
    "226": "Information requested from the Billing/Rendering Provider was not provided or not provided timely or was insufficient/incomplete",
    "227": "Information requested from the patient/insured/responsible party was not provided or not provided timely or was insufficient/incomplete",
    "228": "Remittance advice not timely",
    "229": "Partial charge amount not covered by Medicare due to the impact of prior payer(s) adjudication including payments and/or adjustments",
    "230": "No available or correlating CPT/HCPCS code to describe this service",
    "231": "Mutually exclusive procedures cannot be done in the same day/setting",
    "232": "Institutional Transfer Amount",
    "233": "Services/charges related to the treatment of a hospital-acquired condition or preventable medical error",
    "234": "This procedure is not paid separately",
    "235": "Sales Tax",
    "236": "This procedure or procedure/modifier combination is not compatible with another procedure or procedure/modifier combination provided on the same day according to the National Correct Coding Initiative or workers compensation state regulations/fee schedule requirements",
    "237": "Legislated/Regulatory Penalty",
    "238": "Claim span includes dates not covered or not consistent with level of care",
    "239": "Claim spans eligible and ineligible periods of coverage",
    "240": "The procedure(s) billed are inconsistent with the revenue code",
    "P1": "Pending: Investigating",
    "P2": "Pending: Investigating Third-Party Liability",
    "P3": "Pending: Provider of Service to Resubmit Claims",
    "P4": "Pending: Patient to Provide Information to Payer",
    "P5": "Pending: Payer Administrative/System Limitation",
    "CO": "Contractual Obligations",
    "CR": "Corrections and Reversals",
    "OA": "Other Adjustments",
    "PI": "Payer Initiated Reductions",
    "PR": "Patient Responsibility",
}

# Place of service codes
PLACE_OF_SERVICE = {
    "01": "Pharmacy",
    "02": "Telehealth",
    "03": "School",
    "04": "Homeless Shelter",
    "05": "Indian Health Service Free-standing Facility",
    "06": "Indian Health Service Provider-based Facility",
    "07": "Tribal 638 Free-standing Facility",
    "08": "Tribal 638 Provider-based Facility",
    "09": "Prison/Correctional Facility",
    "10": "Telehealth Provided in Patient's Home",
    "11": "Office",
    "12": "Home",
    "13": "Assisted Living Facility",
    "14": "Group Home",
    "15": "Mobile Unit",
    "16": "Temporary Lodging",
    "17": "Walk-in Retail Health Clinic",
    "18": "Place of Employment/Worksite",
    "19": "Off Campus-Outpatient Hospital",
    "20": "Urgent Care Facility",
    "21": "Inpatient Hospital",
    "22": "On Campus-Outpatient Hospital",
    "23": "Emergency Room - Hospital",
    "24": "Ambulatory Surgical Center",
    "25": "Birthing Center",
    "26": "Military Treatment Facility",
    "27": "Outreach Site/Street",
    "28": "Nursing Facility",
    "31": "Skilled Nursing Facility",
    "32": "Nursing Facility",
    "33": "Custodial Care Facility",
    "34": "Hospice",
    "41": "Ambulance - Land",
    "42": "Ambulance - Air or Water",
    "49": "Independent Clinic",
    "50": "Federally Qualified Health Center",
    "51": "Inpatient Psychiatric Facility",
    "52": "Psychiatric Facility Partial Hospitalization",
    "53": "Community Mental Health Center",
    "54": "Intermediate Care Facility/Individuals with Intellectual Disabilities",
    "55": "Residential Substance Abuse Treatment Facility",
    "56": "Psychiatric Residential Treatment Center",
    "57": "Non-residential Substance Abuse Treatment Facility",
    "58": "Non-residential Opioid Treatment Facility",
    "60": "Mass Immunization Center",
    "61": "Comprehensive Inpatient Rehabilitation Facility",
    "62": "Comprehensive Outpatient Rehabilitation Facility",
    "65": "End-Stage Renal Disease Treatment Facility",
    "71": "Public Health Clinic",
    "72": "Rural Health Clinic",
    "81": "Independent Laboratory",
    "99": "Other Place of Service",
}

# Entity identifier codes
ENTITY_CODES = {
    "40":  "Receiver",
    "41":  "Submitter",
    "1P":  "Provider",
    "1Z":  "Person",
    "2B":  "Subscriber",
    "36":  "Employer",
    "80":  "Hospital",
    "85":  "Billing Provider",
    "87":  "Pay-to Provider",
    "FA":  "Facility",
    "IL":  "Insured or Subscriber",
    "PR":  "Payer",
    "PT":  "Patient",
    "QC":  "Patient",
    "SJ":  "Service Facility",
    "77":  "Service Location",
    "82":  "Rendering Provider",
    "DN":  "Referring Provider",
    "DK":  "Ordering Provider",
    "DQ":  "Supervising Provider",
    "PW":  "Ambulance Pick-up Location",
    "45":  "Drop-off Location",
}


# =============================================================================
# RESULT
# =============================================================================

@dataclass
class X12ParseResult:
    success: bool
    transaction_type: str
    raw_segments: list = field(default_factory=list)
    envelope: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps({
            "success":          self.success,
            "transaction_type": self.transaction_type,
            "envelope":         self.envelope,
            "summary":          self.summary,
            "errors":           self.errors,
            "warnings":         self.warnings,
        }, indent=indent, default=str)

    def get_claims(self) -> list:
        return self.summary.get("claims", [])

    def get_payments(self) -> list:
        return self.summary.get("claim_payments", [])

    def get_financial_summary(self) -> dict:
        return self.summary.get("financial_summary", {})


# =============================================================================
# BASE X12 PARSER
# =============================================================================

class BaseX12Parser:
    """
    Base class for all X12 parsers.
    Handles envelope parsing, segment splitting, and element access.
    """

    def __init__(self):
        self.element_sep   = DEFAULT_ELEMENT_SEP
        self.segment_sep   = DEFAULT_SEGMENT_SEP
        self.component_sep = DEFAULT_COMPONENT_SEP
        self._segments     = []

    def _detect_delimiters(self, raw: str) -> str:
        """
        Detect delimiters from the ISA segment.
        ISA is always exactly 106 characters.
        Returns normalised string.
        """
        raw = raw.strip()

        # Find ISA segment
        isa_start = raw.find("ISA")
        if isa_start == -1:
            return raw

        isa = raw[isa_start:isa_start + 106]

        if len(isa) >= 4:
            self.element_sep = isa[3]

        # Component separator is ISA element 16 (position 104 in the 106-char ISA)
        if len(isa) >= 105:
            self.component_sep = isa[104]

        # Segment terminator is the character right after ISA element 16
        if len(isa) >= 106:
            self.segment_sep = isa[105]
        else:
            # Fall back: look for ~ after ISA
            for ch in ["~", "\n", "\r"]:
                if ch in raw[isa_start + 100:isa_start + 120]:
                    self.segment_sep = ch
                    break

        return raw

    def _split_segments(self, raw: str) -> list:
        """Split raw X12 into individual segment strings."""
        raw = self._detect_delimiters(raw)
        segments = []
        for seg in raw.split(self.segment_sep):
            seg = seg.strip()
            if seg:
                segments.append(seg)
        return segments

    def _parse_segment(self, seg_str: str) -> dict:
        """Parse one segment string into id + elements list."""
        elements = seg_str.split(self.element_sep)
        return {
            "id":       elements[0].strip(),
            "elements": elements,
            "raw":      seg_str,
        }

    def _elem(self, seg: dict, idx: int, default: str = "") -> str:
        """Safely get element by index (1-based matches X12 convention)."""
        elems = seg.get("elements", [])
        return elems[idx].strip() if idx < len(elems) else default

    def _comp(self, value: str, idx: int, default: str = "") -> str:
        """Get component from a composite element."""
        if not value:
            return default
        parts = value.split(self.component_sep)
        return parts[idx].strip() if idx < len(parts) else default

    def _date(self, d: str) -> Optional[str]:
        """Parse X12 date CCYYMMDD or YYMMDD to ISO."""
        if not d:
            return None
        d = d.strip()
        for fmt, length in [("%Y%m%d", 8), ("%y%m%d", 6)]:
            if len(d) >= length:
                try:
                    return datetime.strptime(d[:length], fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return d

    def _time(self, t: str) -> Optional[str]:
        """Parse X12 time HHMM or HHMMSS."""
        if not t:
            return None
        t = t.strip()
        for fmt, length in [("%H%M%S", 6), ("%H%M", 4)]:
            if len(t) >= length:
                try:
                    return datetime.strptime(t[:length], fmt).strftime("%H:%M:%S" if length == 6 else "%H:%M")
                except ValueError:
                    continue
        return t

    def _money(self, val: str) -> Optional[float]:
        """Parse X12 monetary value to float."""
        if not val:
            return None
        try:
            return float(val.strip())
        except ValueError:
            return None

    def _parse_envelope(self, segments: list) -> dict:
        """Parse ISA/GS/ST envelope segments."""
        envelope = {}
        for seg in segments:
            s = self._parse_segment(seg)
            sid = s["id"]

            if sid == "ISA":
                envelope["interchange"] = {
                    "auth_info_qualifier":   self._elem(s, 1),
                    "auth_info":             self._elem(s, 2),
                    "security_qualifier":    self._elem(s, 3),
                    "security_info":         self._elem(s, 4),
                    "sender_id_qualifier":   self._elem(s, 5),
                    "sender_id":             self._elem(s, 6),
                    "receiver_id_qualifier": self._elem(s, 7),
                    "receiver_id":           self._elem(s, 8),
                    "date":                  self._date(self._elem(s, 9)),
                    "time":                  self._time(self._elem(s, 10)),
                    "repetition_separator":  self._elem(s, 11),
                    "version":               self._elem(s, 12),
                    "control_number":        self._elem(s, 13),
                    "ack_requested":         self._elem(s, 14),
                    "usage_indicator":       self._elem(s, 15),  # P=Production, T=Test
                    "component_separator":   self._elem(s, 16),
                }

            elif sid == "GS":
                envelope["functional_group"] = {
                    "functional_id_code":    self._elem(s, 1),
                    "sender_id":             self._elem(s, 2),
                    "receiver_id":           self._elem(s, 3),
                    "date":                  self._date(self._elem(s, 4)),
                    "time":                  self._time(self._elem(s, 5)),
                    "control_number":        self._elem(s, 6),
                    "responsible_agency":    self._elem(s, 7),
                    "version":               self._elem(s, 8),
                }

            elif sid == "ST":
                envelope["transaction_set"] = {
                    "id":             self._elem(s, 1),
                    "control_number": self._elem(s, 2),
                    "version":        self._elem(s, 3),
                    "type_name":      TRANSACTION_TYPES.get(self._elem(s, 1), "Unknown"),
                }
                break  # enough for envelope

        return envelope

    def _get_segments_between(self, segments: list, start_id: str, end_id: str) -> list:
        """Return segments between two segment IDs (inclusive)."""
        result = []
        capturing = False
        for seg in segments:
            s = self._parse_segment(seg)
            if s["id"] == start_id:
                capturing = True
            if capturing:
                result.append(seg)
            if capturing and s["id"] == end_id:
                break
        return result

    def _find_segments(self, segments: list, seg_id: str) -> list:
        """Return all segments with matching ID. Accepts raw strings or parsed dicts."""
        result = []
        for seg in segments:
            s = seg if isinstance(seg, dict) else self._parse_segment(seg)
            if s["id"] == seg_id:
                result.append(s)
        return result

    def _find_first(self, segments: list, seg_id: str) -> Optional[dict]:
        """Return first segment with matching ID, parsed. Accepts raw strings or parsed dicts."""
        for seg in segments:
            s = seg if isinstance(seg, dict) else self._parse_segment(seg)
            if s["id"] == seg_id:
                return s
        return None

    def _parse_nm1(self, s: dict) -> dict:
        """Parse NM1 (entity name) segment."""
        return {
            "entity_id_code":   self._elem(s, 1),
            "entity_type":      "person" if self._elem(s, 2) == "1" else "organization",
            "last_or_org_name": self._elem(s, 3),
            "first_name":       self._elem(s, 4),
            "middle_name":      self._elem(s, 5),
            "name_prefix":      self._elem(s, 6),
            "name_suffix":      self._elem(s, 7),
            "id_code_qualifier":self._elem(s, 8),
            "id_code":          self._elem(s, 9),
            "full_name":        f"{self._elem(s,4)} {self._elem(s,5)} {self._elem(s,3)}".strip() if self._elem(s,2) == "1" else self._elem(s, 3),
        }

    def _parse_n3n4(self, n3: Optional[dict], n4: Optional[dict]) -> dict:
        """Parse N3 (address) and N4 (city/state/zip) into one dict."""
        return {
            "address_line_1": self._elem(n3, 1) if n3 else "",
            "address_line_2": self._elem(n3, 2) if n3 else "",
            "city":           self._elem(n4, 1) if n4 else "",
            "state":          self._elem(n4, 2) if n4 else "",
            "zip":            self._elem(n4, 3) if n4 else "",
            "country":        self._elem(n4, 4) if n4 else "",
        }

    def _parse_ref(self, s: dict) -> dict:
        """Parse REF (reference identification) segment."""
        return {
            "qualifier": self._elem(s, 1),
            "value":     self._elem(s, 2),
            "description": self._elem(s, 3),
        }

    def _parse_dtp(self, s: dict) -> dict:
        """Parse DTP (date/time period) segment."""
        qualifier = self._elem(s, 1)
        format_code = self._elem(s, 2)
        value = self._elem(s, 3)

        parsed = {}
        if format_code == "D8":
            parsed["date"] = self._date(value)
        elif format_code == "RD8":
            parts = value.split("-")
            parsed["start_date"] = self._date(parts[0]) if parts else ""
            parsed["end_date"]   = self._date(parts[1]) if len(parts) > 1 else ""
        else:
            parsed["value"] = value

        return {"qualifier": qualifier, "format": format_code, **parsed}

    def _detect_transaction_type(self, segments: list) -> str:
        """Auto-detect 837 sub-type from GS01 or ST01."""
        for seg in segments:
            s = self._parse_segment(seg)
            if s["id"] == "ST":
                st01 = self._elem(s, 1)
                if st01 == "835":
                    return "835"
                if st01 == "277":
                    return "277"
                if st01 == "837":
                    # Need to look further for BPR or HL loops
                    # Will be determined by GS or claim type
                    pass
            if s["id"] == "GS":
                gs08 = self._elem(s, 8)  # version
                gs01 = self._elem(s, 1)  # functional group ID
                # HC = 837I, HP = 837P, HD = 837D
                if gs01 == "HC":
                    return "837I"
                if gs01 == "HP":
                    return "837P"
                if gs01 == "HD":
                    return "837D"
                if gs01 == "FA":
                    return "999"
                if gs01 == "HB":
                    return "835"
                if gs01 == "HN":
                    return "277"
        return "837P"  # default


# =============================================================================
# 837 CLAIM PARSER  (handles I, P, D)
# =============================================================================

class X12_837Parser(BaseX12Parser):
    """
    Parser for X12 837 Healthcare Claim transactions.
    Handles 837P (Professional), 837I (Institutional), 837D (Dental).
    """

    def parse(self, raw: str, subtype: str = None) -> X12ParseResult:
        """
        Parse an 837 claim transaction.

        Args:
            raw:     Raw X12 string
            subtype: "837P", "837I", "837D" or None (auto-detect)
        """
        try:
            self._segments = self._split_segments(raw)

            # Detect sub-type
            if not subtype:
                subtype = self._detect_transaction_type(self._segments)

            envelope = self._parse_envelope(self._segments)
            parsed_segs = [self._parse_segment(s) for s in self._segments]
            summary  = self._parse_837_body(parsed_segs, subtype)

            return X12ParseResult(
                success=True,
                transaction_type=subtype,
                raw_segments=self._segments,
                envelope=envelope,
                summary=summary,
            )

        except Exception as e:
            return X12ParseResult(False, "837", errors=[f"Parse error: {str(e)}"])

    def _parse_837_body(self, segs: list, subtype: str) -> dict:
        """Parse the body of an 837 transaction."""
        summary = {"transaction_subtype": subtype}

        # Locate submitter (NM1*41)
        submitter = self._find_nm1_by_qualifier(segs, "41")
        summary["submitter"] = submitter

        # Locate receiver (NM1*40)
        receiver = self._find_nm1_by_qualifier(segs, "40")
        summary["receiver"] = receiver

        # Parse all claim loops (HL segments define hierarchy)
        claims = self._parse_claim_loops(segs, subtype)
        summary["claims"] = claims
        summary["claim_count"] = len(claims)

        # Financial totals (CTX or sum)
        total_billed = sum(self._money(c.get("total_billed", "0") or "0") or 0 for c in claims)
        summary["financial_summary"] = {
            "total_claims":     len(claims),
            "total_billed":     round(total_billed, 2),
        }

        return summary

    def _find_nm1_by_qualifier(self, segs: list, qualifier: str) -> dict:
        """Find first NM1 segment with matching entity qualifier."""
        for s in segs:
            if s["id"] == "NM1" and self._elem(s, 1) == qualifier:
                return self._parse_nm1(s)
        return {}

    def _parse_claim_loops(self, segs: list, subtype: str) -> list:
        """
        Parse HL loop hierarchy to extract billing provider, subscriber, and claims.
        Returns a list of claim dicts.
        """
        claims = []
        n = len(segs)
        i = 0

        # Context tracking
        billing_provider = {}
        subscriber       = {}
        patient          = {}

        while i < n:
            s = segs[i]
            sid = s["id"]

            # ── Billing Provider Loop (NM1*85) ────────────────────────────────
            if sid == "NM1" and self._elem(s, 1) == "85":
                billing_provider = self._parse_nm1(s)
                # Look ahead for N3/N4/REF
                j = i + 1
                n3 = n4 = None
                refs = []
                while j < n and segs[j]["id"] not in ("NM1", "CLM", "HL"):
                    if segs[j]["id"] == "N3":
                        n3 = segs[j]
                    elif segs[j]["id"] == "N4":
                        n4 = segs[j]
                    elif segs[j]["id"] == "REF":
                        refs.append(self._parse_ref(segs[j]))
                    j += 1
                billing_provider["address"] = self._parse_n3n4(n3, n4)
                billing_provider["references"] = refs

            # ── Subscriber Loop (NM1*IL) ──────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "IL":
                subscriber = self._parse_nm1(s)
                j = i + 1
                n3 = n4 = None
                refs = []
                dmg = None
                while j < n and segs[j]["id"] not in ("NM1", "CLM"):
                    if segs[j]["id"] == "N3":
                        n3 = segs[j]
                    elif segs[j]["id"] == "N4":
                        n4 = segs[j]
                    elif segs[j]["id"] == "REF":
                        refs.append(self._parse_ref(segs[j]))
                    elif segs[j]["id"] == "DMG":
                        dmg = segs[j]
                    j += 1
                subscriber["address"] = self._parse_n3n4(n3, n4)
                subscriber["references"] = refs
                if dmg:
                    subscriber["dob"]    = self._date(self._elem(dmg, 2))
                    subscriber["gender"] = {"M": "Male", "F": "Female", "U": "Unknown"}.get(self._elem(dmg, 3), self._elem(dmg, 3))

            # ── Patient Loop (NM1*QC) ─────────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) in ("QC", "PT"):
                patient = self._parse_nm1(s)
                j = i + 1
                n3 = n4 = None
                dmg = None
                while j < n and segs[j]["id"] not in ("NM1", "CLM"):
                    if segs[j]["id"] == "N3":
                        n3 = segs[j]
                    elif segs[j]["id"] == "N4":
                        n4 = segs[j]
                    elif segs[j]["id"] == "DMG":
                        dmg = segs[j]
                    j += 1
                patient["address"] = self._parse_n3n4(n3, n4)
                if dmg:
                    patient["dob"]    = self._date(self._elem(dmg, 2))
                    patient["gender"] = {"M": "Male", "F": "Female", "U": "Unknown"}.get(self._elem(dmg, 3), self._elem(dmg, 3))

            # ── Claim Segment (CLM) ───────────────────────────────────────────
            elif sid == "CLM":
                claim = self._parse_clm(s, segs, i, subtype, billing_provider, subscriber, patient)
                claims.append(claim)

            i += 1

        return claims

    def _parse_clm(self, clm: dict, segs: list, clm_idx: int,
                   subtype: str, billing_provider: dict, subscriber: dict, patient: dict) -> dict:
        """Parse a CLM segment and all its related segments into a claim dict."""

        claim = {
            "claim_id":           self._elem(clm, 1),
            "total_billed":       self._elem(clm, 2),
            "facility_code":      self._elem(clm, 5).split(self.component_sep)[0] if self.component_sep in self._elem(clm, 5) else self._elem(clm, 5),
            "place_of_service":   self._comp(self._elem(clm, 5), 0),
            "place_of_service_name": PLACE_OF_SERVICE.get(self._comp(self._elem(clm, 5), 0), ""),
            "claim_frequency":    self._comp(self._elem(clm, 5), 2),
            "claim_frequency_name": CLAIM_FREQUENCY.get(self._comp(self._elem(clm, 5), 2), ""),
            "provider_signature": self._elem(clm, 6),
            "assignment_of_benefits": self._elem(clm, 7),
            "release_of_info":    self._elem(clm, 8),
            "billing_provider":   billing_provider,
            "subscriber":         subscriber,
            "patient":            patient or subscriber,
            "diagnoses":          [],
            "service_lines":      [],
            "dates":              {},
            "references":         [],
            "payer":              {},
            "rendering_provider": {},
            "referring_provider": {},
            "attending_provider": {},
            "operating_provider": {},
            "facility":           {},
            "claim_notes":        [],
        }

        # Scan forward from CLM to next CLM or SE
        i = clm_idx + 1
        n = len(segs)
        current_service_line = None
        svc_components       = []

        while i < n:
            s   = segs[i]
            sid = s["id"]

            if sid == "CLM" or sid == "SE":
                break

            # ── Diagnosis codes (HI) ──────────────────────────────────────────
            elif sid == "HI":
                for e_idx in range(1, 13):
                    dx = self._elem(s, e_idx)
                    if dx:
                        qualifier = self._comp(dx, 0)
                        code      = self._comp(dx, 1)
                        if code:
                            claim["diagnoses"].append({
                                "qualifier": qualifier,
                                "code":      code,
                                "present_on_admission": self._comp(dx, 7) if subtype == "837I" else "",
                            })

            # ── Reference numbers (REF) ───────────────────────────────────────
            elif sid == "REF":
                claim["references"].append(self._parse_ref(s))
                # Special: prior auth
                if self._elem(s, 1) == "G1":
                    claim["prior_auth_number"] = self._elem(s, 2)
                elif self._elem(s, 1) == "F8":
                    claim["original_claim_number"] = self._elem(s, 2)

            # ── Dates (DTP) ───────────────────────────────────────────────────
            elif sid == "DTP":
                dtp = self._parse_dtp(s)
                q = dtp["qualifier"]
                date_labels = {
                    "431": "onset_of_illness",
                    "454": "initial_treatment",
                    "304": "last_seen",
                    "453": "acute_manifestation",
                    "439": "accident",
                    "484": "last_menstrual_period",
                    "455": "last_x_ray",
                    "471": "hearing_vision_prescription",
                    "314": "disability_begin",
                    "360": "disability_end",
                    "297": "hospitalization_start",
                    "298": "hospitalization_end",
                    "435": "admission",
                    "096": "discharge",
                    "472": "service",
                    "573": "accident_hour",
                    "090": "report_start",
                    "091": "report_end",
                }
                label = date_labels.get(q, f"date_{q}")
                claim["dates"][label] = dtp

            # ── Payer (NM1*PR) ────────────────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "PR":
                claim["payer"] = self._parse_nm1(s)

            # ── Rendering Provider (NM1*82) ───────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "82":
                claim["rendering_provider"] = self._parse_nm1(s)

            # ── Referring Provider (NM1*DN) ───────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) in ("DN", "P3"):
                claim["referring_provider"] = self._parse_nm1(s)

            # ── Attending Provider (NM1*71) ───────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "71":
                claim["attending_provider"] = self._parse_nm1(s)

            # ── Operating Provider (NM1*72) ───────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "72":
                claim["operating_provider"] = self._parse_nm1(s)

            # ── Facility (NM1*77 or NM1*FA) ───────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) in ("77", "FA", "SJ"):
                claim["facility"] = self._parse_nm1(s)

            # ── Claim notes (NTE) ─────────────────────────────────────────────
            elif sid == "NTE":
                claim["claim_notes"].append({
                    "qualifier": self._elem(s, 1),
                    "text":      self._elem(s, 2),
                })

            # ── Service line (SV1 = Professional, SV2 = Institutional, SV3 = Dental) ──
            elif sid == "SV1":
                current_service_line = self._parse_sv1(s)
                claim["service_lines"].append(current_service_line)

            elif sid == "SV2":
                current_service_line = self._parse_sv2(s)
                claim["service_lines"].append(current_service_line)

            elif sid == "SV3":
                current_service_line = self._parse_sv3(s)
                claim["service_lines"].append(current_service_line)

            # ── Line item control number (LX) ─────────────────────────────────
            elif sid == "LX":
                # Start of new service line block
                svc_components = []

            # ── Service line date (DTP on service line) ───────────────────────
            elif sid == "DTP" and current_service_line is not None:
                dtp = self._parse_dtp(s)
                if dtp["qualifier"] == "472":
                    current_service_line["service_date"] = dtp.get("date") or dtp.get("start_date")
                    current_service_line["service_date_end"] = dtp.get("end_date")

            # ── Service line REF ──────────────────────────────────────────────
            elif sid == "REF" and current_service_line is not None:
                if "references" not in current_service_line:
                    current_service_line["references"] = []
                current_service_line["references"].append(self._parse_ref(s))

            # ── Service adjudication (CAS on 837) ────────────────────────────
            elif sid == "AMT" and current_service_line is not None:
                current_service_line["amounts"] = current_service_line.get("amounts", {})
                current_service_line["amounts"][self._elem(s, 1)] = self._money(self._elem(s, 2))

            # ── Institutional value codes (HI in I loop) ──────────────────────
            elif sid == "HI" and subtype == "837I":
                # Already handled above but also look for value/condition/occurrence codes
                pass

            i += 1

        # Compute service line totals
        claim["service_line_count"]  = len(claim["service_lines"])
        claim["total_billed_amount"] = self._money(claim["total_billed"])

        return claim

    def _parse_sv1(self, s: dict) -> dict:
        """Parse SV1 - Professional service line."""
        composite = self._elem(s, 1)
        return {
            "type":                "professional",
            "procedure_qualifier": self._comp(composite, 0),
            "procedure_code":      self._comp(composite, 1),
            "modifier_1":          self._comp(composite, 2),
            "modifier_2":          self._comp(composite, 3),
            "modifier_3":          self._comp(composite, 4),
            "modifier_4":          self._comp(composite, 5),
            "description":         self._comp(composite, 6),
            "charge_amount":       self._money(self._elem(s, 2)),
            "unit_of_measure":     self._elem(s, 3),
            "quantity":            self._elem(s, 4),
            "place_of_service":    self._elem(s, 5),
            "place_of_service_name": PLACE_OF_SERVICE.get(self._elem(s, 5), ""),
            "diagnosis_code_pointers": [
                p.strip() for p in self._elem(s, 7).split(self.component_sep) if p.strip()
            ],
        }

    def _parse_sv2(self, s: dict) -> dict:
        """Parse SV2 - Institutional service line."""
        composite = self._elem(s, 2)
        return {
            "type":            "institutional",
            "revenue_code":    self._elem(s, 1),
            "procedure_qualifier": self._comp(composite, 0),
            "procedure_code":  self._comp(composite, 1),
            "modifier_1":      self._comp(composite, 2),
            "modifier_2":      self._comp(composite, 3),
            "charge_amount":   self._money(self._elem(s, 3)),
            "unit_of_measure": self._elem(s, 4),
            "quantity":        self._elem(s, 5),
            "unit_rate":       self._money(self._elem(s, 7)),
            "non_covered_charge": self._money(self._elem(s, 8)),
        }

    def _parse_sv3(self, s: dict) -> dict:
        """Parse SV3 - Dental service line."""
        composite = self._elem(s, 1)
        return {
            "type":              "dental",
            "procedure_qualifier": self._comp(composite, 0),
            "procedure_code":    self._comp(composite, 1),
            "procedure_modifier":self._comp(composite, 2),
            "description":       self._comp(composite, 3),
            "charge_amount":     self._money(self._elem(s, 2)),
            "procedure_count":   self._elem(s, 3),
            "oral_cavity_code":  self._elem(s, 4),
            "prosthesis_code":   self._elem(s, 5),
            "tooth_code":        self._elem(s, 10),
            "tooth_surface": [
                t.strip() for t in self._elem(s, 11).split(self.component_sep) if t.strip()
            ],
        }


# =============================================================================
# 835 PAYMENT / REMITTANCE PARSER
# =============================================================================

class X12_835Parser(BaseX12Parser):
    """
    Parser for X12 835 Healthcare Payment / Remittance Advice transactions.
    """

    def parse(self, raw: str) -> X12ParseResult:
        """Parse an 835 remittance advice transaction."""
        try:
            self._segments = self._split_segments(raw)

            envelope = self._parse_envelope(self._segments)
            # Pass raw segment strings; internal methods parse as needed
            summary  = self._parse_835_body(self._segments)

            return X12ParseResult(
                success=True,
                transaction_type="835",
                raw_segments=self._segments,
                envelope=envelope,
                summary=summary,
            )

        except Exception as e:
            return X12ParseResult(False, "835", errors=[f"Parse error: {str(e)}"])

    def _parse_835_body(self, raw_segs: list) -> dict:
        segs = [self._parse_segment(s) for s in raw_segs]
        summary = {}

        # ── BPR - Financial Information ───────────────────────────────────────
        bpr = self._find_first(segs, "BPR")
        if bpr:
            summary["payment"] = {
                "transaction_handling": self._elem(bpr, 1),   # C=Payment, D=Debit, I=Non-payment
                "total_payment_amount": self._money(self._elem(bpr, 2)),
                "credit_debit":         self._elem(bpr, 3),   # C=Credit
                "payment_method":       self._elem(bpr, 4),   # ACH, CHK, etc
                "payment_format":       self._elem(bpr, 5),
                "sender_aba":           self._elem(bpr, 7),
                "sender_account_type":  self._elem(bpr, 8),
                "sender_account":       self._elem(bpr, 9),
                "originating_company":  self._elem(bpr, 10),
                "receiver_aba":         self._elem(bpr, 12),
                "receiver_account_type":self._elem(bpr, 13),
                "receiver_account":     self._elem(bpr, 14),
                "payment_date":         self._date(self._elem(bpr, 16)),
            }

        # ── TRN - Trace Number ────────────────────────────────────────────────
        trn = self._find_first(segs, "TRN")
        if trn:
            summary["trace"] = {
                "type_code":       self._elem(trn, 1),
                "reference_number":self._elem(trn, 2),
                "originator_id":   self._elem(trn, 3),
                "reference_id":    self._elem(trn, 4),
            }

        # ── Payer (NM1*PR or N1*PR) ────────────────────────────────────────────
        for s in segs:
            if s["id"] in ("NM1", "N1") and self._elem(s, 1) == "PR":
                if s["id"] == "NM1":
                    summary["payer"] = self._parse_nm1(s)
                else:
                    summary["payer"] = {
                        "full_name": self._elem(s, 2),
                        "id_code_qualifier": self._elem(s, 3),
                        "id_code": self._elem(s, 4),
                    }
                break

        # ── Payee (NM1*PE or N1*PE) ────────────────────────────────────────────
        for idx, s in enumerate(segs):
            if s["id"] in ("NM1", "N1") and self._elem(s, 1) == "PE":
                if s["id"] == "NM1":
                    payee = self._parse_nm1(s)
                else:
                    payee = {
                        "full_name": self._elem(s, 2),
                        "id_code_qualifier": self._elem(s, 3),
                        "id_code": self._elem(s, 4),
                    }
                n3 = n4 = None
                for j in range(idx + 1, min(idx + 6, len(segs))):
                    if segs[j]["id"] == "N3":
                        n3 = segs[j]
                    elif segs[j]["id"] == "N4":
                        n4 = segs[j]
                payee["address"] = self._parse_n3n4(n3, n4)
                summary["payee"] = payee
                break

        # ── Claim payment loops (CLP) ─────────────────────────────────────────
        claim_payments = self._parse_clp_loops(segs)  # segs already parsed
        summary["claim_payments"] = claim_payments
        summary["claim_count"]    = len(claim_payments)

        # ── Financial Summary ─────────────────────────────────────────────────
        def _safe_float(v):
            if v is None: return 0.0
            if isinstance(v, (int, float)): return float(v)
            try: return float(str(v).strip())
            except: return 0.0

        total_charged  = sum(_safe_float(cp.get("charged_amount")) for cp in claim_payments)
        total_paid     = sum(_safe_float(cp.get("paid_amount")) for cp in claim_payments)
        total_patient  = sum(_safe_float(cp.get("patient_responsibility_total")) for cp in claim_payments)
        total_adjustments = sum(
            sum(_safe_float(adj.get("adjustment_amount")) for adj in cp.get("adjustments", []))
            for cp in claim_payments
        )

        summary["financial_summary"] = {
            "total_payment":        summary.get("payment", {}).get("total_payment_amount", 0),
            "total_claims":         len(claim_payments),
            "total_charged":        round(total_charged, 2),
            "total_paid":           round(total_paid, 2),
            "total_patient_resp":   round(total_patient, 2),
            "total_adjustments":    round(total_adjustments, 2),
            "payment_date":         summary.get("payment", {}).get("payment_date"),
            "payment_method":       summary.get("payment", {}).get("payment_method"),
        }

        return summary

    def _parse_clp_loops(self, segs: list) -> list:
        """Parse all CLP (claim-level payment) loops. Expects pre-parsed segment dicts."""
        claims = []
        n = len(segs)
        i = 0

        while i < n:
            s = segs[i]
            if s["id"] == "CLP":
                claim = self._parse_clp(s, segs, i)
                claims.append(claim)
            i += 1

        return claims

    def _parse_clp(self, clp: dict, segs: list, clp_idx: int) -> dict:
        """Parse CLP segment and all subordinate segments."""
        status_code = self._elem(clp, 2)
        status_map  = {
            "1":  "Processed as Primary",
            "2":  "Processed as Secondary",
            "3":  "Processed as Tertiary",
            "4":  "Denied",
            "19": "Processed as Primary, Forwarded to Additional Payer",
            "20": "Processed as Secondary, Forwarded to Additional Payer",
            "21": "Reversal of Previous Payment",
            "22": "Partial Reversal of Previous Payment",
            "23": "Reversal of Overpayment Recovery",
        }

        claim = {
            "patient_control_number": self._elem(clp, 1),
            "claim_status_code":      status_code,
            "claim_status":           status_map.get(status_code, status_code),
            "charged_amount":         self._money(self._elem(clp, 3)),
            "paid_amount":            self._money(self._elem(clp, 4)),
            "patient_responsibility": self._money(self._elem(clp, 5)),
            "claim_type":             self._elem(clp, 6),  # 12=HMO, 13=PPO etc.
            "payer_claim_number":     self._elem(clp, 7),
            "facility_type":          self._elem(clp, 8),
            "claim_frequency":        self._elem(clp, 9),
            "drg_code":               self._elem(clp, 10),
            "drg_weight":             self._elem(clp, 11),
            "discharge_fraction":     self._elem(clp, 12),
            "adjustments":            [],
            "service_payments":       [],
            "patient":                {},
            "insured":                {},
            "corrected_patient":      {},
            "rendering_provider":     {},
            "crossover_carrier":      {},
            "references":             [],
            "dates":                  {},
            "claim_notes":            [],
            "amount_details":         {},
            "patient_responsibility_total": 0.0,
        }

        i = clp_idx + 1
        n = len(segs)
        current_svc = None

        while i < n:
            s   = segs[i]
            sid = s["id"]

            if sid == "CLP":
                break  # start of next claim

            # ── Claim-level adjustments (CAS) ─────────────────────────────────
            elif sid == "CAS" and current_svc is None:
                adj = self._parse_cas(s)
                claim["adjustments"].extend(adj)

            # ── Patient (NM1*QC) ──────────────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "QC":
                claim["patient"] = self._parse_nm1(s)

            # ── Insured (NM1*IL) ──────────────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "IL":
                claim["insured"] = self._parse_nm1(s)

            # ── Corrected Patient (NM1*74) ────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "74":
                claim["corrected_patient"] = self._parse_nm1(s)

            # ── Rendering Provider (NM1*82) ───────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "82":
                claim["rendering_provider"] = self._parse_nm1(s)

            # ── Crossover Carrier (NM1*TT) ────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "TT":
                claim["crossover_carrier"] = self._parse_nm1(s)

            # ── Reference numbers (REF) ───────────────────────────────────────
            elif sid == "REF" and current_svc is None:
                ref = self._parse_ref(s)
                claim["references"].append(ref)
                if ref["qualifier"] == "EA":
                    claim["medical_record_number"] = ref["value"]
                elif ref["qualifier"] == "1L":
                    claim["group_number"] = ref["value"]
                elif ref["qualifier"] == "1W":
                    claim["member_id"] = ref["value"]

            # ── Dates (DTP) ───────────────────────────────────────────────────
            elif sid == "DTP" and current_svc is None:
                dtp = self._parse_dtp(s)
                label = {
                    "232": "claim_statement_from",
                    "233": "claim_statement_to",
                    "050": "claim_received",
                    "036": "expiration",
                    "472": "service",
                }.get(dtp["qualifier"], f"date_{dtp['qualifier']}")
                claim["dates"][label] = dtp

            # ── Claim amounts (AMT) ───────────────────────────────────────────
            elif sid == "AMT" and current_svc is None:
                amt_labels = {
                    "AU": "covered_amount",
                    "D8": "discount_amount",
                    "DY": "per_day_limit",
                    "F5": "patient_amount_paid",
                    "I":  "interest",
                    "NL": "negative_ledger_balance",
                    "NW": "allowed_not_paid",
                    "T": "tax",
                    "T2": "total_claim_before_taxes",
                    "ZK": "federal_mandated_amount",
                    "B6": "allowed_amount",
                    "KH": "deductible_amount",
                    "EAF": "co-payment_amount",
                    "A8": "coinsurance_amount",
                }
                label = amt_labels.get(self._elem(s, 1), f"amount_{self._elem(s,1)}")
                claim["amount_details"][label] = self._money(self._elem(s, 2))
                if self._elem(s, 1) in ("A8", "EAF", "KH"):
                    claim["patient_responsibility_total"] += self._money(self._elem(s, 2)) or 0

            # ── Claim notes (MOA, LQ) ─────────────────────────────────────────
            elif sid == "MOA":
                claim["claim_notes"].append({
                    "type":    "MOA",
                    "remark_code_1": self._elem(s, 2),
                    "remark_code_2": self._elem(s, 3),
                    "remark_code_3": self._elem(s, 4),
                    "remark_code_4": self._elem(s, 5),
                    "remark_code_5": self._elem(s, 6),
                })

            # ── Service Line (SVC) ────────────────────────────────────────────
            elif sid == "SVC":
                current_svc = self._parse_svc(s)
                claim["service_payments"].append(current_svc)

            # ── Service-level adjustments (CAS after SVC) ────────────────────
            elif sid == "CAS" and current_svc is not None:
                adjs = self._parse_cas(s)
                current_svc["adjustments"].extend(adjs)

            # ── Service-level dates ───────────────────────────────────────────
            elif sid == "DTP" and current_svc is not None:
                dtp = self._parse_dtp(s)
                if dtp["qualifier"] == "472":
                    current_svc["service_date"]     = dtp.get("date") or dtp.get("start_date")
                    current_svc["service_date_end"] = dtp.get("end_date")

            # ── Service-level REF ─────────────────────────────────────────────
            elif sid == "REF" and current_svc is not None:
                current_svc["references"] = current_svc.get("references", [])
                current_svc["references"].append(self._parse_ref(s))

            # ── Service-level AMT ─────────────────────────────────────────────
            elif sid == "AMT" and current_svc is not None:
                current_svc["amounts"] = current_svc.get("amounts", {})
                current_svc["amounts"][self._elem(s, 1)] = self._money(self._elem(s, 2))

            # ── Service remark codes (LQ) ────────────────────────────────────
            elif sid == "LQ":
                if current_svc:
                    current_svc["remark_codes"] = current_svc.get("remark_codes", [])
                    current_svc["remark_codes"].append({
                        "qualifier": self._elem(s, 1),
                        "code":      self._elem(s, 2),
                    })

            i += 1

        # Compute per-claim totals
        claim["service_line_count"] = len(claim["service_payments"])
        claim["total_service_paid"] = round(
            sum(svc.get("paid_amount") or 0 for svc in claim["service_payments"]), 2
        )
        claim["total_service_adjustments"] = round(
            sum(adj.get("adjustment_amount") or 0 for adj in claim["adjustments"]), 2
        )

        return claim

    def _parse_svc(self, s: dict) -> dict:
        """Parse SVC (service payment information) segment."""
        composite     = self._elem(s, 1)
        adj_composite = self._elem(s, 6)

        return {
            "procedure_qualifier":    self._comp(composite, 0),
            "procedure_code":         self._comp(composite, 1),
            "modifier_1":             self._comp(composite, 2),
            "modifier_2":             self._comp(composite, 3),
            "modifier_3":             self._comp(composite, 4),
            "modifier_4":             self._comp(composite, 5),
            "charged_amount":         self._money(self._elem(s, 2)),
            "paid_amount":            self._money(self._elem(s, 3)),
            "national_uniform_rate":  self._money(self._elem(s, 4)),
            "revenue_code":           self._elem(s, 5),
            "units":                  self._elem(s, 7),
            "original_procedure_code":self._comp(adj_composite, 1),
            "adjustments":            [],
            "service_date":           None,
            "service_date_end":       None,
        }

    def _parse_cas(self, s: dict) -> list:
        """
        Parse CAS (claim adjustment) segment.
        Returns a list of individual adjustment dicts
        (each CAS can contain up to 3 reason/amount pairs).
        """
        adjustments = []
        group_code  = self._elem(s, 1)

        # CAS can have up to 3 reason/amount/quantity triplets (elements 2-10)
        for offset in range(3):
            base     = 2 + offset * 3
            reason   = self._elem(s, base)
            amount   = self._money(self._elem(s, base + 1))
            quantity = self._elem(s, base + 2)

            if reason:
                adjustments.append({
                    "group_code":         group_code,
                    "group_code_name":    {"CO": "Contractual Obligation", "OA": "Other Adjustment", "PI": "Payer Initiated", "PR": "Patient Responsibility", "CR": "Correction/Reversal"}.get(group_code, group_code),
                    "reason_code":        reason,
                    "reason_description": ADJ_REASON_CODES.get(reason, f"Code {reason}"),
                    "adjustment_amount":  amount,
                    "adjustment_quantity":quantity,
                })

        return adjustments


# =============================================================================
# 277 / MO4 CLAIM STATUS / ACKNOWLEDGMENT PARSER
# =============================================================================

class X12_277Parser(BaseX12Parser):
    """
    Parser for X12 277 Healthcare Claim Status Response (MO4 / 277CA).
    """

    def parse(self, raw: str) -> X12ParseResult:
        """Parse a 277/277CA transaction."""
        try:
            self._segments = self._split_segments(raw)

            envelope = self._parse_envelope(self._segments)
            summary  = self._parse_277_body(self._segments)

            tx_type = "277CA (MO4)"
            return X12ParseResult(
                success=True,
                transaction_type=tx_type,
                raw_segments=self._segments,
                envelope=envelope,
                summary=summary,
            )

        except Exception as e:
            return X12ParseResult(False, "277", errors=[f"Parse error: {str(e)}"])

    def _parse_277_body(self, raw_segs: list) -> dict:
        segs = [self._parse_segment(s) for s in raw_segs]
        summary = {}

        # ── Sender / Receiver ─────────────────────────────────────────────────
        for s in segs:
            if s["id"] == "NM1" and self._elem(s, 1) == "40":
                summary["receiver"] = self._parse_nm1(s)
            if s["id"] == "NM1" and self._elem(s, 1) == "41":
                summary["submitter"] = self._parse_nm1(s)

        # ── Claim status entries ──────────────────────────────────────────────
        claim_statuses = self._parse_claim_status_loops(segs)  # segs already parsed
        summary["claim_statuses"] = claim_statuses
        summary["claim_count"]    = len(claim_statuses)

        # Status summary
        by_status = {}
        for cs in claim_statuses:
            sc = cs.get("status_category_code", "UNKNOWN")
            by_status[sc] = by_status.get(sc, 0) + 1

        summary["status_summary"] = {
            sc: {"count": cnt, "description": STATUS_CATEGORY.get(sc, sc)}
            for sc, cnt in by_status.items()
        }

        return summary

    def _parse_claim_status_loops(self, segs: list) -> list:
        """Parse STC/TRN/REF/NM1 loops for individual claim statuses."""
        claims = []
        n  = len(segs)
        i  = 0

        current_claim = None
        payer = {}
        provider = {}
        patient  = {}

        while i < n:
            s   = segs[i]
            sid = s["id"]

            # ── Payer ─────────────────────────────────────────────────────────
            if sid == "NM1" and self._elem(s, 1) == "PR":
                payer = self._parse_nm1(s)

            # ── Provider ─────────────────────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) in ("1P", "85"):
                provider = self._parse_nm1(s)

            # ── Patient ────────────────────────────────────────────────────────
            elif sid == "NM1" and self._elem(s, 1) == "QC":
                patient = self._parse_nm1(s)

            # ── Trace (TRN) - identifies the specific claim ───────────────────
            elif sid == "TRN":
                current_claim = {
                    "trace_type":               self._elem(s, 1),
                    "claim_trace_number":       self._elem(s, 2),
                    "originating_company_id":   self._elem(s, 3),
                    "reference_id":             self._elem(s, 4),
                    "payer":                    payer,
                    "provider":                 provider,
                    "patient":                  patient,
                    "statuses":                 [],
                    "references":               [],
                    "dates":                    {},
                }
                claims.append(current_claim)

            # ── Status (STC) ──────────────────────────────────────────────────
            elif sid == "STC" and current_claim is not None:
                status_composite  = self._elem(s, 1)
                category_code     = self._comp(status_composite, 0)
                status_code       = self._comp(status_composite, 1)
                entity_code       = self._comp(status_composite, 2)

                current_claim["statuses"].append({
                    "status_category_code":   category_code,
                    "status_category":        STATUS_CATEGORY.get(category_code, category_code),
                    "status_code":            status_code,
                    "entity_code":            entity_code,
                    "entity_name":            ENTITY_CODES.get(entity_code, entity_code),
                    "date":                   self._date(self._elem(s, 2)),
                    "action_code":            self._elem(s, 3),
                    "monetary_amount":        self._money(self._elem(s, 4)),
                    "submission_count":       self._elem(s, 7),
                    "status_information_date":self._date(self._elem(s, 8)),
                    "additional_category_code": self._comp(self._elem(s, 9), 0),
                })

                # Set primary status on claim
                if not current_claim.get("primary_status"):
                    current_claim["primary_status"]      = STATUS_CATEGORY.get(category_code, category_code)
                    current_claim["status_category_code"] = category_code
                    current_claim["status_date"]          = self._date(self._elem(s, 2))
                    current_claim["billed_amount"]        = self._money(self._elem(s, 4))

            # ── Reference (REF) ───────────────────────────────────────────────
            elif sid == "REF" and current_claim is not None:
                ref = self._parse_ref(s)
                current_claim["references"].append(ref)
                if ref["qualifier"] == "1K":
                    current_claim["payer_claim_control_number"] = ref["value"]
                elif ref["qualifier"] == "D9":
                    current_claim["claim_adjustment_identifier"] = ref["value"]
                elif ref["qualifier"] == "EJ":
                    current_claim["patient_account_number"] = ref["value"]
                elif ref["qualifier"] == "BLT":
                    current_claim["billing_type"] = ref["value"]

            # ── DTP ───────────────────────────────────────────────────────────
            elif sid == "DTP" and current_claim is not None:
                dtp = self._parse_dtp(s)
                label = {
                    "472": "service_date",
                    "232": "claim_period_start",
                    "233": "claim_period_end",
                    "050": "received_date",
                }.get(dtp["qualifier"], f"date_{dtp['qualifier']}")
                current_claim["dates"][label] = dtp

            i += 1

        return claims


# =============================================================================
# UNIFIED X12 PARSER
# =============================================================================

class X12Parser:
    """
    Unified parser that auto-detects the X12 transaction type and
    routes to the appropriate sub-parser.

    Handles: 837P, 837I, 837D, 835, 277/277CA (MO4)
    """

    def __init__(self):
        self._837 = X12_837Parser()
        self._835 = X12_835Parser()
        self._277 = X12_277Parser()

    def parse(self, raw: str) -> X12ParseResult:
        """Auto-detect transaction type and parse."""
        tx_type = self._detect_type(raw)
        return self._route(raw, tx_type)

    def parse_837p(self, raw: str) -> X12ParseResult:
        return self._837.parse(raw, "837P")

    def parse_837i(self, raw: str) -> X12ParseResult:
        return self._837.parse(raw, "837I")

    def parse_837d(self, raw: str) -> X12ParseResult:
        return self._837.parse(raw, "837D")

    def parse_835(self, raw: str) -> X12ParseResult:
        return self._835.parse(raw)

    def parse_277(self, raw: str) -> X12ParseResult:
        return self._277.parse(raw)

    def parse_mo4(self, raw: str) -> X12ParseResult:
        """Alias for 277CA (MO4)."""
        return self._277.parse(raw)

    def _detect_type(self, raw: str) -> str:
        base = BaseX12Parser()
        segs = base._split_segments(raw)
        return base._detect_transaction_type(segs)

    def _route(self, raw: str, tx_type: str) -> X12ParseResult:
        if tx_type == "835":
            return self._835.parse(raw)
        if tx_type in ("277", "277CA"):
            return self._277.parse(raw)
        return self._837.parse(raw, tx_type)


# =============================================================================
# SAMPLE X12 TRANSACTIONS
# =============================================================================

# ── 837P Professional Claim ───────────────────────────────────────────────────
SAMPLE_837P = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *240315*1430*^*00501*000000001*0*P*:~"
    "GS*HP*SENDER*RECEIVER*20240315*1430*1*X*005010X222A1~"
    "ST*837*0001*005010X222A1~"
    "BHT*0019*00*BATCH001*20240315*1430*CH~"
    "NM1*41*2*MEMORIAL MEDICAL GROUP*****46*1234567890~"
    "PER*IC*EDI DEPT*TE*3125551234~"
    "NM1*40*2*BCBS ILLINOIS*****46*9876543210~"
    "HL*1**20*1~"
    "NM1*85*2*MEMORIAL MEDICAL GROUP*****XX*1234567890~"
    "N3*123 PROVIDER BLVD~"
    "N4*CHICAGO*IL*60601~"
    "REF*EI*362738191~"
    "HL*2*1*22*0~"
    "SBR*P*18*GROUP123**CH***CI~"
    "NM1*IL*1*SMITH*JOHN*WILLIAM**JR*MI*MEM12345678~"
    "N3*123 MAIN ST APT 4B~"
    "N4*CHICAGO*IL*60601~"
    "DMG*D8*19850322*M~"
    "NM1*PR*2*BCBS ILLINOIS*****PI*BCBSIL01~"
    "CLM*CLAIM001*1250.00***11:B:1*Y*A*Y*I~"
    "DTP*431*D8*20240310~"
    "DTP*472*D8*20240315~"
    "REF*G1*AUTH789012~"
    "HI*ABK:I21.9*ABF:I10*ABF:E78.5~"
    "NM1*82*1*JOHNSON*EMILY*M***XX*9876543211~"
    "NM1*DN*1*PATEL*RAJESH****XX*1122334455~"
    "LX*1~"
    "SV1*HC:99213*250.00*UN*1***1:2~"
    "DTP*472*D8*20240315~"
    "LX*2~"
    "SV1*HC:93000*350.00*UN*1***1~"
    "DTP*472*D8*20240315~"
    "LX*3~"
    "SV1*HC:85027:QW*650.00*UN*1***1:2:3~"
    "DTP*472*D8*20240315~"
    "SE*31*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)

# ── 837I Institutional Claim ──────────────────────────────────────────────────
SAMPLE_837I = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *240315*0900*^*00501*000000002*0*P*:~"
    "GS*HC*SENDER*RECEIVER*20240315*0900*2*X*005010X223A2~"
    "ST*837*0001*005010X223A2~"
    "BHT*0019*00*BATCH002*20240315*0900*CH~"
    "NM1*41*2*MEMORIAL HOSPITAL*****46*9876543210~"
    "NM1*40*2*MEDICARE*****46*1234567890~"
    "HL*1**20*1~"
    "NM1*85*2*MEMORIAL HOSPITAL*****XX*1234567890~"
    "N3*1002 HEALTHCARE DR~"
    "N4*PORTLAND*OR*97005~"
    "REF*EI*910456789~"
    "HL*2*1*22*0~"
    "SBR*P*18*MCARE001**MC***MC~"
    "NM1*IL*1*BROWN*PATRICIA*ANN***MI*1EG4-TE5-MK72~"
    "N3*456 OAK AVENUE~"
    "N4*PORTLAND*OR*97201~"
    "DMG*D8*19450715*F~"
    "NM1*PR*2*MEDICARE*****PI*MCARE~"
    "CLM*CLAIM002*18750.00***11:B:1*Y*A*Y*I~"
    "DTP*435*D8*20240310~"
    "DTP*096*D8*20240315~"
    "CL1*1*9*0~"
    "HI*ABK:I50.9*ABF:I10*ABF:N18.3*ABF:E11.9~"
    "HI*BG:A3*BH:01*BH:02~"
    "NM1*71*1*CHEN*ROBERT*M***XX*2233445566~"
    "NM1*72*1*GARCIA*MARIA****XX*3344556677~"
    "LX*1~"
    "SV2*0450*HC:99291*5000.00*UN*2~"
    "DTP*472*RD8*20240310-20240312~"
    "LX*2~"
    "SV2*0270*HC:85025**UN*3~"
    "SV2*0270**3750.00*UN*3~"
    "DTP*472*RD8*20240310-20240315~"
    "LX*3~"
    "SV2*0730*HC:93005*10000.00*UN*1~"
    "DTP*472*D8*20240311~"
    "SE*35*0001~"
    "GE*1*2~"
    "IEA*1*000000002~"
)

# ── 837D Dental Claim ─────────────────────────────────────────────────────────
SAMPLE_837D = (
    "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *240315*1100*^*00501*000000003*0*P*:~"
    "GS*HD*SENDER*RECEIVER*20240315*1100*3*X*005010X224A2~"
    "ST*837*0001*005010X224A2~"
    "BHT*0019*00*BATCH003*20240315*1100*CH~"
    "NM1*41*2*BRIGHT SMILE DENTAL*****46*5544332211~"
    "NM1*40*2*DELTA DENTAL*****46*1122334455~"
    "HL*1**20*1~"
    "NM1*85*2*BRIGHT SMILE DENTAL*****XX*5544332211~"
    "N3*789 DENTAL WAY~"
    "N4*SEATTLE*WA*98101~"
    "REF*EI*455667788~"
    "HL*2*1*22*0~"
    "SBR*P*18*DELT001**CH***CI~"
    "NM1*IL*1*JONES*ROBERT*ALAN***MI*DDIL987654~"
    "N3*789 ELM STREET~"
    "N4*SEATTLE*WA*98102~"
    "DMG*D8*19780905*M~"
    "NM1*PR*2*DELTA DENTAL*****PI*DDIL~"
    "CLM*CLAIM003*2340.00***11:B:1*Y*A*Y*I~"
    "DTP*472*D8*20240315~"
    "HI*ABK:K02.9*ABF:K05.1~"
    "NM1*82*1*PARKER*SARAH*J***XX*6677889900~"
    "LX*1~"
    "SV3*HC:D0150*150.00*1***~"
    "DTP*472*D8*20240315~"
    "TOO*JP*14~"
    "LX*2~"
    "SV3*HC:D1110*190.00*1***~"
    "DTP*472*D8*20240315~"
    "LX*3~"
    "SV3*HC:D2740*2000.00*1***~"
    "TOO*JP*14~"
    "DTP*472*D8*20240315~"
    "SE*28*0001~"
    "GE*1*3~"
    "IEA*1*000000003~"
)

# ── 835 Remittance Advice ─────────────────────────────────────────────────────
SAMPLE_835 = (
    "ISA*00*          *00*          *ZZ*BCBSIL         *ZZ*MEMHOSP        *240316*0800*^*00501*000000004*0*P*:~"
    "GS*HB*BCBSIL*MEMHOSP*20240316*0800*4*X*005010X221A1~"
    "ST*835*0001*005010X221A1~"
    "BPR*I*1587.50*C*ACH*CCP**01*021000021*DA*1234567890**01*071000013*DA*9876543210*20240316~"
    "TRN*1*835CTRL001*1234567890~"
    "DTM*405*20240316~"
    "N1*PR*BCBS ILLINOIS*XV*BCBSIL01~"
    "N3*300 E RANDOLPH ST~"
    "N4*CHICAGO*IL*60601~"
    "N1*PE*MEMORIAL MEDICAL GROUP*XX*1234567890~"
    "N3*123 PROVIDER BLVD~"
    "N4*CHICAGO*IL*60601~"
    "REF*TJ*362738191~"
    "LX*1~"
    "CLP*CLAIM001*1*1250.00*1037.50*62.50*12*BCBS-CLM-20240316-001*11*1~"
    "CAS*CO*45*212.50~"
    "NM1*QC*1*SMITH*JOHN*WILLIAM**JR*MI*MEM12345678~"
    "NM1*IL*1*SMITH*JOHN*WILLIAM**JR*MI*MEM12345678~"
    "NM1*82*1*JOHNSON*EMILY*M***XX*9876543211~"
    "DTM*232*20240315~"
    "DTM*233*20240315~"
    "AMT*AU*1100.00~"
    "AMT*B6*1100.00~"
    "SVC*HC:99213*250.00*207.50**1~"
    "DTM*472*20240315~"
    "CAS*CO*45*42.50~"
    "AMT*B6*250.00~"
    "SVC*HC:93000*350.00*290.00**1~"
    "DTM*472*20240315~"
    "CAS*CO*45*60.00~"
    "AMT*B6*350.00~"
    "SVC*HC:85027*650.00*540.00**1~"
    "DTM*472*20240315~"
    "CAS*CO*45*110.00~"
    "CAS*PR*3*62.50~"
    "AMT*B6*602.50~"
    "LX*2~"
    "CLP*CLAIM002*4*875.00*0.00*0.00*12*BCBS-CLM-20240316-002*11*1~"
    "CAS*CO*29*875.00~"
    "NM1*QC*1*DAVIS*MICHAEL*JOHN***MI*BCB55566677~"
    "NM1*IL*1*DAVIS*MICHAEL*JOHN***MI*BCB55566677~"
    "DTM*232*20240310~"
    "DTM*233*20240310~"
    "SVC*HC:99214*875.00*0.00**1~"
    "DTM*472*20240310~"
    "CAS*CO*29*875.00~"
    "LQ*HE*M20~"
    "SE*44*0001~"
    "GE*1*4~"
    "IEA*1*000000004~"
)

# ── 277CA / MO4 Claim Acknowledgment ─────────────────────────────────────────
SAMPLE_277 = (
    "ISA*00*          *00*          *ZZ*BCBSIL         *ZZ*MEMHOSP        *240315*1500*^*00501*000000005*0*P*:~"
    "GS*HN*BCBSIL*MEMHOSP*20240315*1500*5*X*005010X214~"
    "ST*277*0001*005010X214~"
    "BHT*0085*08*277CTRL001*20240315*1500~"
    "HL*1**20*1~"
    "NM1*PR*2*BCBS ILLINOIS*****PI*BCBSIL01~"
    "HL*2*1*21*1~"
    "NM1*41*2*MEMORIAL MEDICAL GROUP*****46*1234567890~"
    "HL*3*2*19*1~"
    "NM1*1P*2*MEMORIAL MEDICAL GROUP*****XX*1234567890~"
    "HL*4*3*22*0~"
    "NM1*IL*1*SMITH*JOHN*WILLIAM***MI*MEM12345678~"
    "TRN*2*CLAIM001*1234567890~"
    "STC*A1:20:QC*20240315*U*1250.00~"
    "REF*EJ*CLAIM001~"
    "REF*1K*BCBS-277-20240315-001~"
    "DTP*472*D8*20240315~"
    "HL*5*3*22*0~"
    "NM1*IL*1*JONES*ROBERT*ALAN***MI*DDIL987654~"
    "TRN*2*CLAIM003*1234567890~"
    "STC*F1:1:PR*20240315*WQ*2340.00~"
    "REF*EJ*CLAIM003~"
    "REF*1K*BCBS-277-20240315-002~"
    "DTP*472*D8*20240315~"
    "HL*6*3*22*0~"
    "NM1*IL*1*BROWN*PATRICIA*ANN***MI*1EG4-TE5-MK72~"
    "TRN*2*CLAIM002*1234567890~"
    "STC*F2:97:IL*20240315*WQ*18750.00~"
    "REF*EJ*CLAIM002~"
    "REF*1K*BCBS-277-20240315-003~"
    "DTP*472*D8*20240315~"
    "SE*30*0001~"
    "GE*1*5~"
    "IEA*1*000000005~"
)


# =============================================================================
# DEMO
# =============================================================================

def _money_str(val) -> str:
    if val is None:
        return "N/A"
    return f"${val:,.2f}"

def demo():
    parser = X12Parser()
    SEP = "=" * 72

    print(SEP)
    print("  X12 EDI HEALTHCARE PARSERS  -  DEMO")
    print("  Covers: 837P · 837I · 837D · 835 · 277CA (MO4)")
    print(SEP)

    # ─────────────────────────────────────────────────────────────────────────
    # 837P  Professional Claim
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  837P  -  Professional Claim  (Physician / Outpatient)")
    print(f"{'─'*72}")

    r837p = parser.parse_837p(SAMPLE_837P)
    print(f"  Success         : {r837p.success}")
    print(f"  Transaction Type: {r837p.transaction_type}")

    env = r837p.envelope
    print(f"  Sender          : {env.get('interchange', {}).get('sender_id', '').strip()}")
    print(f"  Receiver        : {env.get('interchange', {}).get('receiver_id', '').strip()}")
    print(f"  Production?     : {env.get('interchange', {}).get('usage_indicator') == 'P'}")

    for claim in r837p.get_claims():
        sub  = claim.get("subscriber", {})
        prov = claim.get("billing_provider", {})
        rend = claim.get("rendering_provider", {})
        ref  = claim.get("referring_provider", {})
        print(f"\n  CLAIM ID        : {claim.get('claim_id')}")
        print(f"  Total Billed    : {_money_str(claim.get('total_billed_amount'))}")
        print(f"  Place of Service: {claim.get('place_of_service')} - {claim.get('place_of_service_name')}")
        print(f"  Frequency       : {claim.get('claim_frequency')} - {claim.get('claim_frequency_name')}")
        print(f"  Billing Provider: {prov.get('full_name')} NPI:{prov.get('id_code')}")
        print(f"  Rendering Prov  : {rend.get('full_name')} NPI:{rend.get('id_code')}")
        print(f"  Referring Prov  : {ref.get('full_name')} NPI:{ref.get('id_code')}")
        print(f"  Subscriber      : {sub.get('full_name')} MID:{sub.get('id_code')} DOB:{sub.get('dob')}")
        print(f"  Prior Auth      : {claim.get('prior_auth_number', 'N/A')}")

        print(f"\n  DIAGNOSES")
        for dx in claim.get("diagnoses", []):
            print(f"    [{dx.get('qualifier')}] {dx.get('code')}")

        print(f"\n  SERVICE LINES ({claim.get('service_line_count')})")
        for i, svc in enumerate(claim.get("service_lines", []), 1):
            mods = " ".join(filter(None, [svc.get("modifier_1"), svc.get("modifier_2"), svc.get("modifier_3")]))
            print(f"    {i}. CPT {svc.get('procedure_code'):<8} {_money_str(svc.get('charge_amount')):<12}"
                  f"  Qty:{svc.get('quantity','1'):<4}  Mods:{mods or 'None':<10}"
                  f"  POS:{svc.get('place_of_service')}")

    # ─────────────────────────────────────────────────────────────────────────
    # 837I  Institutional Claim
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  837I  -  Institutional Claim  (Hospital / Inpatient)")
    print(f"{'─'*72}")

    r837i = parser.parse_837i(SAMPLE_837I)
    print(f"  Success         : {r837i.success}")
    print(f"  Transaction Type: {r837i.transaction_type}")

    for claim in r837i.get_claims():
        sub  = claim.get("subscriber", {})
        att  = claim.get("attending_provider", {})
        op   = claim.get("operating_provider", {})
        print(f"\n  CLAIM ID        : {claim.get('claim_id')}")
        print(f"  Total Billed    : {_money_str(claim.get('total_billed_amount'))}")
        print(f"  Subscriber      : {sub.get('full_name')} DOB:{sub.get('dob')} Gender:{sub.get('gender')}")
        print(f"  Attending Prov  : {att.get('full_name')} NPI:{att.get('id_code')}")
        print(f"  Operating Prov  : {op.get('full_name')} NPI:{op.get('id_code')}")

        print(f"\n  DIAGNOSES (ICD-10)")
        for dx in claim.get("diagnoses", []):
            print(f"    [{dx.get('qualifier')}] {dx.get('code')}")

        print(f"\n  REVENUE LINES ({claim.get('service_line_count')})")
        for i, svc in enumerate(claim.get("service_lines", []), 1):
            print(f"    {i}. Rev:{svc.get('revenue_code','----')}  "
                  f"CPT:{svc.get('procedure_code','----'):<8}  "
                  f"{_money_str(svc.get('charge_amount')):<12}  "
                  f"Qty:{svc.get('quantity','1')}")

    # ─────────────────────────────────────────────────────────────────────────
    # 837D  Dental Claim
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  837D  -  Dental Claim")
    print(f"{'─'*72}")

    r837d = parser.parse_837d(SAMPLE_837D)
    print(f"  Success         : {r837d.success}")
    print(f"  Transaction Type: {r837d.transaction_type}")

    for claim in r837d.get_claims():
        sub = claim.get("subscriber", {})
        print(f"\n  CLAIM ID        : {claim.get('claim_id')}")
        print(f"  Total Billed    : {_money_str(claim.get('total_billed_amount'))}")
        print(f"  Patient         : {sub.get('full_name')} DOB:{sub.get('dob')}")

        print(f"\n  DIAGNOSES")
        for dx in claim.get("diagnoses", []):
            print(f"    [{dx.get('qualifier')}] {dx.get('code')}")

        print(f"\n  DENTAL PROCEDURE LINES ({claim.get('service_line_count')})")
        for i, svc in enumerate(claim.get("service_lines", []), 1):
            print(f"    {i}. CDT {svc.get('procedure_code'):<8} {_money_str(svc.get('charge_amount')):<12}"
                  f"  Tooth:{svc.get('tooth_code') or 'N/A':<6}"
                  f"  Surfaces:{','.join(svc.get('tooth_surface', [])) or 'N/A'}")

    # ─────────────────────────────────────────────────────────────────────────
    # 835  Remittance Advice
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  835  -  Healthcare Payment / Remittance Advice")
    print(f"{'─'*72}")

    r835 = parser.parse_835(SAMPLE_835)
    print(f"  Success         : {r835.success}")
    print(f"  Transaction Type: {r835.transaction_type}")

    pay  = r835.summary.get("payment", {})
    payer= r835.summary.get("payer", {})
    payee= r835.summary.get("payee", {})
    fin  = r835.get_financial_summary()
    trn  = r835.summary.get("trace", {})

    print(f"\n  PAYMENT INFO")
    print(f"    Payer           : {payer.get('full_name')}")
    print(f"    Payee           : {payee.get('full_name')}")
    print(f"    Check/EFT Amount: {_money_str(pay.get('total_payment_amount'))}")
    print(f"    Payment Method  : {pay.get('payment_method')}")
    print(f"    Payment Date    : {pay.get('payment_date')}")
    print(f"    Check/Trace #   : {trn.get('reference_number')}")

    print(f"\n  FINANCIAL SUMMARY")
    print(f"    Total Claims    : {fin.get('total_claims')}")
    print(f"    Total Charged   : {_money_str(fin.get('total_charged'))}")
    print(f"    Total Paid      : {_money_str(fin.get('total_paid'))}")
    print(f"    Total Adjustments: {_money_str(fin.get('total_adjustments'))}")

    print(f"\n  CLAIM PAYMENTS")
    for cp in r835.get_payments():
        patient = cp.get("patient", {})
        print(f"\n    Claim#  : {cp.get('patient_control_number')}")
        print(f"    Status  : {cp.get('claim_status')}")
        print(f"    Patient : {patient.get('full_name')} ID:{patient.get('id_code')}")
        print(f"    Charged : {_money_str(cp.get('charged_amount'))}")
        print(f"    Paid    : {_money_str(cp.get('paid_amount'))}")
        print(f"    Pt Resp : {_money_str(cp.get('patient_responsibility'))}")

        if cp.get("adjustments"):
            print(f"    ADJUSTMENTS:")
            for adj in cp["adjustments"]:
                print(f"      [{adj.get('group_code')}] Reason {adj.get('reason_code')}: "
                      f"{adj.get('reason_description')[:55]}  {_money_str(adj.get('adjustment_amount'))}")

        if cp.get("service_payments"):
            print(f"    SERVICE LINES ({cp.get('service_line_count')}):")
            for svc in cp["service_payments"]:
                svc_adjs = svc.get("adjustments", [])
                adj_str = " | ".join(
                    f"[{a.get('group_code')}] {a.get('reason_code')}: {_money_str(a.get('adjustment_amount'))}"
                    for a in svc_adjs
                )
                print(f"      CPT {svc.get('procedure_code'):<8}  "
                      f"Charged:{_money_str(svc.get('charged_amount')):<12}  "
                      f"Paid:{_money_str(svc.get('paid_amount')):<12}  "
                      f"Adj: {adj_str or 'None'}")

    # ─────────────────────────────────────────────────────────────────────────
    # 277CA / MO4  Claim Acknowledgment
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("  277CA / MO4  -  Claim Acknowledgment / Status Response")
    print(f"{'─'*72}")

    r277 = parser.parse_mo4(SAMPLE_277)
    print(f"  Success         : {r277.success}")
    print(f"  Transaction Type: {r277.transaction_type}")

    stat_summary = r277.summary.get("status_summary", {})
    print(f"\n  STATUS SUMMARY")
    for code, info in stat_summary.items():
        print(f"    [{code}] {info.get('description'):<55}  Count: {info.get('count')}")

    print(f"\n  INDIVIDUAL CLAIM STATUSES")
    for cs in r277.summary.get("claim_statuses", []):
        patient = cs.get("patient", {})
        print(f"\n    Trace # : {cs.get('claim_trace_number')}")
        print(f"    Patient : {patient.get('full_name')} ID:{patient.get('id_code')}")
        print(f"    Status  : {cs.get('primary_status')}")
        print(f"    Date    : {cs.get('status_date')}")
        print(f"    Billed  : {_money_str(cs.get('billed_amount'))}")
        if cs.get("payer_claim_control_number"):
            print(f"    Payer # : {cs.get('payer_claim_control_number')}")
        for stc in cs.get("statuses", []):
            print(f"    STC     : [{stc.get('status_category_code')}:{stc.get('status_code')}] "
                  f"{stc.get('status_category')}")

    # JSON output
    print(f"\n{'─'*72}")
    print("  JSON OUTPUT SAMPLE  (837P claim summary)")
    print(f"{'─'*72}")
    print(json.dumps(r837p.summary, indent=2, default=str)[:2000] + "\n  ... (truncated)")

    print(f"\n{SEP}")
    print("  Done. Import X12Parser in your own code to use.")
    print(f"  from x12_parser import X12Parser")
    print(SEP)


if __name__ == "__main__":
    demo()
