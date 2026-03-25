# Installation

## User

!!! note
    While there are many similar tools, we recommend using `uv` to manage your Python environments.
    It can be installed from [here](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv venv <myenvname> --python 3.13
source <myenvname>/bin/activate
uv pip install compas_timber
```

## Developer

If you wish to contribute to or modify COMPAS Timber, [fork the repository](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/fork-a-repo) and clone the fork

```bash
git clone https://github.com/<yourgithub_username>/compas_timber.git
cd compas_timber
```

Create a new environment if necessary

```bash
uv venv <myenvname> --python 3.13
source <myenvname>/bin/activate
```

Install the package in editable mode with its development dependencies

```bash
uv pip install -e ".[dev]"
```

To compile the Rhino8 Grasshopper components

```bash
invoke build-cpython-ghuser-components
```
