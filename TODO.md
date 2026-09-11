# TODO

## Open

### Architecture / modularity

| id | status | severity | effort | description |
|---|---|---|---|---|
| ARCH-036 | open | medium | small | Architecture/public typing boundary: the annotated extension API is checked only inside the checkout (`pyproject.toml`, `.github/workflows/ci.yml`); the package has no py.typed marker. In an isolated installed-package layout, mypy reports import-untyped and reveals api.Engine as Any, missing an invalid string seed argument. Adding the marker in that isolated copy restores the expected argument error. Publish the inline typing marker and add an installed-artifact consumer check that exercises public generator/transform/validator contracts, accepts valid implementations, and rejects invalid API calls. Verify the marker is included in the wheel rather than relying only on source-tree type checks. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|
| DOC-044 | blocked | low | small | Documentation/policy: the session-supplied AGENTS.md instructions require every contradiction to be blocked, while checked-in AGENTS.md Rules classify known bugs with clear expected behavior as open and reserve blocked for unavailable prerequisites. These sources give conflicting ledger instructions despite the maintainer's earlier request to revise the rule. Align the supplied instruction source with the approved readiness-based policy; unblock when that external instruction source is updated or its replacement is explicitly established. This policy-source synchronization does not prevent implementing the independently actionable findings above. |

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
