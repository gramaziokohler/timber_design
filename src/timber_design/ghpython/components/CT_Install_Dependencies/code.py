
# r: timber_design>=0.2.0
# flake8: noqa
import Grasshopper  # type: ignore

import glob
import importlib
import os
import re
import shutil
import sys

try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata


REQUIRED = [
    "timber_design>=0.2.0",
    "compas_timber>=2.1.1-rc1",
    "compas>=2.15.1",
]


class InstallDependencies(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore  # noqa: F821

    def RunScript(self):
        # 1) Detect Rhino's default site-env folder used by # r installs.
        active_env = self._latest_default_env()
        active_env_name = os.path.basename(active_env) if active_env else "default-*"

        # 2) Make sure this env is the first import location for the current GH session.
        self._activate(active_env)

        # 3) Check package versions before cleanup to report updates.
        before_all_versions = self._all_versions_map(active_env)

        # 4) Keep only the newest dist-info per required package.
        cleanup_errors = self._cleanup_old_dist_infos(active_env)

        # 5) Re-check versions and import origins after cleanup.
        after_all_versions = self._all_versions_map(active_env)
        versions = self._versions(active_env)
        missing = self._missing_specs(active_env)
        import_issues = self._import_origin_issues(active_env)

        lines = ["Active env: {}".format(active_env)]

        updates = []
        for name in sorted(after_all_versions.keys()):
            old_list = before_all_versions.get(name, [])
            new_list = after_all_versions.get(name, [])
            if old_list != new_list:
                updates.append("{}: [{}] -> [{}]".format(name, ", ".join(old_list), ", ".join(new_list)))
        # Report only when cleanup changed detected package versions.
        if updates:
            lines.append("Updated versions:")
            lines.extend(updates)

        if missing:
            lines.append("Missing requirements: {}".format(", ".join(missing)))
        if import_issues:
            lines.append("Import path issues: {}".format("; ".join(import_issues)))
        if cleanup_errors:
            lines.append("Cleanup warnings: {}".format("; ".join(cleanup_errors)))

        self.component.Message = "Ready"
        # Any missing requirement or wrong import origin means manual reset is needed.
        if missing or import_issues:
            self.component.Message = "Error"
            lines.append("Close Rhino and delete {} folder, run again.".format(active_env_name))

        return versions, "\n".join(lines)

    def _latest_default_env(self):
        site_envs = os.path.join(sys.prefix, "site-envs")
        envs = glob.glob(os.path.join(site_envs, "default-*"))
        if not envs:
            return None
        return envs[0]

    def _activate(self, site_env):
        self._prioritize_active_env(site_env)
        importlib.invalidate_caches()

    def _prioritize_active_env(self, active_env):
        active_norm = self._norm(active_env)
        kept = []
        for path in list(sys.path):
            if not path:
                continue
            path_norm = self._norm(path)
            if path_norm == active_norm:
                continue
            if self._is_default_site_env(path_norm):
                continue
            kept.append(path)
        sys.path[:] = [active_env] + kept

    def _is_default_site_env(self, path_norm):
        marker = "{}site-envs{}default-".format(os.sep, os.sep)
        return marker in path_norm

    def _norm(self, path):
        return os.path.normcase(os.path.normpath(os.path.abspath(path)))

    def _is_under(self, path, root):
        path_norm = self._norm(path)
        root_norm = self._norm(root)
        return path_norm == root_norm or path_norm.startswith(root_norm + os.sep)

    def _versions(self, site_env):
        out = []
        for name in self._required_names():
            ver = self._installed_version(name, site_env)
            out.append("{}=={}".format(name, ver) if ver else "{} (missing)".format(name))
        return out

    def _required_names(self):
        return [self._name(spec) for spec in REQUIRED]

    def _missing_specs(self, site_env):
        return [spec for spec in REQUIRED if not self._is_satisfied(spec, site_env)]

    def _installed_version(self, name, site_env):
        versions = [v for v, _ in self._installed_distributions(name, site_env)]
        if not versions:
            return None

        best = versions[0]
        for v in versions[1:]:
            if self._compare(v, best) > 0:
                best = v
        return best

    def _installed_distributions(self, name, site_env):
        wanted = name.lower().replace("-", "_")
        found = []
        try:
            for dist in importlib_metadata.distributions(path=[site_env]):
                meta_name = (dist.metadata["Name"] or "").lower().replace("-", "_")
                if meta_name == wanted:
                    found.append((dist.metadata["Version"], dist))
        except Exception:
            pass
        return found

    def _all_versions_map(self, site_env):
        out = {}
        for name in self._required_names():
            versions = [v for v, _ in self._installed_distributions(name, site_env)]
            unique_versions = []
            for version in versions:
                if version not in unique_versions:
                    unique_versions.append(version)
            unique_versions.sort(key=self._version_key)
            out[name] = unique_versions
        return out

    def _cleanup_old_dist_infos(self, site_env):
        errors = []
        for name in self._required_names():
            pkg_errors = self._prune_old_dist_infos(name, site_env)
            errors.extend(pkg_errors)
        return errors

    def _required_modules(self):
        modules = []
        seen = set()
        for name in self._required_names():
            module_name = name.replace("-", "_")
            if module_name not in seen:
                seen.add(module_name)
                modules.append(module_name)
        return modules

    def _unload_module_tree(self, root_module):
        for name in list(sys.modules.keys()):
            if name == root_module or name.startswith(root_module + "."):
                sys.modules.pop(name, None)

    def _import_origin_issues(self, active_env):
        issues = []

        for module_name in self._required_modules():
            self._unload_module_tree(module_name)
            try:
                module = importlib.import_module(module_name)
                module_file = getattr(module, "__file__", None) or "<unknown>"
                if module_file != "<unknown>" and not self._is_under(module_file, active_env):
                    issues.append("{} -> {}".format(module_name, module_file))
            except Exception as e:
                issues.append("{} ({})".format(module_name, e))

        return issues

    def _prune_old_dist_infos(self, name, site_env):
        dists = self._installed_distributions(name, site_env)
        if len(dists) <= 1:
            return []

        best_idx = 0
        for i in range(1, len(dists)):
            if self._compare(dists[i][0], dists[best_idx][0]) > 0:
                best_idx = i
        errors = []

        for i, (version, dist) in enumerate(dists):
            if i == best_idx:
                continue
            path = getattr(dist, "_path", None)
            if not path:
                continue
            path = str(path)
            if not path.lower().endswith(".dist-info"):
                continue
            try:
                shutil.rmtree(path)
            except Exception as e:
                errors.append("{}=={} ({})".format(name, version, e))

        return errors

    def _is_satisfied(self, spec, site_env):
        name, constraint = self._split(spec)
        installed = self._installed_version(name, site_env)
        if installed is None:
            return False
        if not constraint:
            return True
        if constraint.startswith("=="):
            return installed == constraint[2:].strip()
        if constraint.startswith(">="):
            return self._compare(installed, constraint[2:].strip()) >= 0
        return False

    def _name(self, spec):
        m = re.match(r"^([A-Za-z0-9_.-]+)", spec)
        return m.group(1) if m else spec

    def _split(self, spec):
        m = re.match(r"^([A-Za-z0-9_.-]+)(.*)$", spec.strip())
        return (m.group(1), m.group(2).strip()) if m else (spec, "")

    def _compare(self, left, right):
        a = self._version_key(left)
        b = self._version_key(right)
        for x, y in zip(a, b):
            if x == y:
                continue
            if isinstance(x, int) and isinstance(y, int):
                return -1 if x < y else 1
            return -1 if str(x) < str(y) else 1
        return 0 if len(a) == len(b) else (-1 if len(a) < len(b) else 1)

    def _version_key(self, version):
        return [int(p) if p.isdigit() else p for p in re.findall(r"\d+|[A-Za-z]+", version)]

