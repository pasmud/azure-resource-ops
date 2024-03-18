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

Use `plan --exit-code` in automation to distinguish a nonempty plan (exit `4`)
from a no-op (exit `0`). Both outcomes write the same plan JSON as the default
mode, which exits `0` on any successful plan. Invalid input still exits `2`.

For a scoped rollout and recovery from partial application, see the
[two-subscription drift tutorial](examples/two-subscriptions/README.md).

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
- **Policy:** Requires `subscriptions` (nonempty, unique UUID list), `ensure`
  (desired string-valued tags), and `protected` (unique names; may be empty).
  Managed names match `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`. Tag values are at most
  256 characters with no controls. Names are compared case-insensitively; values
  are exact. Attempting to manage a protected name is an error. A merge sets
  only changed or missing managed tags; it never deletes tags. `""` sets an
  empty string, not a deletion.
- **Optional scope filters:** `resource_groups` and `resource_types` are
  nonempty lists of exact case-insensitive names. A resource must match its
  subscription and every supplied filter (any one entry within each list).
  Group names are matched within the approved subscriptions, including the
  group itself; subscription-level resources have no group. Use full ARM types
  such as `Microsoft.Storage/storageAccounts` or
  `Microsoft.Network/virtualNetworks/subnets`. A parent type does not match
  children. Extension resources match their final provider/type path; resource
  groups use `Microsoft.Resources/resourceGroups`. Both fields are derived from
  the resource ID, not inventory metadata. Empty lists, wildcards, duplicates,
  and unknown policy fields are errors. A valid filter with no matches plans no
  changes. Any filters are embedded in the plan and enforced during validation
  and apply.

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
Redacted reports identify their schema with `kind` and `report_version` (now
`2`). The `plan_audit` report has `status` `changes_planned` or `no_changes`.
These report fields do not change the version 1 plan format or canonical digest.

## Opt-in application

`python -m azure_resource_ops apply --help` shows the write interface without
calling Azure. The offline examples do not apply changes. The end-to-end tests
apply the synthetic plan only to an injected in-memory fake.

For an authorized operator on POSIX, `apply` requires a reviewed `--plan`, one
`--subscription` UUID per subscription in the policy (the set must match
exactly), and `--approve-sha256` from the audit of that reviewed plan. It uses
the `az` executable on `PATH` and its existing session with tag read and write
permissions limited to the intended resources. It does not log in or change
the active account. Use a trusted `PATH` and avoid secrets in tags; desired
tags are passed in process arguments and may be visible to local process
inspection or Azure CLI logging independently of these reports.

The adapter validates the whole plan and approvals before invoking `az`. For
each target in order, it runs a scoped tag read, checks the returned target
identity and full tag-map fingerprint, and recomputes the delta. Only a match
permits `az tag update` with `Merge` and only the delta assignments. Both calls
have explicit resource and subscription arguments. The runner uses an argument
vector with no shell, closed stdin, captured output, and a 60-second timeout per
command. The native adapter has not been tested against an Azure tenant.

**The tag read and write are not atomic.** The CLI merge path does not supply
an ETag precondition. A concurrent change after the read to a managed value can
be overwritten, and an identical tag map cannot distinguish a resource that
was deleted and recreated at the same ID. Azure permissions, resource tag
limits and service-specific constraints can also reject a merge. Use a recent
snapshot and coordinate with other tag writers. The tool stops at the first
failure, does not roll back earlier writes, and does not retry. A timeout or
Ctrl-C during a command stops the run and produces an incomplete report. An
interrupted write may still take effect server-side. Reconcile live state and
make a fresh plan before resuming.

Apply outputs a redacted JSON report with the plan digest, counts, and ordered
change numbers. It never prints captured Azure CLI output or arguments. Exit
`0` means each merge exited successfully (or none were needed); exit `2` means
invalid input or approval; exit `3` means an incomplete apply with a report.
The `plan_apply` report has `status` `applied`, `no_changes`, or `incomplete`;
`complete` remains true for the first two outcomes. `applied` records CLI success,
not verified live state.
Per-change statuses are `merged` (CLI success, no read-back), `read_failed`
(CLI error), `invalid_read` (unexpected response), `stale` (snapshot or delta
mismatch), `merge_unconfirmed` (write did not return success; outcome may be
unknown), and `not_attempted` (after an earlier failure).
A failed command also records a fixed `reason`: `timeout`, `interrupted`,
`nonzero_exit`, or `runner_error` (for example, a missing executable). No raw
exception text or process output is included.

## Install and develop

The offline CLI has no runtime dependencies beyond Python 3.11+. In a virtual
environment, `python -m pip install .` installs the `azure-resource-ops` command
as an alternative to `python -m azure_resource_ops`. To run the project checks:

```sh
python -m pip install '.[dev]'
ruff check azure_resource_ops tests
python -m pytest -q
```

GitHub Actions runs lint, the offline suite, and an installed-command smoke
test on Python 3.11 and 3.14 on pushes and pull requests.
