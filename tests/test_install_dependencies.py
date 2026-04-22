import importlib.util
import os
import sys
import types


def _load_install_dependencies_module():
    module_name = "_ct_install_dependencies_code"
    if module_name in sys.modules:
        return sys.modules[module_name]

    # Minimal Grasshopper stub so the component module can be imported in pytest.
    grasshopper = types.ModuleType("Grasshopper")
    grasshopper.Kernel = types.SimpleNamespace(
        GH_ScriptInstance=object,
        GH_RuntimeMessageLevel=types.SimpleNamespace(Error="Error"),
    )
    sys.modules.setdefault("Grasshopper", grasshopper)

    file_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "timber_design",
        "ghpython",
        "components",
        "CT_Install_Dependencies",
        "code.py",
    )
    file_path = os.path.abspath(file_path)

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _installer():
    module = _load_install_dependencies_module()
    return module.InstallDependencies()


def test_compare_stable_is_newer_than_prerelease():
    installer = _installer()

    assert installer._compare("2.1.1", "2.1.1rc1") > 0
    assert installer._compare("2.1.1", "2.1.1-rc1") > 0


def test_is_satisfied_greater_equal_with_final_release(monkeypatch):
    installer = _installer()

    monkeypatch.setattr(installer, "_installed_version", lambda name, site_env: "2.1.1")

    assert installer._is_satisfied("compas_timber>=2.1.1-rc1", "dummy-env") is True


def test_is_satisfied_greater_equal_with_older_prerelease(monkeypatch):
    installer = _installer()

    monkeypatch.setattr(installer, "_installed_version", lambda name, site_env: "2.1.0rc1")

    assert installer._is_satisfied("compas_timber>=2.1.1-rc1", "dummy-env") is False


def test_installed_version_selects_best_from_multiple(monkeypatch):
    installer = _installer()

    versions = [
        ("2.1.0", object()),
        ("2.1.1-rc1", object()),
        ("2.1.1", object()),
    ]
    monkeypatch.setattr(installer, "_installed_distributions", lambda name, site_env: versions)

    assert installer._installed_version("compas_timber", "dummy-env") == "2.1.1"
