from __future__ import print_function

import os
import re
from pathlib import Path

import invoke
from compas_invocations2 import build
from compas_invocations2 import mkdocs
from compas_invocations2 import style
from compas_invocations2 import tests
from compas_invocations2 import grasshopper

from invoke.collection import Collection

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "src")
GH_PACKAGE = os.path.join(SRC, "timber_design_gh")

# All packages ship in the single `timber_design` distribution; components require it via `# r:`.
DIST_NAME = "timber_design"

# Grasshopper targets: each one becomes its own set of .ghuser files and its own Yak package.
GH_TARGETS = {
    "core": {
        "source_dir": os.path.join(GH_PACKAGE, "components", "core"),
        "target_dir": os.path.join(HERE, "dist", "ghuser", "core"),
        "yak_dir": os.path.join(GH_PACKAGE, "yak", "core"),
    },
    "populator": {
        "source_dir": os.path.join(GH_PACKAGE, "components", "populator"),
        "target_dir": os.path.join(HERE, "dist", "ghuser", "populator"),
        "yak_dir": os.path.join(GH_PACKAGE, "yak", "populator"),
    },
}

# components that manage their own pinned `# r:` header and must not be touched
GH_HEADER_SKIP = {"CT_Install"}


def _version():
    """Version of the `timber_design` distribution (bump-my-version keeps all package __init__ files in sync)."""
    init = os.path.join(SRC, "timber_design_rules", "__init__.py")
    with open(init, "r", encoding="utf-8") as f:
        return re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)


def _targets(target):
    if target in (None, "all"):
        return list(GH_TARGETS)
    if target not in GH_TARGETS:
        raise invoke.Exit("Unknown target '{}', choose from: all, {}".format(target, ", ".join(GH_TARGETS)))
    return [target]


def _configure_ghuser(ctx, target):
    cfg = GH_TARGETS[target]
    ctx.config.ghuser_cpython = {"source_dir": cfg["source_dir"], "target_dir": cfg["target_dir"], "prefix": "CT: "}


@invoke.task(help={"target": "core, populator or all (default)", "gh_io_folder": "Folder containing GH_IO.dll (downloaded if omitted)."})
def build_gh_components(ctx, target="all", gh_io_folder=None):
    """Build CPython .ghuser components for one or all Grasshopper targets."""
    for t in _targets(target):
        _configure_ghuser(ctx, t)
        build.build_cpython_ghuser_components(ctx, gh_io_folder=gh_io_folder)


@invoke.task(
    help={
        "target": "core, populator or all (default)",
        "dev": "Instead of the `# r:` requirement, add an `# env:` line pointing at the local src folder.",
        "venv": "(Optional) Rhino virtual environment name added as `# venv:`.",
    }
)
def update_gh_headers(ctx, target="all", dev=False, venv=None):
    """Rewrite the dependency header of every component in the given Grasshopper target(s)."""
    for t in _targets(target):
        cfg = GH_TARGETS[t]
        header = []
        if venv:
            header.append("# venv: {}\n".format(venv))
        if dev:
            header.append("# env: {}\n".format(SRC))
        else:
            header.append("# r: {}>={}\n".format(DIST_NAME, _version()))

        for code in sorted(Path(cfg["source_dir"]).glob("*/code.py")):
            if code.parent.name in GH_HEADER_SKIP:
                continue
            with open(code, "r", encoding="utf-8") as f:
                lines = f.readlines()
            body = [line for line in lines if not grasshopper._is_header_line(line)]
            with open(code, "w", encoding="utf-8") as f:
                f.writelines(header + body)
            print("Updated: {}".format(code))


@invoke.task(
    help={
        "target": "core or populator",
        "version": "Version written into the manifest (defaults to the timber_design version).",
        "target_rhino": "Target Rhino version (default rh8).",
    }
)
def yakerize_gh(ctx, target, version=None, target_rhino="rh8"):
    """Create the Yak package for one Grasshopper target from previously built .ghuser components."""
    cfg = GH_TARGETS[_targets(target)[0]]
    grasshopper.yakerize(
        ctx,
        manifest_path=os.path.join(cfg["yak_dir"], "manifest.yml"),
        logo_path=os.path.join(cfg["yak_dir"], "icon.png"),
        gh_components_dir=cfg["target_dir"],
        version=version or _version(),
        target_rhino=target_rhino,
    )


ns = Collection(
    style.check,
    style.lint,
    style.format,
    tests.test,
    build.prepare_changelog,
    build.clean,
    build.release,
    build_gh_components,
    update_gh_headers,
    yakerize_gh,
    grasshopper.publish_yak,
    mkdocs.docs,
)

ns.configure(
    {
        "base_folder": HERE,
    }
)
