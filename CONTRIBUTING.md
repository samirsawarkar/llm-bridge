# Contributing to LLM Bridge

Thank you for your interest in contributing to **LLM Bridge**! We welcome bug reports, improvements, documentation, and feature requests.

## Design Philosophy

Before submitting a change, keep our core architectural principles in mind:

1. **Zero External Dependencies:**
   The entire bridge runtime must run on Python 3.8+ standard library alone (`urllib`, `http.server`, `json`, `sqlite3`, `subprocess`, `argparse`). Do not add external dependencies to `install_requires`.
2. **Minimal & Edge-Case-Correct:**
   Keep diffs clean, maintainable, and focused on root causes rather than symptoms.
3. **Safety & Loopback Security:**
   The proxy binds to `127.0.0.1` by default and manages local agent credentials securely.

---

## Local Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/samirsawarkar/llm-bridge.git
   cd llm-bridge
   ```

2. **Install in editable mode:**
   ```bash
   pip install -e .
   ```

3. **Verify CLI availability:**
   ```bash
   llm-bridge --help
   ```

---

## Running the Test Suite

We use Python's built-in `unittest` framework (no external test runner needed):

```bash
python3 tests/run_tests.py
```

Or via unittest auto-discovery:
```bash
python3 -m unittest discover tests
```

Every pull request must pass 100% of unit tests. When adding new features or addressing quirks (such as schema conversions or model mapping), add corresponding test cases under `tests/`.

---

## Coding Standards

- **Formatting:** Clean PEP 8 formatting.
- **Python Compatibility:** Must run on Python 3.8, 3.9, 3.10, 3.11, and 3.12.
- **Commit Messages:** Follow [Conventional Commits](https://www.conventionalcommits.org/):
  - `feat: add support for new Claude model variant`
  - `fix: handle protobuf array item nullability in schema parser`
  - `docs: update Hermes integration guide`
  - `test: add unit test for thought signature fallback`

---

## Submitting a Pull Request

1. Fork the repository on GitHub.
2. Create a feature branch: `git checkout -b feature/my-feature`.
3. Write your code and add unit tests.
4. Run `python3 tests/run_tests.py` to verify all tests pass.
5. Push to your fork and submit a Pull Request against `main`.
6. Our GitHub Actions CI will automatically test your PR across multiple operating systems and Python versions.

---

## Questions & Discussions

Have questions? Feel free to open a [GitHub Discussion](https://github.com/samirsawarkar/llm-bridge/discussions) or submit an issue on the [Issue Tracker](https://github.com/samirsawarkar/llm-bridge/issues).
