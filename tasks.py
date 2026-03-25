from __future__ import print_function

import os

from compas_invocations2 import build
from compas_invocations2 import mkdocs
from compas_invocations2 import style
from compas_invocations2 import tests
from compas_invocations2 import grasshopper

from invoke.collection import Collection

ns = Collection(
    style.check,
    style.lint,
    style.format,
    tests.test,
    tests.testdocs,
    tests.testcodeblocks,
    build.prepare_changelog,
    build.clean,
    build.release,
    build.build_ghuser_components,
    build.build_cpython_ghuser_components,
    grasshopper.yakerize,
    grasshopper.publish_yak,
    grasshopper.update_gh_header,
    mkdocs.docs,
)

ns.configure(
    {
        "base_folder": os.path.dirname(__file__),
        "ghuser_cpython": {
            "source_dir": "src/timber_design/ghpython/components",
            "target_dir": "src/timber_design/ghpython/components/ghuser",
            "prefix": "CT: ",
        },
    }
)
