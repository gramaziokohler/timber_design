# Show

Tools for previewing, inspecting and extracting geometry and data from the model.

## Show Element Reference Sides

![Show Beam Face Index](../images/gh_show_beam_face_index.png){ width=20% }

**Show element Reference Side** displays the sides of an element based on `ref_side_index`.
Text labels are located at the reference side origins and oriented along the reference sides.

## Show Element Index

![Show Beam Index](../images/gh_show_beam_index.png){ width=20% }

**ShowElementIndex** displays the key of each Element in the Model.

## Show Elements By Type

**ShowElementsByType** filters element geometries by element type.

## Show Elements By Category

**ShowElementsByCategory** visualizes the elements of the model by their `Category` attribute.

## Show Feature Errors

![Show Feature Errors](../images/gh_show_feature_errors.png){ width=25% }

Shows information useful for debugging feature application errors.

## Show Joining Errors

![Show Joining Errors](../images/gh_show_joining_errors.png){ width=25% }

Shows information useful for debugging errors that occurred while attempting to join Beams.

## Show Joint Types

![Show Joint Types](../images/gh_show_joint_types.png){ width=20% }

Displays the type names of each joint in the model.

## Show Topology Types

![Show Topology Types](../images/gh_show_topology_types.png){ width=20% }

Displays the topologies (L, T or X) that Compas Timber recognizes at each Joint

## Related

**DecomposeBeam** and **FindBeamByRhinoGuid** also belong to this group — they are described in [beams](beams.md).
