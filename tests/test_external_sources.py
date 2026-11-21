"""Regression tests for rebuilding external sources in a reused checkout."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import combine
import download
import sources_list


class ExternalSourcesTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)
    self.external = self.root / 'external'
    self.local = self.root / 'local'
    self.external.mkdir()
    self.local.mkdir()
    self.app = sources_list.Source('app', 'https://example.test/app', '', sources_list.APP)
    self.collection = sources_list.Source('collection', 'https://example.test/list', '', sources_list.COLLECTION)
    self.addCleanup(patch.stopall)
    patch.object(download, 'destination_dir', str(self.external)).start()
    patch.object(combine, 'SOURCES_DIR', str(self.root)).start()

  def write_templates(self, path, *titles):
    path.write_text(json.dumps({'templates': [{'title': title} for title in titles]}))

  def run_download(self, sources, payload, error=None):
    with patch.object(sources_list, 'load', return_value=sources), \
         patch.object(sources_list, 'fetch_json', return_value=(payload, error)):
      download.main()

  def test_unavailable_app_does_not_reuse_old_download(self):
    self.write_templates(self.external / 'app.json', 'Old app')
    self.run_download([self.app], None, 'network failure')
    self.assertFalse((self.external / 'app.json').exists())
    self.assertEqual(combine.load_sources([self.app]), [])
    self.assertEqual(combine.missing_sources([self.app], sources_list.APP), ['app'])

  def test_invalid_empty_or_oversized_app_does_not_reuse_old_download(self):
    for payload in (None, {'templates': []}, {'templates': [{'title': 'A'}, {'title': 'B'}]}):
      with self.subTest(payload=payload):
        self.write_templates(self.external / 'app.json', 'Old app')
        self.run_download([self.app], payload)
        self.assertFalse((self.external / 'app.json').exists())

  def test_missing_collection_still_stops_download(self):
    self.write_templates(self.external / 'collection.json', 'Old collection')
    with self.assertRaises(SystemExit) as result:
      self.run_download([self.collection], None, 'network failure')
    self.assertEqual(result.exception.code, 1)
    self.assertFalse((self.external / 'collection.json').exists())
    self.assertEqual(combine.missing_sources([self.collection], sources_list.COLLECTION), ['collection'])

  def test_removed_source_is_ignored_even_by_standalone_combine(self):
    self.write_templates(self.external / 'removed.json', 'Removed')
    self.write_templates(self.external / 'app.json', 'Current')
    self.assertEqual([t['title'] for t in combine.load_sources([self.app])], ['Current'])

  def test_successful_download_replaces_old_data_and_cleans_removed_sources(self):
    self.write_templates(self.external / 'app.json', 'Old')
    self.write_templates(self.external / 'removed.json', 'Removed')
    self.run_download([self.app], {'title': 'Updated'})
    self.assertEqual([t['title'] for t in combine.load_sources([self.app])], ['Updated'])
    self.assertFalse((self.external / 'removed.json').exists())

  def test_local_templates_and_other_files_are_preserved(self):
    self.write_templates(self.local / 'mine.json', 'Local')
    (self.external / 'notes.txt').write_text('keep')
    self.run_download([self.app], {'title': 'External'})
    loaded = combine.load_sources([self.app])
    self.assertEqual({t['title']: t['_priority'] for t in loaded}, {'Local': 0, 'External': 1})
    self.assertTrue((self.local / 'mine.json').exists())
    self.assertEqual((self.external / 'notes.txt').read_text(), 'keep')

  def test_cleanup_failure_stops_before_downloading(self):
    self.write_templates(self.external / 'app.json', 'Old')
    with patch.object(sources_list, 'load', return_value=[self.app]), \
         patch.object(download.os, 'unlink', side_effect=PermissionError('denied')), \
         patch.object(sources_list, 'fetch_json') as fetch:
      with self.assertRaises(PermissionError):
        download.main()
      fetch.assert_not_called()


if __name__ == '__main__':
  unittest.main()
