"""This is the ONLY component that should have this r: specifier! to prevent rhino from forever re-installing everything."""

# r: timber_design==0.3.0, compas_timber==2.2.0
import compas
import compas_timber

import timber_design

print(f"compas: {compas.__version__}")
print(f"compas_timber: {compas_timber.__version__}")
print(f"timber_design: {timber_design.__version__}")
