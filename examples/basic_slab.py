from compas.geometry import Point, Polyline, Vector

from compas_timber.elements import Panel

from timber_design.populators import PanelPopulator


outline = Polyline([Point(0, 0, 0), Point(5000, 0, 0), Point(5000, 3000, 0), Point(0, 3000, 0), Point(0, 0, 0)])

panel = Panel(outline, 200)

print(panel)

