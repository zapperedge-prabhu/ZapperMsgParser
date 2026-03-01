"""
╔══════════════════════════════════════════════════════════════════════╗
║              FHIR R4 RESOURCE PARSER  —  Standalone                 ║
║                                                                      ║
║  Supports  : FHIR R4 (4.0.1)                                         ║
║  Resources : Patient · Observation · Encounter · DiagnosticReport   ║
║              MedicationRequest · Condition · Bundle · Practitioner  ║
║              Organization · Coverage                                 ║
║  Requires  : Python 3.9+  —  zero external dependencies              ║
╚══════════════════════════════════════════════════════════════════════╝

QUICK START:
    from fhir_parser import FHIRParser

    parser = FHIRParser()
    result = parser.parse(fhir_json_string)   # or pass a dict
    result = parser.parse(fhir_dict)

    print(result.success)          # True / False
    print(result.resource_type)    # e.g. "Patient"
    print(result.summary)          # clean clinical dict
    print(result.to_json())        # full JSON output

Run as script for built-in demo:
    python fhir_parser.py
"""

import json
from typing import Any, Optional
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# RESULT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FHIRParseResult:
    success: bool
    resource_type: str
    raw_data: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps({
            "success":       self.success,
            "resource_type": self.resource_type,
            "summary":       self.summary,
            "raw_data":      self.raw_data,
            "errors":        self.errors,
            "warnings":      self.warnings,
        }, indent=indent, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PARSER
# ─────────────────────────────────────────────────────────────────────────────

class FHIRParser:
    """
    Parses FHIR R4 JSON resources.

    Usage:
        parser = FHIRParser()
        result = parser.parse(json_string_or_dict)
    """

    SUPPORTED = [
        "Patient", "Observation", "Encounter", "DiagnosticReport",
        "MedicationRequest", "Condition", "Bundle", "Practitioner",
        "Organization", "Coverage", "AllergyIntolerance",
        "Procedure", "Immunization",
    ]

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self, fhir_input: Any) -> FHIRParseResult:
        """
        Parse a FHIR R4 resource.

        Args:
            fhir_input:  JSON string or Python dict

        Returns:
            FHIRParseResult
        """
        try:
            data = json.loads(fhir_input) if isinstance(fhir_input, str) else fhir_input

            if not isinstance(data, dict):
                return FHIRParseResult(False, "UNKNOWN", errors=["Input must be a JSON object / dict"])

            resource_type = data.get("resourceType")
            if not resource_type:
                return FHIRParseResult(False, "UNKNOWN", errors=["Missing 'resourceType' field"])

            parsers = {
                "Patient":            self._parse_patient,
                "Observation":        self._parse_observation,
                "Encounter":          self._parse_encounter,
                "DiagnosticReport":   self._parse_diagnostic_report,
                "MedicationRequest":  self._parse_medication_request,
                "Condition":          self._parse_condition,
                "Bundle":             self._parse_bundle,
                "Practitioner":       self._parse_practitioner,
                "Organization":       self._parse_organization,
                "Coverage":           self._parse_coverage,
                "AllergyIntolerance": self._parse_allergy,
                "Procedure":          self._parse_procedure,
                "Immunization":       self._parse_immunization,
            }

            fn = parsers.get(resource_type)
            if fn:
                summary = fn(data)
            else:
                summary = {
                    "note": f"Resource '{resource_type}' not specifically handled. Raw data available.",
                    "id":   data.get("id", ""),
                }

            warnings = []
            if resource_type not in self.SUPPORTED:
                warnings.append(f"Resource type '{resource_type}' has generic handling only")

            return FHIRParseResult(
                success=True,
                resource_type=resource_type,
                raw_data=data,
                summary=summary,
                warnings=warnings,
            )

        except json.JSONDecodeError as e:
            return FHIRParseResult(False, "UNKNOWN", errors=[f"Invalid JSON: {str(e)}"])
        except Exception as e:
            return FHIRParseResult(False, "UNKNOWN", errors=[f"Parse error: {str(e)}"])

    def parse_batch(self, items: list) -> list:
        """Parse a list of FHIR resources, return list of FHIRParseResult."""
        return [self.parse(item) for item in items]

    # ── Generic helpers ───────────────────────────────────────────────────────

    def _get(self, data: dict, *keys, default="") -> Any:
        """Safely traverse nested keys."""
        cur = data
        for key in keys:
            if isinstance(cur, dict):
                cur = cur.get(key, {} if key != keys[-1] else default)
            elif isinstance(cur, list) and isinstance(key, int):
                cur = cur[key] if key < len(cur) else default
            else:
                return default
        return cur if cur != {} else default

    def _coding(self, coding_list) -> dict:
        """Extract first coding from a list."""
        if not coding_list:
            return {}
        item = coding_list[0] if isinstance(coding_list, list) else coding_list
        return {
            "system":  item.get("system", ""),
            "code":    item.get("code", ""),
            "display": item.get("display", ""),
            "version": item.get("version", ""),
        }

    def _cc(self, cc: dict) -> dict:
        """Extract a CodeableConcept."""
        if not cc:
            return {}
        return {
            "text":   cc.get("text", ""),
            "coding": self._coding(cc.get("coding", [])),
        }

    def _ref(self, ref: dict) -> dict:
        """Extract a Reference."""
        if not ref:
            return {}
        return {
            "reference": ref.get("reference", ""),
            "display":   ref.get("display", ""),
            "type":      ref.get("type", ""),
            "id":        ref.get("reference", "").split("/")[-1] if "/" in ref.get("reference", "") else "",
        }

    def _name(self, name_list: list) -> dict:
        """Extract the best name from a HumanName list."""
        if not name_list:
            return {}
        name = next((n for n in name_list if n.get("use") == "official"), name_list[0])
        given = name.get("given", [])
        return {
            "full":   f"{' '.join(given)} {name.get('family', '')}".strip(),
            "family": name.get("family", ""),
            "given":  " ".join(given),
            "prefix": " ".join(name.get("prefix", [])),
            "suffix": " ".join(name.get("suffix", [])),
            "use":    name.get("use", ""),
            "text":   name.get("text", ""),
        }

    def _address(self, addr_list: list) -> dict:
        """Extract first address."""
        if not addr_list:
            return {}
        addr = addr_list[0]
        return {
            "use":         addr.get("use", ""),
            "type":        addr.get("type", ""),
            "text":        addr.get("text", ""),
            "line":        addr.get("line", []),
            "city":        addr.get("city", ""),
            "district":    addr.get("district", ""),
            "state":       addr.get("state", ""),
            "postal_code": addr.get("postalCode", ""),
            "country":     addr.get("country", ""),
        }

    def _telecom(self, telecom_list: list) -> dict:
        """Extract phone, email, fax from telecom list."""
        result = {}
        for t in (telecom_list or []):
            sys = t.get("system", "")
            val = t.get("value", "")
            if sys and sys not in result:
                result[sys] = val
        return result

    def _identifier(self, id_list: list, system_hint: str = None) -> str:
        """Find identifier value, optionally filtered by system."""
        for ident in (id_list or []):
            if system_hint and system_hint.lower() not in ident.get("system", "").lower():
                continue
            return ident.get("value", "")
        return ""

    def _all_identifiers(self, id_list: list) -> list:
        """Return all identifiers as list of dicts."""
        result = []
        for ident in (id_list or []):
            result.append({
                "system":  ident.get("system", ""),
                "value":   ident.get("value", ""),
                "use":     ident.get("use", ""),
                "type":    self._cc(ident.get("type", {})),
            })
        return result

    def _obs_value(self, obs: dict) -> dict:
        """Extract value[x] from an Observation."""
        for field_name, handler in [
            ("valueQuantity",      lambda v: {"type": "Quantity",  "value": v.get("value"), "unit": v.get("unit", v.get("code", "")), "display": f"{v.get('value','')} {v.get('unit', v.get('code',''))}".strip()}),
            ("valueCodeableConcept", lambda v: {"type": "CodeableConcept", **self._cc(v)}),
            ("valueString",        lambda v: {"type": "string",    "value": v,    "display": v}),
            ("valueBoolean",       lambda v: {"type": "boolean",   "value": v,    "display": str(v)}),
            ("valueInteger",       lambda v: {"type": "integer",   "value": v,    "display": str(v)}),
            ("valueDateTime",      lambda v: {"type": "dateTime",  "value": v,    "display": v}),
            ("valueTime",          lambda v: {"type": "time",      "value": v,    "display": v}),
            ("valueRange",         lambda v: {"type": "Range", "low": v.get("low", {}), "high": v.get("high", {})}),
            ("valueRatio",         lambda v: {"type": "Ratio", "numerator": v.get("numerator", {}), "denominator": v.get("denominator", {})}),
            ("valueSampledData",   lambda v: {"type": "SampledData", "raw": v}),
            ("valuePeriod",        lambda v: {"type": "Period", "start": v.get("start"), "end": v.get("end")}),
        ]:
            if field_name in obs:
                return handler(obs[field_name])
        return {}

    def _period(self, period: dict) -> dict:
        if not period:
            return {}
        return {"start": period.get("start", ""), "end": period.get("end", "")}

    def _meta(self, data: dict) -> dict:
        m = data.get("meta", {})
        return {
            "version_id":   m.get("versionId", ""),
            "last_updated": m.get("lastUpdated", ""),
            "source":       m.get("source", ""),
            "profile":      m.get("profile", []),
        }

    # ── Resource parsers ──────────────────────────────────────────────────────

    def _parse_patient(self, data: dict) -> dict:
        ids = self._all_identifiers(data.get("identifier", []))
        return {
            "resource_type":  "Patient",
            "id":             data.get("id", ""),
            "active":         data.get("active", True),
            "name":           self._name(data.get("name", [])),
            "identifiers":    ids,
            "mrn":            self._identifier(data.get("identifier", []), "MR") or (ids[0]["value"] if ids else ""),
            "ssn":            self._identifier(data.get("identifier", []), "SS"),
            "date_of_birth":  data.get("birthDate", ""),
            "gender":         data.get("gender", ""),
            "deceased":       data.get("deceasedBoolean", False) or data.get("deceasedDateTime"),
            "multiple_birth": data.get("multipleBirthBoolean") or data.get("multipleBirthInteger"),
            "address":        self._address(data.get("address", [])),
            "telecom":        self._telecom(data.get("telecom", [])),
            "marital_status": self._cc(data.get("maritalStatus", {})),
            "communication": [
                {
                    "language":  self._cc(c.get("language", {})),
                    "preferred": c.get("preferred", False),
                }
                for c in data.get("communication", [])
            ],
            "general_practitioner": [self._ref(r) for r in data.get("generalPractitioner", [])],
            "managing_organization": self._ref(data.get("managingOrganization", {})),
            "links": [{"other": self._ref(l.get("other", {})), "type": l.get("type", "")} for l in data.get("link", [])],
            "meta": self._meta(data),
        }

    def _parse_observation(self, data: dict) -> dict:
        interps = data.get("interpretation", [])
        interp_codes = [self._coding(i.get("coding", [])).get("code", "") for i in interps]
        is_abnormal  = any(c in ("H", "HH", "L", "LL", "A", "AA", "HU", "LU") for c in interp_codes)

        ref_ranges = []
        for rr in data.get("referenceRange", []):
            low  = rr.get("low", {})
            high = rr.get("high", {})
            ref_ranges.append({
                "low":    f"{low.get('value','')} {low.get('unit','')}".strip()  if low  else "",
                "high":   f"{high.get('value','')} {high.get('unit','')}".strip() if high else "",
                "text":   rr.get("text", ""),
                "type":   self._cc(rr.get("type", {})),
                "applies_to": [self._cc(a) for a in rr.get("appliesTo", [])],
            })

        return {
            "resource_type":    "Observation",
            "id":               data.get("id", ""),
            "status":           data.get("status", ""),
            "category":         [self._cc(c) for c in data.get("category", [])],
            "code":             self._cc(data.get("code", {})),
            "subject":          self._ref(data.get("subject", {})),
            "focus":            [self._ref(f) for f in data.get("focus", [])],
            "encounter":        self._ref(data.get("encounter", {})),
            "effective_datetime": data.get("effectiveDateTime") or self._period(data.get("effectivePeriod", {})).get("start", ""),
            "effective_period": self._period(data.get("effectivePeriod", {})),
            "issued":           data.get("issued", ""),
            "performer":        [self._ref(p) for p in data.get("performer", [])],
            "value":            self._obs_value(data),
            "data_absent_reason": self._cc(data.get("dataAbsentReason", {})),
            "interpretation":   [self._cc(i) for i in interps],
            "is_abnormal":      is_abnormal,
            "note":             [n.get("text", "") for n in data.get("note", [])],
            "body_site":        self._cc(data.get("bodySite", {})),
            "method":           self._cc(data.get("method", {})),
            "specimen":         self._ref(data.get("specimen", {})),
            "reference_range":  ref_ranges,
            "has_member":       [self._ref(m) for m in data.get("hasMember", [])],
            "derived_from":     [self._ref(d) for d in data.get("derivedFrom", [])],
            "components": [
                {
                    "code":           self._cc(c.get("code", {})),
                    "value":          self._obs_value(c),
                    "interpretation": [self._cc(i) for i in c.get("interpretation", [])],
                    "reference_range": [
                        {"low": rr.get("low", {}), "high": rr.get("high", {})}
                        for rr in c.get("referenceRange", [])
                    ],
                }
                for c in data.get("component", [])
            ],
            "meta": self._meta(data),
        }

    def _parse_encounter(self, data: dict) -> dict:
        return {
            "resource_type":    "Encounter",
            "id":               data.get("id", ""),
            "status":           data.get("status", ""),
            "status_history":   [{"status": s.get("status"), "period": self._period(s.get("period", {}))} for s in data.get("statusHistory", [])],
            "class":            self._coding(data.get("class", {})) if isinstance(data.get("class"), dict) else {},
            "type":             [self._cc(t) for t in data.get("type", [])],
            "service_type":     self._cc(data.get("serviceType", {})),
            "priority":         self._cc(data.get("priority", {})),
            "subject":          self._ref(data.get("subject", {})),
            "episode_of_care":  [self._ref(e) for e in data.get("episodeOfCare", [])],
            "based_on":         [self._ref(b) for b in data.get("basedOn", [])],
            "participant": [
                {
                    "type":       [self._cc(t) for t in p.get("type", [])],
                    "period":     self._period(p.get("period", {})),
                    "individual": self._ref(p.get("individual", {})),
                }
                for p in data.get("participant", [])
            ],
            "appointment":  [self._ref(a) for a in data.get("appointment", [])],
            "period":       self._period(data.get("period", {})),
            "length":       data.get("length", {}),
            "reason_code":  [self._cc(r) for r in data.get("reasonCode", [])],
            "reason_reference": [self._ref(r) for r in data.get("reasonReference", [])],
            "diagnosis": [
                {
                    "condition": self._ref(d.get("condition", {})),
                    "use":       self._cc(d.get("use", {})),
                    "rank":      d.get("rank"),
                }
                for d in data.get("diagnosis", [])
            ],
            "account":          [self._ref(a) for a in data.get("account", [])],
            "hospitalization": {
                "pre_admission_identifier": data.get("hospitalization", {}).get("preAdmissionIdentifier", {}),
                "origin":             self._ref(self._get(data, "hospitalization", "origin", default={})),
                "admit_source":       self._cc(self._get(data, "hospitalization", "admitSource", default={})),
                "re_admission":       self._cc(self._get(data, "hospitalization", "reAdmission", default={})),
                "diet_preference":    [self._cc(d) for d in self._get(data, "hospitalization", "dietPreference", default=[])],
                "discharge_disposition": self._cc(self._get(data, "hospitalization", "dischargeDisposition", default={})),
                "destination":        self._ref(self._get(data, "hospitalization", "destination", default={})),
            },
            "location": [
                {
                    "location":      self._ref(l.get("location", {})),
                    "status":        l.get("status", ""),
                    "physical_type": self._cc(l.get("physicalType", {})),
                    "period":        self._period(l.get("period", {})),
                }
                for l in data.get("location", [])
            ],
            "service_provider": self._ref(data.get("serviceProvider", {})),
            "part_of":          self._ref(data.get("partOf", {})),
            "meta": self._meta(data),
        }

    def _parse_diagnostic_report(self, data: dict) -> dict:
        return {
            "resource_type":      "DiagnosticReport",
            "id":                 data.get("id", ""),
            "status":             data.get("status", ""),
            "category":           [self._cc(c) for c in data.get("category", [])],
            "code":               self._cc(data.get("code", {})),
            "subject":            self._ref(data.get("subject", {})),
            "encounter":          self._ref(data.get("encounter", {})),
            "effective_datetime": data.get("effectiveDateTime", ""),
            "effective_period":   self._period(data.get("effectivePeriod", {})),
            "issued":             data.get("issued", ""),
            "performer":          [self._ref(p) for p in data.get("performer", [])],
            "results_interpreter":[self._ref(r) for r in data.get("resultsInterpreter", [])],
            "specimen":           [self._ref(s) for s in data.get("specimen", [])],
            "result":             [self._ref(r) for r in data.get("result", [])],
            "imaging_study":      [self._ref(i) for i in data.get("imagingStudy", [])],
            "media": [
                {"comment": m.get("comment", ""), "link": self._ref(m.get("link", {}))}
                for m in data.get("media", [])
            ],
            "conclusion":         data.get("conclusion", ""),
            "conclusion_code":    [self._cc(c) for c in data.get("conclusionCode", [])],
            "presented_form":     [{"content_type": a.get("contentType"), "url": a.get("url"), "title": a.get("title")} for a in data.get("presentedForm", [])],
            "meta": self._meta(data),
        }

    def _parse_medication_request(self, data: dict) -> dict:
        dosage = []
        for di in data.get("dosageInstruction", []):
            dr = di.get("doseAndRate", [{}])[0] if di.get("doseAndRate") else {}
            dq = dr.get("doseQuantity", {})
            dosage.append({
                "sequence":   di.get("sequence"),
                "text":       di.get("text", ""),
                "additional_instruction": [self._cc(a) for a in di.get("additionalInstruction", [])],
                "patient_instruction": di.get("patientInstruction", ""),
                "timing":     di.get("timing", {}).get("code", {}).get("text", ""),
                "as_needed":  di.get("asNeededBoolean", False),
                "as_needed_for": self._cc(di.get("asNeededCodeableConcept", {})),
                "site":       self._cc(di.get("site", {})),
                "route":      self._cc(di.get("route", {})),
                "method":     self._cc(di.get("method", {})),
                "dose":       f"{dq.get('value','')} {dq.get('unit','')}".strip(),
                "max_dose_per_period": dr.get("maxDosePerPeriod", {}),
            })

        dispense = data.get("dispenseRequest", {})
        return {
            "resource_type":  "MedicationRequest",
            "id":             data.get("id", ""),
            "status":         data.get("status", ""),
            "status_reason":  self._cc(data.get("statusReason", {})),
            "intent":         data.get("intent", ""),
            "category":       [self._cc(c) for c in data.get("category", [])],
            "priority":       data.get("priority", ""),
            "do_not_perform": data.get("doNotPerform", False),
            "medication":     self._cc(data.get("medicationCodeableConcept", {})) or self._ref(data.get("medicationReference", {})),
            "subject":        self._ref(data.get("subject", {})),
            "encounter":      self._ref(data.get("encounter", {})),
            "authored_on":    data.get("authoredOn", ""),
            "requester":      self._ref(data.get("requester", {})),
            "performer":      self._ref(data.get("performer", {})),
            "recorder":       self._ref(data.get("recorder", {})),
            "reason_code":    [self._cc(r) for r in data.get("reasonCode", [])],
            "reason_reference": [self._ref(r) for r in data.get("reasonReference", [])],
            "based_on":       [self._ref(b) for b in data.get("basedOn", [])],
            "dosage_instruction": dosage,
            "dispense_request": {
                "initial_fill":       dispense.get("initialFill", {}),
                "dispense_interval":  dispense.get("dispenseInterval", {}),
                "validity_period":    self._period(dispense.get("validityPeriod", {})),
                "number_of_repeats":  dispense.get("numberOfRepeatsAllowed"),
                "quantity":           dispense.get("quantity", {}),
                "expected_supply":    dispense.get("expectedSupplyDuration", {}),
                "performer":          self._ref(dispense.get("performer", {})),
            },
            "substitution":   data.get("substitution", {}),
            "note":           [n.get("text", "") for n in data.get("note", [])],
            "meta": self._meta(data),
        }

    def _parse_condition(self, data: dict) -> dict:
        return {
            "resource_type":       "Condition",
            "id":                  data.get("id", ""),
            "clinical_status":     self._cc(data.get("clinicalStatus", {})),
            "verification_status": self._cc(data.get("verificationStatus", {})),
            "category":            [self._cc(c) for c in data.get("category", [])],
            "severity":            self._cc(data.get("severity", {})),
            "code":                self._cc(data.get("code", {})),
            "body_site":           [self._cc(b) for b in data.get("bodySite", [])],
            "subject":             self._ref(data.get("subject", {})),
            "encounter":           self._ref(data.get("encounter", {})),
            "onset_datetime":      data.get("onsetDateTime", ""),
            "onset_age":           data.get("onsetAge", {}),
            "onset_period":        self._period(data.get("onsetPeriod", {})),
            "abatement_datetime":  data.get("abatementDateTime", ""),
            "abatement_age":       data.get("abatementAge", {}),
            "recorded_date":       data.get("recordedDate", ""),
            "recorder":            self._ref(data.get("recorder", {})),
            "asserter":            self._ref(data.get("asserter", {})),
            "stage": [
                {
                    "summary":    self._cc(s.get("summary", {})),
                    "assessment": [self._ref(a) for a in s.get("assessment", [])],
                    "type":       self._cc(s.get("type", {})),
                }
                for s in data.get("stage", [])
            ],
            "evidence": [
                {
                    "code":   [self._cc(c) for c in e.get("code", [])],
                    "detail": [self._ref(d) for d in e.get("detail", [])],
                }
                for e in data.get("evidence", [])
            ],
            "note":    [n.get("text", "") for n in data.get("note", [])],
            "meta":    self._meta(data),
        }

    def _parse_allergy(self, data: dict) -> dict:
        return {
            "resource_type":       "AllergyIntolerance",
            "id":                  data.get("id", ""),
            "clinical_status":     self._cc(data.get("clinicalStatus", {})),
            "verification_status": self._cc(data.get("verificationStatus", {})),
            "type":                data.get("type", ""),          # allergy | intolerance
            "category":            data.get("category", []),      # food | medication | environment | biologic
            "criticality":         data.get("criticality", ""),   # low | high | unable-to-assess
            "code":                self._cc(data.get("code", {})),
            "patient":             self._ref(data.get("patient", {})),
            "encounter":           self._ref(data.get("encounter", {})),
            "onset_datetime":      data.get("onsetDateTime", ""),
            "recorded_date":       data.get("recordedDate", ""),
            "recorder":            self._ref(data.get("recorder", {})),
            "asserter":            self._ref(data.get("asserter", {})),
            "last_occurrence":     data.get("lastOccurrence", ""),
            "note":                [n.get("text", "") for n in data.get("note", [])],
            "reaction": [
                {
                    "substance":        self._cc(r.get("substance", {})),
                    "manifestation":    [self._cc(m) for m in r.get("manifestation", [])],
                    "description":      r.get("description", ""),
                    "onset":            r.get("onset", ""),
                    "severity":         r.get("severity", ""),   # mild | moderate | severe
                    "exposure_route":   self._cc(r.get("exposureRoute", {})),
                    "note":             [n.get("text", "") for n in r.get("note", [])],
                }
                for r in data.get("reaction", [])
            ],
            "meta": self._meta(data),
        }

    def _parse_procedure(self, data: dict) -> dict:
        return {
            "resource_type":  "Procedure",
            "id":             data.get("id", ""),
            "status":         data.get("status", ""),
            "status_reason":  self._cc(data.get("statusReason", {})),
            "category":       self._cc(data.get("category", {})),
            "code":           self._cc(data.get("code", {})),
            "subject":        self._ref(data.get("subject", {})),
            "encounter":      self._ref(data.get("encounter", {})),
            "performed_datetime": data.get("performedDateTime", ""),
            "performed_period":   self._period(data.get("performedPeriod", {})),
            "recorder":       self._ref(data.get("recorder", {})),
            "asserter":       self._ref(data.get("asserter", {})),
            "performer": [
                {
                    "function": self._cc(p.get("function", {})),
                    "actor":    self._ref(p.get("actor", {})),
                    "on_behalf_of": self._ref(p.get("onBehalfOf", {})),
                }
                for p in data.get("performer", [])
            ],
            "location":       self._ref(data.get("location", {})),
            "reason_code":    [self._cc(r) for r in data.get("reasonCode", [])],
            "reason_reference": [self._ref(r) for r in data.get("reasonReference", [])],
            "body_site":      [self._cc(b) for b in data.get("bodySite", [])],
            "outcome":        self._cc(data.get("outcome", {})),
            "report":         [self._ref(r) for r in data.get("report", [])],
            "complication":   [self._cc(c) for c in data.get("complication", [])],
            "follow_up":      [self._cc(f) for f in data.get("followUp", [])],
            "note":           [n.get("text", "") for n in data.get("note", [])],
            "focal_device":   data.get("focalDevice", []),
            "used_reference": [self._ref(u) for u in data.get("usedReference", [])],
            "meta": self._meta(data),
        }

    def _parse_immunization(self, data: dict) -> dict:
        return {
            "resource_type":   "Immunization",
            "id":              data.get("id", ""),
            "status":          data.get("status", ""),
            "status_reason":   self._cc(data.get("statusReason", {})),
            "vaccine_code":    self._cc(data.get("vaccineCode", {})),
            "patient":         self._ref(data.get("patient", {})),
            "encounter":       self._ref(data.get("encounter", {})),
            "occurrence_datetime": data.get("occurrenceDateTime", ""),
            "recorded":        data.get("recorded", ""),
            "primary_source":  data.get("primarySource", True),
            "location":        self._ref(data.get("location", {})),
            "manufacturer":    self._ref(data.get("manufacturer", {})),
            "lot_number":      data.get("lotNumber", ""),
            "expiration_date": data.get("expirationDate", ""),
            "site":            self._cc(data.get("site", {})),
            "route":           self._cc(data.get("route", {})),
            "dose_quantity":   data.get("doseQuantity", {}),
            "performer": [
                {"function": self._cc(p.get("function", {})), "actor": self._ref(p.get("actor", {}))}
                for p in data.get("performer", [])
            ],
            "note":            [n.get("text", "") for n in data.get("note", [])],
            "reason_code":     [self._cc(r) for r in data.get("reasonCode", [])],
            "is_subpotent":    data.get("isSubpotent", False),
            "education":       data.get("education", []),
            "protocol_applied": data.get("protocolApplied", []),
            "reaction": [
                {
                    "date":     r.get("date", ""),
                    "detail":   self._ref(r.get("detail", {})),
                    "reported": r.get("reported", False),
                }
                for r in data.get("reaction", [])
            ],
            "meta": self._meta(data),
        }

    def _parse_bundle(self, data: dict) -> dict:
        entries = []
        for entry in data.get("entry", []):
            resource = entry.get("resource", {})
            if resource:
                sub = self.parse(resource)
                entries.append({
                    "full_url":     entry.get("fullUrl", ""),
                    "resource_type": resource.get("resourceType", ""),
                    "resource_id":  resource.get("id", ""),
                    "summary":      sub.summary,
                    "search":       entry.get("search", {}),
                    "request":      entry.get("request", {}),
                    "response":     entry.get("response", {}),
                })

        counts = {}
        for e in entries:
            rt = e["resource_type"]
            counts[rt] = counts.get(rt, 0) + 1

        return {
            "resource_type":         "Bundle",
            "id":                    data.get("id", ""),
            "type":                  data.get("type", ""),
            "timestamp":             data.get("timestamp", ""),
            "total":                 data.get("total", len(entries)),
            "entry_count":           len(entries),
            "resource_type_summary": counts,
            "entries":               entries,
            "link": [{"relation": l.get("relation", ""), "url": l.get("url", "")} for l in data.get("link", [])],
            "meta": self._meta(data),
        }

    def _parse_practitioner(self, data: dict) -> dict:
        return {
            "resource_type": "Practitioner",
            "id":            data.get("id", ""),
            "active":        data.get("active", True),
            "identifier":    self._all_identifiers(data.get("identifier", [])),
            "name":          self._name(data.get("name", [])),
            "telecom":       self._telecom(data.get("telecom", [])),
            "address":       self._address(data.get("address", [])),
            "gender":        data.get("gender", ""),
            "birth_date":    data.get("birthDate", ""),
            "photo":         data.get("photo", []),
            "qualification": [
                {
                    "identifier": self._all_identifiers(q.get("identifier", [])),
                    "code":       self._cc(q.get("code", {})),
                    "period":     self._period(q.get("period", {})),
                    "issuer":     self._ref(q.get("issuer", {})),
                }
                for q in data.get("qualification", [])
            ],
            "communication": [self._cc(c) for c in data.get("communication", [])],
            "meta": self._meta(data),
        }

    def _parse_organization(self, data: dict) -> dict:
        return {
            "resource_type": "Organization",
            "id":            data.get("id", ""),
            "active":        data.get("active", True),
            "identifier":    self._all_identifiers(data.get("identifier", [])),
            "type":          [self._cc(t) for t in data.get("type", [])],
            "name":          data.get("name", ""),
            "alias":         data.get("alias", []),
            "telecom":       self._telecom(data.get("telecom", [])),
            "address":       self._address(data.get("address", [])),
            "part_of":       self._ref(data.get("partOf", {})),
            "contact": [
                {
                    "purpose":  self._cc(c.get("purpose", {})),
                    "name":     self._name([c.get("name", {})]) if c.get("name") else {},
                    "telecom":  self._telecom(c.get("telecom", [])),
                    "address":  self._address([c.get("address", {})]) if c.get("address") else {},
                }
                for c in data.get("contact", [])
            ],
            "endpoint": [self._ref(e) for e in data.get("endpoint", [])],
            "meta": self._meta(data),
        }

    def _parse_coverage(self, data: dict) -> dict:
        return {
            "resource_type":  "Coverage",
            "id":             data.get("id", ""),
            "status":         data.get("status", ""),
            "type":           self._cc(data.get("type", {})),
            "policy_holder":  self._ref(data.get("policyHolder", {})),
            "subscriber":     self._ref(data.get("subscriber", {})),
            "subscriber_id":  data.get("subscriberId", ""),
            "beneficiary":    self._ref(data.get("beneficiary", {})),
            "dependent":      data.get("dependent", ""),
            "relationship":   self._cc(data.get("relationship", {})),
            "period":         self._period(data.get("period", {})),
            "payor":          [self._ref(p) for p in data.get("payor", [])],
            "class": [
                {
                    "type":  self._cc(c.get("type", {})),
                    "value": c.get("value", ""),
                    "name":  c.get("name", ""),
                }
                for c in data.get("class", [])
            ],
            "order":          data.get("order"),
            "network":        data.get("network", ""),
            "cost_to_beneficiary": [
                {
                    "type":        self._cc(c.get("type", {})),
                    "value_money": c.get("valueMoney", {}),
                    "value_quantity": c.get("valueQuantity", {}),
                    "exception": [self._cc(e.get("type", {})) for e in c.get("exception", [])],
                }
                for c in data.get("costToBeneficiary", [])
            ],
            "subrogation":    data.get("subrogation", False),
            "contract":       [self._ref(c) for c in data.get("contract", [])],
            "meta": self._meta(data),
        }


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE DATA
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_PATIENT = {
    "resourceType": "Patient",
    "id": "patient-001",
    "meta": {"versionId": "3", "lastUpdated": "2024-03-15T14:30:22Z", "profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]},
    "identifier": [
        {"use": "usual",    "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR",  "display": "Medical record number"}]}, "system": "urn:oid:1.3.6.1.4.1.21367.2005.3.7", "value": "MR-123456"},
        {"use": "official", "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "SS",  "display": "Social Security number"}]}, "system": "http://hl7.org/fhir/sid/us-ssn", "value": "111-22-3333"},
    ],
    "active": True,
    "name": [{"use": "official", "family": "Smith", "given": ["John", "William"], "prefix": ["Mr."]}],
    "telecom": [
        {"system": "phone", "value": "312-555-7890", "use": "home"},
        {"system": "phone", "value": "312-555-1234", "use": "work"},
        {"system": "email", "value": "john.smith@email.com"},
    ],
    "gender": "male",
    "birthDate": "1985-03-22",
    "address": [{"use": "home", "line": ["123 Main St", "Apt 4B"], "city": "Chicago", "state": "IL", "postalCode": "60601", "country": "USA"}],
    "maritalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus", "code": "M", "display": "Married"}]},
    "communication": [{"language": {"coding": [{"system": "urn:ietf:bcp:47", "code": "en", "display": "English"}]}, "preferred": True}],
    "generalPractitioner": [{"reference": "Practitioner/prac-001", "display": "Dr. Emily Johnson"}],
    "managingOrganization": {"reference": "Organization/org-001", "display": "Memorial Hospital"},
}

