from __future__ import print_function

import os
import re
import sys
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
# built .ghuser files go into the package, one folder per target (gitignored)
GHUSER_DIR = os.path.join(GH_PACKAGE, "ghuser")

# All packages ship in the single `timber_design` distribution; components require it via `# r:`.
DIST_NAME = "timber_design"

# Grasshopper targets, named after the package each one becomes: its own set of .ghuser files, its own
# UserObjects folder and its own Yak package.
GH_TARGETS = {
    "compas_timber": {
        "source_dir": os.path.join(GH_PACKAGE, "components", "core"),
        "target_dir": os.path.join(GHUSER_DIR, "compas_timber"),
        "yak_dir": os.path.join(GH_PACKAGE, "yak", "compas_timber"),
    },
    "timber_arch": {
        "source_dir": os.path.join(GH_PACKAGE, "components", "timber_arch"),
        "target_dir": os.path.join(GHUSER_DIR, "timber_arch"),
        "yak_dir": os.path.join(GH_PACKAGE, "yak", "timber_arch"),
    },
}
# earlier target names, still accepted
GH_TARGET_ALIASES = {"core": "compas_timber", "populator": "timber_arch"}

# where older installs put the components, inside the UserObjects folder; removed on install
OLD_USEROBJECTS_SUBFOLDER = "timber_design"
# components that were removed from the sources; an install deletes copies left over from older installs
GH_REMOVED_COMPONENTS = {"CT_Feature_Agent", "CT_Detail_Agent"}

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
    target = GH_TARGET_ALIASES.get(target, target)
    if target not in GH_TARGETS:
        raise invoke.Exit("Unknown target '{}', choose from: all, {}".format(target, ", ".join(GH_TARGETS)))
    return [target]


def _configure_ghuser(ctx, target):
    cfg = GH_TARGETS[target]
    ctx.config.ghuser_cpython = {"source_dir": cfg["source_dir"], "target_dir": cfg["target_dir"], "prefix": "CT: "}


def _configure_componentizer_env():
    """Set up the environment the componentizer subprocess runs in.

    compas_invocations2 launches the componentizer as a plain ``python`` command, which
    resolves through PATH and can pick up a different interpreter than the one running
    invoke (e.g. from a VS Code task). Put this interpreter first so both match.

    On Apple Silicon, pythonnet defaults to the Mono framework in /Library/Frameworks,
    which is x86-only. Use Homebrew's arm64 Mono instead when it is installed and no
    runtime has been configured explicitly.
    """
    os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")
    if "PYTHONNET_RUNTIME" not in os.environ:
        for libmono in ("/opt/homebrew/lib/libmonosgen-2.0.dylib",):
            if os.path.isfile(libmono):
                os.environ["PYTHONNET_RUNTIME"] = "mono"
                os.environ["PYTHONNET_MONO_LIBMONO"] = libmono
                break


@invoke.task(help={"target": "compas_timber, timber_arch or all (default)", "gh_io_folder": "Folder containing GH_IO.dll (downloaded if omitted)."})
def build_gh_components(ctx, target="all", gh_io_folder=None):
    """Build CPython .ghuser components for one or all Grasshopper targets."""
    _configure_componentizer_env()
    for t in _targets(target):
        # the componentizer creates target_dir with os.mkdir, so its parent must already exist
        os.makedirs(os.path.dirname(GH_TARGETS[t]["target_dir"]), exist_ok=True)
        _configure_ghuser(ctx, t)
        build.build_cpython_ghuser_components(ctx, gh_io_folder=gh_io_folder)


def _cached_gh_io_folder():
    """Folder holding a cached standalone GH_IO.dll, downloaded from NuGet on first use.

    The GH_IO.dll shipped inside Rhino 8 depends on Eto and cannot be loaded on its own by
    the componentizer, so the standalone one from the NuGet Grasshopper package is used.
    """
    folder = os.path.join(HERE, "dist", "gh_io")
    if not os.path.isfile(os.path.join(folder, "GH_IO.dll")):
        import compas_ghpython

        os.makedirs(folder, exist_ok=True)
        print("Downloading GH_IO.dll from NuGet into {}".format(folder))
        compas_ghpython.fetch_ghio_lib(folder)
    return folder


def _default_userobjects_folder():
    """Grasshopper's UserObjects folder for Rhino 8, or None if it cannot be found."""
    if os.name == "nt":
        folder = os.path.join(os.environ.get("APPDATA", ""), "Grasshopper", "UserObjects")
        return folder if os.path.isdir(folder) else None
    plugins = Path.home() / "Library" / "Application Support" / "McNeel" / "Rhinoceros" / "8.0" / "Plug-ins"
    folders = sorted(plugins.glob("Grasshopper (*)/UserObjects"))
    return str(folders[0]) if folders else None


@invoke.task(
    help={
        "target": "compas_timber, timber_arch or all (default)",
        "userobjects_folder": "Grasshopper's UserObjects folder (defaults to the Rhino 8 one); each package goes into its own subfolder.",
        "build": "Build the components first (default). Use --no-build to only copy the last build.",
    }
)
def install_gh_components(ctx, target="all", userobjects_folder=None, build=True):
    """Build the .ghuser components and install them into Grasshopper's UserObjects folder.

    Each package goes into its own folder, ``UserObjects/compas_timber`` and
    ``UserObjects/timber_arch``, whose contents are replaced, so components removed from the
    sources disappear on the next install.  Copies older installs left directly in
    ``UserObjects`` or in ``UserObjects/timber_design`` are deleted, so Grasshopper does not load
    them twice; other user objects are left alone.
    """
    import shutil

    userobjects_folder = userobjects_folder or _default_userobjects_folder()
    if not userobjects_folder or not os.path.isdir(userobjects_folder):
        raise invoke.Exit("Grasshopper UserObjects folder not found; pass --userobjects-folder.")

    targets = _targets(target)
    if build:
        build_gh_components(ctx, target=target, gh_io_folder=_cached_gh_io_folder())

    built = {t: sorted(Path(GH_TARGETS[t]["target_dir"]).glob("*.ghuser")) for t in targets}
    if not any(built.values()):
        raise invoke.Exit("No .ghuser files found to install; build them first.")

    # copies from older installs, directly in UserObjects: any of our components, and removed ones
    ours = set(GH_REMOVED_COMPONENTS)
    for cfg in GH_TARGETS.values():
        ours.update(path.name for path in Path(cfg["source_dir"]).iterdir() if path.is_dir())
    for stale in sorted(Path(userobjects_folder).glob("*.ghuser")):
        if stale.stem in ours:
            stale.unlink()
            print("Removed old copy: {}".format(stale.name))
    old_folder = Path(userobjects_folder) / OLD_USEROBJECTS_SUBFOLDER
    for old in ["core", "populator"] + list(GH_TARGETS):
        if (old_folder / old).is_dir():
            shutil.rmtree(old_folder / old)
            print("Removed old install folder: {}".format(old_folder / old))
    if old_folder.is_dir() and not any(old_folder.iterdir()):
        old_folder.rmdir()

    for t, files in built.items():
        destination = Path(userobjects_folder) / t
        if destination.is_dir():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        for ghuser in files:
            shutil.copy2(ghuser, destination)
        print("Installed {} components into {}".format(len(files), destination))
    print("Restart Grasshopper (or Rhino) if the updated components do not show up.")


@invoke.task(
    help={
        "target": "compas_timber, timber_arch or all (default)",
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
        "target": "compas_timber or timber_arch",
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
    install_gh_components,
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
