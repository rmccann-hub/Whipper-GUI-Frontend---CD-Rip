# Test fixtures

Test data files consumed by `tests/test_*.py`. These are NOT pytest
fixtures — pytest fixtures (the `@pytest.fixture` kind) live in
`tests/conftest.py` and `tests/test_*.py` files themselves.

Each file here is a stable input that exercises one parser or one
adapter. Files are named `<subject>_<scenario>.{txt,log}`:

- `drive_list_*.txt` — parsed by `parsers/drive_list.py`
- `cd_info_*.txt` — parsed by `parsers/cd_info.py`
- `rip_log_*.log` — parsed by `parsers/rip_log.py`

The primary `rip_log_real_whipper_0_7.log` was pulled verbatim from
whipper-team/whipper master's own test suite (commit referenced inside
the file's "Log created by" line). The `rip_log_eac_reference.log`
is hand-authored from public EAC log documentation and exists only
as a reference for the format comparison in `docs/log-format-comparison.md`
— it is NOT consumed by any parser.

When T32 surfaces real-world output that differs from the fixtures,
update the fixtures here and regenerate the affected tests.
