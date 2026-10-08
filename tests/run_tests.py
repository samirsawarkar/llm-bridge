#!/usr/bin/env python3
"""Run all unit tests in tests directory."""

import os
import sys
import unittest
import tempfile

def main():
    test_dir = os.path.dirname(os.path.abspath(__file__))
    # Establish isolation before discovery imports CLI/provider modules and store.
    with tempfile.TemporaryDirectory(prefix="llm-bridge-tests-") as home:
        os.environ["LLM_BRIDGE_HOME"] = home
        loader = unittest.TestLoader()
        suite = loader.discover(start_dir=test_dir, pattern="test_*.py")
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

if __name__ == "__main__":
    main()
