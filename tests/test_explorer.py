import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.explorer import FileExplorer, ExplorerError


class TestFileExplorer(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='serverpy_recovery_')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.explorer = FileExplorer(self.root)

    def assert_error(self, status, operation, *args):
        with self.assertRaises(ExplorerError) as caught:
            operation(*args)
        self.assertEqual(caught.exception.status, status)

    def test_trash_survives_restart_and_restores_content(self):
        source = self.root / 'ação # 100%20.txt'
        source.write_text('recover me', encoding='utf-8')
        item = self.explorer.trash('/' + source.name)
        self.assertFalse(source.exists())
        restarted = FileExplorer(self.root)
        self.assertEqual(restarted.list_trash()[0]['path'], '/' + source.name)
        restarted.restore(item['id'])
        self.assertEqual(source.read_text(encoding='utf-8'), 'recover me')
        self.assertEqual(restarted.list_trash(), [])

    def test_folder_restores_children_and_recreates_missing_parent(self):
        source = self.root / 'parent' / 'folder'
        source.mkdir(parents=True)
        (source / 'child.txt').write_text('child')
        item = self.explorer.trash('/parent/folder/')
        source.parent.rmdir()
        self.explorer.restore(item['id'])
        self.assertEqual((source / 'child.txt').read_text(), 'child')

    def test_restore_conflict_keeps_both_files(self):
        source = self.root / 'file.txt'
        source.write_text('old')
        item = self.explorer.trash('/file.txt')
        source.write_text('new')
        self.assert_error(409, self.explorer.restore, item['id'])
        self.assertEqual(source.read_text(), 'new')
        self.assertEqual(self.explorer.list_trash()[0]['id'], item['id'])

    def test_undo_move_survives_restart(self):
        (self.root / 'source.txt').write_text('content')
        (self.root / 'folder').mkdir()
        item = self.explorer.move('/source.txt', '/folder/destination.txt')
        restarted = FileExplorer(self.root)
        restarted.undo_move(item['id'])
        self.assertEqual((self.root / 'source.txt').read_text(), 'content')
        self.assertFalse((self.root / 'folder' / 'destination.txt').exists())
        self.assertEqual(restarted.list_moves(), [])

    def test_undo_rejects_changed_item_and_destination_conflict(self):
        (self.root / 'source.txt').write_text('original')
        item = self.explorer.move('/source.txt', '/moved.txt')
        (self.root / 'moved.txt').write_text('changed content')
        self.assert_error(409, self.explorer.undo_move, item['id'])
        (self.root / 'source.txt').write_text('another file')
        self.assert_error(409, self.explorer.undo_move, item['id'])
        self.assertEqual((self.root / 'moved.txt').read_text(), 'changed content')

    def test_metadata_failure_rolls_back_delete_and_move(self):
        (self.root / 'source.txt').write_text('preserved')
        with patch.object(self.explorer, '_write', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.explorer.trash('/source.txt')
            with self.assertRaises(OSError):
                self.explorer.move('/source.txt', '/destination.txt')
        self.assertEqual((self.root / 'source.txt').read_text(), 'preserved')
        self.assertFalse((self.root / 'destination.txt').exists())

    def test_search_nested_names_excludes_trash_and_reports_limits(self):
        (self.root / 'nested').mkdir()
        (self.root / 'nested' / 'report.txt').write_text('nested')
        (self.root / 'report.txt').write_text('root')
        (self.root / 'report-deleted.txt').write_text('deleted')
        self.explorer.trash('/report-deleted.txt')
        result = self.explorer.search('REPORT')
        self.assertEqual({item['path'] for item in result['items']}, {'/report.txt', '/nested/report.txt'})
        self.assertFalse(result['partial'])
        self.assertTrue(self.explorer.search('report', limit=1)['partial'])
        self.assertTrue(self.explorer.search('none', max_entries=1)['partial'])

    def test_reserved_directory_and_traversal_are_blocked(self):
        for path in ('/', '/../outside', '/.serverpy/manifest.json'):
            self.assert_error(403, self.explorer.trash, path)
        self.assert_error(403, self.explorer.search, 'query', '/../../')
        self.assert_error(400, self.explorer.search, '')

    def test_trashing_a_symlink_preserves_its_target(self):
        target = self.root / 'target.txt'
        target.write_text('target preserved')
        link = self.root / 'link.txt'
        try:
            os.symlink('target.txt', link)
        except OSError:
            self.skipTest('Creating symlinks is unavailable')
        item = self.explorer.trash('/link.txt')
        self.assertEqual(target.read_text(), 'target preserved')
        self.assertFalse(os.path.lexists(link))
        self.explorer.restore(item['id'])
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.read_text(), 'target preserved')
