# timber_design

Automation toolkit for the design of timber structures based on COMPAS timber.

The `timber_design` distribution contains three top-level packages:

| Package | Contents |
|---|---|
| [`timber_design_rules`](src/timber_design_rules) | Joint-rule workflow (`DirectRule`, `CategoryRule`, `TopologyRule`, `CompositeRule`, `JointRuleSolver`) |
| [`timber_design_populator`](src/timber_design_populator) | `PanelPopulator`, populator agents, 2D connection solver (depends on `timber_design_rules`) |
| [`timber_design_gh`](src/timber_design_gh) | Grasshopper helpers and the sources of the **core** and **populator** Yak packages |

## Installation

Stable releases can be installed from PyPI.

```bash
pip install timber_design
```

In Rhino 8, install the `compas_timber` package (core components) from the Package Manager, and additionally
`timber_design_populator` for the panel populator components. The populator package requires the core package.

To install the latest version for development, do:

```bash
git clone https://github.com/gramaziokohler/timber_design.git
cd timber_design
pip install -e ".[dev]"
```

Grasshopper tasks:

```bash
invoke build-gh-components --target core|populator  # build .ghuser files into dist/ghuser/<target>
invoke update-gh-headers --target core|populator    # rewrite `# r:` headers (use --dev for the local src folder)
invoke yakerize-gh --target core|populator          # build a Yak package
```

## Documentation

For further "getting started" instructions, a tutorial, examples, and an API reference,
please check out the online documentation here: [timber_design docs](https://gramaziokohler.github.io/timber_design)

## Issue Tracker

If you find a bug or if you have a problem with running the code, please file an issue on the [Issue Tracker](https://github.com/gramaziokohler/timber_design/issues).
