"""
MsgParser - Medical Message Parser Library
Demonstrates HL7, FHIR, and C-CDA parsers.
"""

print("MsgParser - Medical Message Parser Library")
print("=" * 60)
print()
print("Available parsers:")
print("  from hl7_parser  import HL7Parser")
print("  from fhir_parser import FHIRParser")
print("  from ccda_parser import CCDAParser")
print()
print("Run individual demos:")
print("  python hl7_parser.py")
print("  python fhir_parser.py")
print("  python ccda_parser.py")
print()

from hl7_parser import HL7Parser
from fhir_parser import FHIRParser
from ccda_parser import CCDAParser

print("All parsers imported successfully.")
print()
print("Running HL7 demo...")
print("-" * 60)
import hl7_parser
hl7_parser.demo()

print()
print("Running FHIR demo...")
print("-" * 60)
import fhir_parser
fhir_parser.demo()

print()
print("Running C-CDA demo...")
print("-" * 60)
import ccda_parser
ccda_parser.demo()
