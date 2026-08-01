# Build and Test

1. Compile after modifying Rust: `PYO3_PYTHON="$PWD/py-hftbacktest/.venv/bin/python" cargo build -p py-hftbacktest`
2. Update the local Python extension: `cp target/debug/libhftbacktest.dylib py-hftbacktest/hftbacktest/_hftbacktest.cpython-313-darwin.so`
3. Run Rust tests: `cargo test -p hftbacktest --lib`
4. Run Python tests: `PYTHONPATH="$PWD/py-hftbacktest:$PWD/py-hftbacktest/tests" py-hftbacktest/.venv/bin/python -m unittest discover -s py-hftbacktest/tests -p "test_*.py"`

# Release

1. Update the version in `py-hftbacktest/pyproject.toml` and `py-hftbacktest/hftbacktest/__init__.py`.
2. Commit and push the changes, then have the agent run `Release Python` in GitHub Actions without waiting for it to finish.
3. Have the agent create the GitHub Release and write the release notes immediately after triggering the workflow.
