# r: timber_design>=0.1.0
# flake8: noqa
import Grasshopper
import System

from compas_timber.planning import PlateStock as CTPlateStock
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython


class PlateStock(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        stock_x: System.Collections.Generic.List[float],
        stock_y: System.Collections.Generic.List[float],
        thickness: System.Collections.Generic.List[float],
    ):
        if not item_input_valid_cpython(ghenv, stock_x, "StockX"):
            return
        if not item_input_valid_cpython(ghenv, stock_y, "StockY"):
            return
        if not item_input_valid_cpython(ghenv, thickness, "Thickness"):
            return

        stock_x = list(stock_x)
        stock_y = list(stock_y)
        thickness = list(thickness)

        count = max(len(stock_x), len(stock_y), len(thickness))

        if len(stock_x) != count:
            for _ in range(count - len(stock_x)):
                stock_x.append(stock_x[0])

        if len(stock_y) != count:
            for _ in range(count - len(stock_y)):
                stock_y.append(stock_y[0])

        if len(thickness) != count:
            for _ in range(count - len(thickness)):
                thickness.append(thickness[0])

        # Create stock objects
        stocks = []
        for x, y, t in zip(stock_x, stock_y, thickness):
            stock = CTPlateStock((x, y), t)
            stocks.append(stock)

        return stocks
