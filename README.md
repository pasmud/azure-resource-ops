# Azure Resource Ops

Plan policy-driven Azure tag merges from saved inventory. The planner is offline
and preserves unrelated and protected tags.

## Offline walkthrough

From the checkout with Python 3.11 or newer:

```sh
mkdir -p local
python -m azure_resource_ops plan --inventory examples/inventory.graph.json \
  --policy examples/policy.json > local/plan.json
python -m azure_resource_ops validate --plan local/plan.json \
  --inventory examples/inventory.graph.json
python -m azure_resource_ops audit --plan local/plan.json
```

All inputs in `examples/` are synthetic. The plan changes two targets, leaves
an already-converged resource alone, and skips a resource in another
subscription. Compare the final output to `examples/audit.expected.json`.
These three commands require no Azure CLI, network, or credentials. Successful
commands write JSON to stdout; invalid input exits 2 with a short diagnostic on
stderr and no JSON output. `--help` describes the available flags.

### Inputs and merge semantics

- **Inventory:** UTF-8 JSON array as saved from `az resource list`, or a
  Resource Graph object-array envelope with a `data` array. Rows must contain
  `id` and `tags` (a string-to-string object or `null` for untagged). If present,
  `subscriptionId` or `subscription_id` must agree with the resource ID.
  Explicit truncation, continuation tokens, inconsistent counts, and duplicate
  resource IDs are errors. Combine all intended pages before planning. A bare
  array gives no way to discover missing pages; table-format Graph results are
  unsupported.
- **Resource IDs:** Subscription-qualified ARM resource groups and resources,
  including child and extension paths. Subscription roots, query parameters,
  encoded segments, and empty or relative path segments are rejected. ID
  segments are limited to ASCII letters, digits, and `_().:@+~-`.
- **Policy:** Exactly `subscriptions` (nonempty, unique UUID list), `ensure`
  (desired string-valued tags), and `protected` (unique names; may be empty).
  Managed names match `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`. Tag values are at most
  256 characters with no controls. Names are compared case-insensitively; values
  are exact. Attempting to manage a protected name is an error. A merge sets
  only changed or missing managed tags; it never deletes tags. `""` sets an
  empty string, not a deletion.

### Plan and audit artifacts

Plan version 1 includes the effective policy and only changed, in-scope targets,
sorted by case-insensitive resource ID. Each change has an `id`, a `merge` map,
and `before_sha256`: the SHA-256 of the entire prior tag map with case-folded
keys, sorted and encoded as compact ASCII-escaped JSON. The plan does not store
old tag values. It **does** contain resource IDs and desired tags; keep plans
and inventory private and never store secrets in tags.

`validate` checks schema, scope, and merge invariants. With `--inventory`, it
also regenerates the plan from that snapshot and the embedded policy to catch
missing or altered changes. It does not authenticate who wrote the plan or
establish that the inventory is current. Review the effective policy before use.

`audit` reports counts, a canonical plan SHA-256, and per-change counts by
one-based position in resource-ID order. It omits resource and subscription
IDs, tag names and values, and individual snapshot fingerprints. The digest
identifies the normalized plan, not its author; the report still reveals counts.
