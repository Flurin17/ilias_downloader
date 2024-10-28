import unittest
import os
import json
from unittest.mock import patch, MagicMock
from main import (
    create_session,
    sanitize_filename,
    get_filename_from_cd,
    load_cookies_from_file
)

class TestIliasDownloader(unittest.TestCase):
    def setUp(self):
        self.test_cookies = [
            {"name": "PHPSESSID", "value": "test_session"},
            {"name": "ilClientId", "value": "test_client"}
        ]

    def test_create_session(self):
        session = create_session(self.test_cookies)
        self.assertEqual(
            session.cookies.get('PHPSESSID'),
            'test_session'
        )
        self.assertEqual(
            session.cookies.get('ilClientId'),
            'test_client'
        )

    def test_sanitize_filename(self):
        test_cases = [
            ('file:name*.txt', 'file_name_.txt'),
            ('path/to/file', 'path_to_file'),
            ('normal.pdf', 'normal.pdf'),
            ('file<with>special:chars', 'file_with_special_chars')
        ]
        for input_name, expected in test_cases:
            self.assertEqual(sanitize_filename(input_name), expected)

    def test_get_filename_from_cd(self):
        test_cases = [
            ('attachment; filename="test.pdf"', 'test.pdf'),
            ('inline; filename=doc.txt', 'doc.txt'),
            (None, None),
            ('invalid_header', None)
        ]
        for input_cd, expected in test_cases:
            self.assertEqual(get_filename_from_cd(input_cd), expected)

    @patch('builtins.open')
    def test_load_cookies_from_file(self, mock_open):
        # Test successful load
        mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(self.test_cookies)
        cookies = load_cookies_from_file('cookies.json')
        self.assertEqual(cookies, self.test_cookies)

        # Test file not found
        mock_open.side_effect = FileNotFoundError()
        with self.assertLogs(level='ERROR') as log:
            cookies = load_cookies_from_file('nonexistent.json')
            self.assertIsNone(cookies)
            self.assertIn('Cookie file not found:', log.output[0])

if __name__ == '__main__':
    unittest.main()
