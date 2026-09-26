# invoicing

Order and account invoicing split across a `core` and a `billing` module.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L4_cross_module_refactor (architectural_refactoring, L4)
- Task: Move billing helpers from core module to billing module and update call sites
- Expected initial test outcome: FAIL (pytest exit status 1)
- The billing behavior checks stay green on the initial state while the
  module-boundary check fails: `apply_tax` and `format_invoice_total` are
  still defined in `core.py` and the call sites still import them from
  `core`. The boundary check passes only after the helpers live in
  `billing.py` and every call site imports them from `billing`.

## Contracts

- `billing.py` owns the billing helpers `apply_tax(amount, rate)` and
  `format_invoice_total(invoice)`; no other module defines them.
- `orders.py` and `accounts.py` are the call sites: they import both helpers
  from `billing`, not from `core`.
- `core.py` keeps its own non-billing utility (`slugify`) — moving or
  deleting core functionality is not part of the task.
- Behavior is unchanged by the refactor: `apply_tax` rounds to two decimals,
  `format_invoice_total` renders `"<currency> <total>"`, and the helpers stay
  reachable through the call-site modules (`orders.apply_tax`,
  `accounts.format_invoice_total`, ...).
