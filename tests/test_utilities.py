import os
import unittest
from clusterrunner.lib import utilities as util

# Path to the temporary dummy scripts directory
DUMMY_SCRIPT_DIR = os.path.join(os.path.dirname(__file__), 'dummy_scripts')
CLI_SCRIPT_PATH = os.path.join(DUMMY_SCRIPT_DIR, 'cli_script.py')
NO_ARGPARSE_PATH = os.path.join(DUMMY_SCRIPT_DIR, 'no_argparse.py')


class TestScriptUtilities(unittest.TestCase):
    """Tests utility functions for script finding and argument parsing."""

    def test_find_possible_scripts_success(self):
        """Tests finding .py files in a valid directory."""
        files = util.find_possible_scripts(DUMMY_SCRIPT_DIR)
        # Check if the list contains our dummy scripts
        self.assertIn('cli_script.py', files)
        self.assertIn('no_argparse.py', files)
        self.assertEqual(len(files), 2)
        self.assertIsInstance(files, list)

    def test_get_script_arguments_cli_script(self):
        """Tests parsing a script with complex argparse arguments."""
        arguments, has_argparse = util.get_script_arguments(CLI_SCRIPT_PATH)
        self.assertTrue(has_argparse, "Should detect argparse usage.")
        self.assertEqual(len(arguments), 3, "Should find exactly 3 arguments.")
        # Test 1: required string arg
        arg1 = arguments[0]
        self.assertEqual(arg1[0], '-f', "Raw flag should be '-f'.")
        self.assertEqual(arg1[3], str, "Type should be str.")
        self.assertTrue(arg1[4], "Required should be True.")
        # Test 2: arg with int type/default
        arg2 = arguments[1]
        self.assertEqual(arg2[1], 'count', "Clean name should be 'count'.")
        self.assertEqual(arg2[3], int, "Type should be int.")
        self.assertEqual(arg2[5], 10, "Default value should be 10.")
        arg3 = arguments[2]
        self.assertEqual(arg3[1], 'v', "Clean name should be 'v'.")
        self.assertEqual(arg3[5], False, "Default value should be False.")

    def test_get_script_arguments_no_argparse_script(self):
        """Tests parsing a script that lacks argparse definition."""
        arguments, has_argparse = util.get_script_arguments(NO_ARGPARSE_PATH)
        self.assertFalse(has_argparse, "Should not detect argparse usage.")
        self.assertEqual(len(arguments), 0, "Should find 0 arguments.")