SAMPLE_OBSERVATION = {
    "resourceType": "Observation",
    "id": "obs-hgb-001",
    "status": "final",
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory", "display": "Laboratory"}]}],
    "code": {"coding": [{"system": "http://loinc.org", "code": "718-7", "display": "Hemoglobin [Mass/volume] in Blood"}], "text": "Hemoglobin"},
    "subject": {"reference": "Patient/patient-001", "display": "John Smith"},
    "encounter": {"reference": "Encounter/enc-001"},
    "effectiveDateTime": "2024-03-15T16:00:00Z",
    "issued": "2024-03-15T16:05:30Z",
    "performer": [{"reference": "Practitioner/prac-001", "display": "Dr. Emily Johnson"}],
    "valueQuantity": {"value": 8.2, "unit": "g/dL", "system": "http://unitsofmeasure.org", "code": "g/dL"},
    "interpretation": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": "L", "display": "Low"}]}],
    "referenceRange": [{"low": {"value": 13.5, "unit": "g/dL"}, "high": {"value": 17.5, "unit": "g/dL"}}],
    "note": [{"text": "Critical value — phoned to Dr. Johnson at 16:05"}],
}

SAMPLE_ENCOUNTER = {
    "resourceType": "Encounter",
    "id": "enc-001",
    "status": "in-progress",
    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
    "type": [{"coding": [{"system": "http://snomed.info/sct", "code": "11429006", "display": "Consultation"}]}],
    "subject": {"reference": "Patient/patient-001", "display": "John Smith"},
    "period": {"start": "2024-03-15T14:30:00Z"},
    "participant": [{"type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType", "code": "ATND", "display": "attender"}]}], "individual": {"reference": "Practitioner/prac-001", "display": "Dr. Emily Johnson"}}],
    "reasonCode": [{"coding": [{"system": "http://snomed.info/sct", "code": "57054005", "display": "Acute myocardial infarction"}]}],
    "diagnosis": [{"condition": {"reference": "Condition/cond-001"}, "use": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/diagnosis-role", "code": "AD", "display": "Admission diagnosis"}]}, "rank": 1}],
    "hospitalization": {"admitSource": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/admit-source", "code": "emd", "display": "From accident/emergency department"}]}, "dischargeDisposition": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/discharge-disposition", "code": "home", "display": "Home"}]}},
    "location": [{"location": {"reference": "Location/loc-icu-101", "display": "ICU Room 101"}, "status": "active"}],
    "serviceProvider": {"reference": "Organization/org-001", "display": "Memorial Hospital"},
}

