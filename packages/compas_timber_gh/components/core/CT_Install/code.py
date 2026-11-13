"""This is the ONLY component that should have this r: specifier! to prevent rhino from forever re-installing everything."""

# r: compas_timber_gh==0.3.1, compas_timber_rules==0.3.1, compas_timber==2.2.0
import compas
import compas_timber

import compas_timber_gh
import compas_timber_rules

print(f"compas: {compas.__version__}")
print(f"compas_timber: {compas_timber.__version__}")
print(f"compas_timber_rules: {compas_timber_rules.__version__}")
print(f"compas_timber_gh: {compas_timber_gh.__version__}")
