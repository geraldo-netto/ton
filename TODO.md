# TODO

## Open

### Reliability / correctness

| id | status | severity | effort | description |
|---|---|---|---|---|
| REL-050 | open | low | small | Reliability/correctness: correct `tests/test_registry.py::EXPECTED_TYPES` and `test_make_registry_covers_every_expected_type`. The list omits two composites and the subset assertion/comment still describe removed live-subclass discovery. Assert the exact built-in catalog, including `oneOf` and `sequence_of`, so unexpected registrations cannot pass unnoticed. |

## Blocked / Deferred

| id | status | severity | effort | description |
|---|---|---|---|---|

## Rejected / Won't fix

| id | status | severity | effort | description |
|---|---|---|---|---|
| PLAT-015 | wont_fix | high | small | Platform: Windows CI verification of the POSIX-only test skip and remaining suite is not required by maintainer decision. |
