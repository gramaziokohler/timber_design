# Installation

## User

!!! note
    While there are many similar tools, we recommend using `uv` to manage your Python environments.
    It can be installed from [here](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv venv <myenvname> --python 3.13
source <myenvname>/bin/activate
uv pip install compas_timber_rules        # joint rules
uv pip install compas_timber_populator    # panel populator (includes compas_timber_rules)
```

## Developer

If you wish to contribute to or modify timber_design, [fork the repository](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/fork-a-repo) and clone the fork

```bash
git clone https://github.com/<yourgithub_username>/timber_design.git
cd timber_design
```

Create a new environment if necessary

```bash
uv venv <myenvname> --python 3.13
source <myenvname>/bin/activate
```

Install all three workspace packages (`compas_timber_rules`, `compas_timber_populator`, `compas_timber_gh`) in editable mode with the development dependencies

```bash
uv sync --all-packages --extra dev
```

To compile the Rhino8 Grasshopper components (core and populator add-on)

```bash
invoke build-gh-components            # or --target core / --target populator
```
