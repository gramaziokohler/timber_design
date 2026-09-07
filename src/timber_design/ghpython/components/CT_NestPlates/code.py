# r: timber_design>=0.1.0
# flake8: noqa
import Grasshopper
import System
import warnings

from compas_timber.planning import PlateNester as CTPlateNester
from compas_timber.planning import PlateStock
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython


class PlateNester(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, model, stock_catalog: System.Collections.Generic.List[object], spacing: float, per_group: bool, seed: int, fast: bool):
        if not item_input_valid_cpython(ghenv, model, "Model"):
            return
        if not item_input_valid_cpython(ghenv, stock_catalog, "Stock Catalog"):
            return

        # Validate stock catalog items
        stock_catalog = list(stock_catalog)
        for stock in stock_catalog:
            if not isinstance(stock, PlateStock):
                ghenv.Component.AddRuntimeMessage(
                    Grasshopper.Kernel.GH_RuntimeMessageLevel.Error,
                    f"All items in Stock Catalog must be of type PlateStock. Found {type(stock)}",
                )
                return

        fast = fast or False
        spacing = spacing or 0.0
        per_group = per_group or False
        seed = seed or 0
        # Catch any warnings raised for unnested plates
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            plate_nester = CTPlateNester(model, stock_catalog, spacing=spacing, per_group=per_group, seed=seed)
            nesting_result = plate_nester.nest(fast=fast)
            nesting_summary = nesting_result.summary
            if w:
                for warning in w:
                    ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, str(warning.message))
                # Add warnings section to summary
                nesting_summary += "\n\nWARNINGS:\n~~~~~~"
                for i, warning in enumerate(w, 1):
                    nesting_summary += f"\nWarning_{i}:\n{str(warning.message)}\n--------"

        return nesting_result, nesting_summary
