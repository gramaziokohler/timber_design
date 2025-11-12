from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import intersection_line_segment
from compas.geometry import dot_vectors


def get_beam_edges_feature_def_intersection(beam, feature_def):
    edge_a = beam.centerline.translated(beam.frame.yaxis*-beam.width/2)
    edge_b = beam.centerline.translated(beam.frame.yaxis*beam.width/2)
    intersections_a = {}
    intersections_b = {}
    for index, element_dict in feature_def.element_edge_dict.items():
        if not hasattr(element_dict["beam"], "centerline"):
            continue
        pt = intersection_line_segment(edge_a, element_dict["edge"])[0]
        if pt:
            intersections_a[index] = {"point": Point(*pt), "dot": dot_vectors(Vector.from_start_end(edge_a.start, pt), edge_a.direction), "beam": element_dict["beam"]}
        pt = intersection_line_segment(edge_b, element_dict["edge"])[0]
        if pt:
            intersections_b[index] = {"point": Point(*pt), "dot": dot_vectors(Vector.from_start_end(edge_b.start, pt), edge_b.direction), "beam": element_dict["beam"]}

    return _classify_intersections(intersections_a, intersections_b, feature_def)



def _classify_intersections(intersections_a, intersections_b, feature_def):
    edge_count = len(feature_def.element_edge_dict)
    simple_keys = list(set(intersections_a).intersection(set(intersections_b)))
    simple_intersections = []
    for i in simple_keys:
        simple_intersections.append({
            "point": (intersections_a[i]["point"] + intersections_b[i]["point"]) / 2,
            "dot": (intersections_a[i]["dot"] + intersections_b[i]["dot"]) / 2,
            "beams": list(set([intersections_a[i]["beam"], intersections_b[i]["beam"]])),
            "feature_def": feature_def
            })
    leftovers_a = list(set(intersections_a)-set(intersections_b))
    leftovers_b = list(set(intersections_b)-set(intersections_a))
    corner_intersections = []
    notch_intersections = []
    lap_intersections = []

    while leftovers_a:
        ia = leftovers_a.pop()
        for i_adjacent in [(ia-1)%edge_count, (ia+1)%edge_count]:
            if i_adjacent in leftovers_b:
                ib = leftovers_b.pop(leftovers_b.index(i_adjacent))
                intersection = {
                    "point": (intersections_a[ia]["point"] + intersections_b[ib]["point"]) / 2,
                    "dot": (intersections_a[ia]["dot"] + intersections_b[ib]["dot"]) / 2,
                    "beams": [intersections_a[ia]["beam"], intersections_b[ib]["beam"]],
                    "feature_def": feature_def}
                corner_intersections.append(intersection)
                break
            elif i_adjacent in leftovers_a:
                ia_b = leftovers_a.pop(leftovers_a.index(i_adjacent))
                intersection = {
                    "point": (intersections_a[ia]["point"] + intersections_a[ia_b]["point"]) / 2,
                    "dot": (intersections_a[ia]["dot"] + intersections_a[ia_b]["dot"]) / 2,
                    "beams": [intersections_a[ia]["beam"], intersections_a[ia_b]["beam"]],
                    "feature_def": feature_def}
                notch_intersections.append(intersection)
                break
        else:
            lap_intersections.append({"point": intersections_a[ia]["point"], "dot": intersections_a[ia]["dot"], "beams": [intersections_a[ia]["beam"]], "feature_def": feature_def})


    while leftovers_b:
        ib = leftovers_b.pop()
        for i_adjacent in [(ib-1)%edge_count, (ib+1)%edge_count]:
            if i_adjacent in leftovers_b:
                ib_b = leftovers_b.pop(leftovers_b.index(i_adjacent))
                intersection = {
                    "point": (intersections_b[ib]["point"] + intersections_b[ib_b]["point"]) / 2,
                    "dot": (intersections_b[ib]["dot"] + intersections_b[ib_b]["dot"]) / 2,
                    "beams": [intersections_b[ib]["beam"], intersections_b[ib_b]["beam"]],
                    "feature_def": feature_def}
                notch_intersections.append(intersection)
                break
        else:
            lap_intersections.append({"point": intersections_b[ib]["point"], "dot": intersections_b[ib]["dot"], "beams": [intersections_b[ib]["beam"]], "feature_def": feature_def})


    return simple_intersections, corner_intersections, notch_intersections, lap_intersections

