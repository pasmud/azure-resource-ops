# Azure Resource Ops

Plan policy-driven Azure tag merges from saved inventory. The planner is offline
and preserves unrelated and protected tags.

## Offline CLI

Run `python -m azure_resource_ops --help` from the checkout with Python 3.11 or
newer. `plan` takes `--inventory` and `--policy` paths to UTF-8 JSON files. It
prints deterministic versioned plan JSON to stdout. Invalid input exits with
status 2 and a diagnostic on stderr. Planning requires no Azure CLI, network,
or credentials.
