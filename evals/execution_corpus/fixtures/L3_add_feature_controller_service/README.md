# promogate

Promo-code validation for the checkout cart.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L3_add_feature_controller_service (implementation, L3)
- Task: Add promo code validation logic across cart_controller.py and promo_service.py
- Expected initial test outcome: FAIL (pytest exit status 1)
- The promo-code checks fail against the initial state, where
  `promo_service.validate_promo` never rejects anything and `cart_controller`
  applies a discount without consulting the service; they pass only once
  validation is implemented across `promo_service.py` and `cart_controller.py`.

## Contracts

- `promo_service.ACTIVE_CODES` maps each active promo code to its percentage
  discount (`SAVE10` → 10, `WELCOME20` → 20).
- `promo_service.validate_promo(code) -> str` strips surrounding whitespace,
  upper-cases the code, and raises `ValueError` when the result is empty, not
  alphanumeric, or not an active code; otherwise it returns the normalized code.
- `promo_service.discount_for(normalized_code) -> int` returns the discount of
  a normalized code, or `0` when the code is unknown.
- `cart_controller.apply_promo(cart, code) -> dict` returns a new cart dict
  carrying `discount` (percentage) and `promo_code` (normalized); when
  validation fails it raises `ValueError` and leaves the input cart untouched.
