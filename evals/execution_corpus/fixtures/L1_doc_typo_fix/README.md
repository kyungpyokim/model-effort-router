# notecaster

A tiny plain-text note renderer.

## Overview

This proejct reads markdown notes and renders them as clean paragraphs for the
command line. Notes live in a single directory; rendering is stateless.

## Usage

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L1_doc_typo_fix (implementation, L1)
- Task: Fix documentation typo in README.md
- Expected initial test outcome: FAIL (pytest exit status 1)
