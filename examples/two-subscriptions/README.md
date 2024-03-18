# Recover from drift in a two-subscription rollout

This offline lab uses fictional billing infrastructure split between two
subscriptions. The policy standardizes `Environment` and `CostCenter` on storage
accounts in `rg-settlement-data` in both subscriptions. It preserves `Owner` and
unrelated tags. A storage account in another group and a vault in the right
group are both out of scope. The lab requires Python 3.11+ and a POSIX shell, and
never runs `apply` or Azure CLI.

From the repository root, create and verify a reviewed plan. `--exit-code`
returns `4` because both storage accounts need changes. Audit reports two
scoped subscriptions, two targeted subscriptions, two resources, and three tag
assignments.

```sh
(
  set -eu
  lab=$(mktemp -d)
  trap 'rm -rf "$lab"' EXIT
  demo=examples/two-subscriptions
  py=${PYTHON:-python}

  code=0
  "$py" -m azure_resource_ops plan --inventory "$demo/before.json" \
    --policy "$demo/policy.json" --exit-code > "$lab/reviewed.json" || code=$?
  [ "$code" -eq 4 ]
  "$py" -m azure_resource_ops validate --plan "$lab/reviewed.json" --inventory "$demo/before.json"
  "$py" -m azure_resource_ops audit --plan "$lab/reviewed.json"

  code=0
  "$py" -m azure_resource_ops validate --plan "$lab/reviewed.json" \
    --inventory "$demo/refreshed.json" || code=$?
  [ "$code" -eq 2 ]

  "$py" -m azure_resource_ops plan --inventory "$demo/refreshed.json" \
    --policy "$demo/policy.json" > "$lab/replanned.json"
  "$py" -m azure_resource_ops validate --plan "$lab/replanned.json" --inventory "$demo/refreshed.json"
  "$py" -m azure_resource_ops audit --plan "$lab/replanned.json"
)
```

`refreshed.json` simulates recovery after the first merge succeeded and a
separate operator changed the second account's `Owner` tag. The old plan no
longer matches the snapshot: the first account is already converged, and the
second account's full tag fingerprint has changed. Even though `Owner` is
protected and the intended assignment for account two is unchanged, a
just-in-time read would mark that target `stale` and skip the write.

The refreshed audit keeps both subscriptions in policy scope but targets only
one subscription, one resource, and one assignment. Review the new plan and
use its new digest for any later approval. For a real rollout, reconcile any
unconfirmed writes with a fresh snapshot before replanning. Do not replay or
hand-edit the previous plan, and remember that apply still requires approval
for **both** policy subscriptions even when only one has remaining work.