SAMPLE_CONDITION = {
    "resourceType": "Condition",
    "id": "cond-001",
    "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active", "display": "Active"}]},
    "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed", "display": "Confirmed"}]},
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "encounter-diagnosis", "display": "Encounter Diagnosis"}]}],
    "severity": {"coding": [{"system": "http://snomed.info/sct", "code": "24484000", "display": "Severe"}]},
    "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I21.9", "display": "Acute myocardial infarction, unspecified"}], "text": "Heart Attack"},
    "subject": {"reference": "Patient/patient-001"},
    "encounter": {"reference": "Encounter/enc-001"},
    "onsetDateTime": "2024-03-15T13:00:00Z",
    "recordedDate": "2024-03-15T14:30:00Z",
    "note": [{"text": "Patient presented with crushing chest pain radiating to left arm."}],
}

SAMPLE_ALLERGY = {
    "resourceType": "AllergyIntolerance",
    "id": "allergy-001",
    "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active", "display": "Active"}]},
    "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "confirmed", "display": "Confirmed"}]},
    "type": "allergy",
    "category": ["medication"],
    "criticality": "high",
    "code": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "7980", "display": "Penicillin"}], "text": "Penicillin"},
    "patient": {"reference": "Patient/patient-001"},
    "reaction": [{"manifestation": [{"coding": [{"system": "http://snomed.info/sct", "code": "247472004", "display": "Hives"}]}], "severity": "severe", "onset": "2007-05-01"}],
    "note": [{"text": "Anaphylaxis risk — always carry epi-pen"}],
}

