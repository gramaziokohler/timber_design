# r: compas_timber>=1.0.3
# flake8: noqa
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython
from timber_design.workflow import Attribute

n = item_input_valid_cpython(ghenv, Name, "Name")
v = item_input_valid_cpython(ghenv, Value, "Value")

if n and v:
    Attribute = Attribute(Name, Value)
