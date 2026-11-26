import os

__version__ = "0.3.1"

HERE = os.path.dirname(__file__)
HOME = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.abspath(os.path.join(HOME, "data"))


__all__ = ["__version__", "DATA", "HOME"]