SAMPLE_BUNDLE = {
    "resourceType": "Bundle",
    "id": "bundle-patient-summary",
    "type": "collection",
    "timestamp": "2024-03-15T16:30:00Z",
    "entry": [
        {"fullUrl": "urn:uuid:patient-001",   "resource": SAMPLE_PATIENT},
        {"fullUrl": "urn:uuid:obs-hgb-001",   "resource": SAMPLE_OBSERVATION},
        {"fullUrl": "urn:uuid:enc-001",        "resource": SAMPLE_ENCOUNTER},
        {"fullUrl": "urn:uuid:cond-001",       "resource": SAMPLE_CONDITION},
        {"fullUrl": "urn:uuid:allergy-001",    "resource": SAMPLE_ALLERGY},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# DEMO
# ─────────────────────────────────────────────────────────────────────────────

def demo():
    parser = FHIRParser()
    sep    = "=" * 68

    print(sep)
    print("  FHIR R4 PARSER  —  DEMO")
    print(sep)

    tests = [
        ("Patient",           SAMPLE_PATIENT),
        ("Observation",       SAMPLE_OBSERVATION),
        ("Encounter",         SAMPLE_ENCOUNTER),
        ("Condition",         SAMPLE_CONDITION),
        ("AllergyIntolerance",SAMPLE_ALLERGY),
        ("Bundle",            SAMPLE_BUNDLE),
    ]

    for label, resource in tests:
        print(f"\n{'─'*68}")
        print(f"  {label}")
        print(f"{'─'*68}")

        r = parser.parse(resource)
        print(f"  Success        : {r.success}")
        print(f"  Resource Type  : {r.resource_type}")
        s = r.summary

        if label == "Patient":
            print(f"  Name           : {s.get('name', {}).get('full')}")
            print(f"  DOB            : {s.get('date_of_birth')}")
            print(f"  Gender         : {s.get('gender')}")
            print(f"  MRN            : {s.get('mrn')}")
            tc = s.get("telecom", {})
            print(f"  Phone (home)   : {tc.get('phone', 'N/A')}")
            print(f"  Email          : {tc.get('email', 'N/A')}")
            addr = s.get("address", {})
            line = ", ".join(addr.get("line", []))
            print(f"  Address        : {line}, {addr.get('city')}, {addr.get('state')} {addr.get('postal_code')}")
            print(f"  GP             : {s.get('general_practitioner', [{}])[0].get('display', 'N/A')}")

        elif label == "Observation":
            val  = s.get("value", {})
            rr   = s.get("reference_range", [{}])[0]
            interp = s.get("interpretation", [{}])[0].get("coding", {}).get("display", "")
            print(f"  Test           : {s.get('code', {}).get('text')}")
            print(f"  LOINC          : {s.get('code', {}).get('coding', {}).get('code')}")
            print(f"  Value          : {val.get('display')}")
            print(f"  Status         : {s.get('status')}")
            print(f"  Is Abnormal    : {s.get('is_abnormal')}")
            print(f"  Interpretation : {interp}")
            print(f"  Ref Range      : {rr.get('low')} – {rr.get('high')}")
            print(f"  Note           : {s.get('note', [''])[0]}")

        elif label == "Encounter":
            cls = s.get("class", {})
            print(f"  Class          : {cls.get('code')} — {cls.get('display')}")
            print(f"  Status         : {s.get('status')}")
            print(f"  Period         : {s.get('period', {}).get('start')} → {s.get('period', {}).get('end') or 'ongoing'}")
            for part in s.get("participant", []):
                print(f"  Participant    : {part.get('individual', {}).get('display')}")
            for dx in s.get("diagnosis", []):
                print(f"  Diagnosis      : {dx.get('condition', {}).get('reference')} (rank {dx.get('rank')})")

        elif label == "Condition":
            print(f"  Code           : {s.get('code', {}).get('text')}")
            print(f"  ICD-10         : {s.get('code', {}).get('coding', {}).get('code')}")
            print(f"  Clinical Status: {s.get('clinical_status', {}).get('coding', {}).get('display')}")
            print(f"  Severity       : {s.get('severity', {}).get('coding', {}).get('display')}")
            print(f"  Onset          : {s.get('onset_datetime')}")
            print(f"  Note           : {s.get('note', [''])[0]}")

        elif label == "AllergyIntolerance":
            print(f"  Allergen       : {s.get('code', {}).get('text')}")
            print(f"  Type           : {s.get('type')} / Category: {', '.join(s.get('category', []))}")
            print(f"  Criticality    : {s.get('criticality')}")
            for rxn in s.get("reaction", []):
                for m in rxn.get("manifestation", []):
                    print(f"  Reaction       : {m.get('coding', {}).get('display')} ({rxn.get('severity')})")
            print(f"  Note           : {s.get('note', [''])[0]}")

        elif label == "Bundle":
            print(f"  Bundle Type    : {s.get('type')}")
            print(f"  Timestamp      : {s.get('timestamp')}")
            print(f"  Total Entries  : {s.get('entry_count')}")
            print(f"  Resources      : {s.get('resource_type_summary')}")

    # JSON sample for Patient
    print(f"\n{'─'*68}")
    print("  JSON OUTPUT SAMPLE  (Patient summary)")
    print(f"{'─'*68}")
    r_pt = parser.parse(SAMPLE_PATIENT)
    print(r_pt.to_json())

    print(f"\n{sep}")
    print("  Done. Import FHIRParser in your own code to use.")
    print(sep)


if __name__ == "__main__":
    demo()
