from compas.geometry import Point, Polyline, Vector

from compas_timber.elements import Slab

from timber_design.populators import SlabPopulator


outline = Polyline([Point(0, 0, 0), Point(5000, 0, 0), Point(5000, 3000, 0), Point(0, 3000, 0), Point(0, 0, 0)])

slab = Slab(outline, 200)

print(slab)

