"""This is the ONLY component that should have this r: specifier! to prevent rhino from forever re-installing everything."""

# r: timber_design==0.3.1, compas_timber==2.2.0
import compas
import compas_timber

import compas_timber_rules

print(f"compas: {compas.__version__}")
print(f"compas_timber: {compas_timber.__version__}")
print(f"timber_design: {compas_timber_rules.__version__}")
