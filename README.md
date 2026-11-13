# timber_design

Automation toolkit for the design of timber structures based on COMPAS timber.

This repository is a monorepo containing three independently released packages:

| Package | Contents | Depends on |
|---|---|---|
| [`compas_timber_rules`](packages/compas_timber_rules) | Joint-rule workflow (`DirectRule`, `CategoryRule`, `TopologyRule`, `CompositeRule`, `JointRuleSolver`) | `compas_timber` |
| [`compas_timber_populator`](packages/compas_timber_populator) | `PanelPopulator`, populator agents, 2D connection solver | `compas_timber_rules` |
| [`compas_timber_gh`](packages/compas_timber_gh) | Grasshopper helpers and the sources of the **core** and **populator** Yak packages | `compas_timber_rules` |

## Installation

```bash
pip install compas_timber_rules          # joint rules only
pip install compas_timber_populator      # panel populator (pulls in compas_timber_rules)
```

In Rhino 8, install the `compas_timber` package (core components) from the Package Manager, and additionally
`compas_timber_populator` for the panel populator components. The populator package requires the core package.

## Development

```bash
git clone https://github.com/gramaziokohler/timber_design.git
cd timber_design
uv sync --all-packages --extra dev      # or: pip install -e ".[dev]"
```

Useful tasks:

```bash
invoke test                                         # tests of all packages
invoke build-gh-components --target core|populator  # build .ghuser files into dist/ghuser/<target>
invoke update-gh-headers --target core|populator    # rewrite `# r:` headers (use --dev for local sources)
invoke yakerize-gh --target core|populator          # build a Yak package
```

Each package is versioned independently: run `bump-my-version bump <part>` inside `packages/<name>`.
That creates a `rules-v*`, `populator-v*` or `gh-v*` tag, which triggers the PyPI release of that package only.

## Documentation

For further "getting started" instructions, a tutorial, examples, and an API reference,
please check out the online documentation here: [timber_design docs](https://gramaziokohler.github.io/timber_design)

## Issue Tracker

If you find a bug or if you have a problem with running the code, please file an issue on the [Issue Tracker](https://github.com/gramaziokohler/timber_design/issues).
