# vim:fileencoding=utf-8:et:ts=4:sw=4:sts=4
#
# Copyright (C) 2013 Intel Corporation <markus.lehtonen@linux.intel.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301, USA.
"""Tests for the GBS source service"""

import os
import shutil
import stat
import tempfile
# pylint: disable=E0611
from nose.tools import assert_raises

from gbp.git.repository import GitRepository

from obs_service_gbs.command import main as service


TEST_DATA_DIR = os.path.abspath(os.path.join('tests', 'data'))

class UnitTestsBase(object):
    """Base class for unit tests"""

    @classmethod
    def create_orig_repo(cls, name):
        """Create test repo"""
        orig_repo = GitRepository.create(os.path.join(cls.workdir, name))
        orig_repo.commit_dir(TEST_DATA_DIR, 'Initial version', 'master',
                             create_missing_branch=True)
        orig_repo.force_head('master', hard=True)
        # Make new commit
        cls.update_repository_file(orig_repo, 'foo.txt', 'new data\n')
        return orig_repo

    @classmethod
    def setup_class(cls):
        """Test class setup"""
        # Don't let git see that we're (possibly) under a git directory
        os.environ['GIT_CEILING_DIRECTORIES'] = os.getcwd()
        # Create temporary workdir
        cls.workdir = os.path.abspath(tempfile.mkdtemp(prefix='%s_' %
                                     __name__, dir='.'))
        cls.orig_dir = os.getcwd()
        os.chdir(cls.workdir)
        # Use cache in our workdir
        cls.cachedir = os.path.join(cls.workdir, 'cache')
        os.environ['CACHEDIR'] = cls.cachedir
        # Create an orig repo for testing
        cls.orig_repo = cls.create_orig_repo('orig')

    @classmethod
    def teardown_class(cls):
        """Test class teardown"""
        os.chdir(cls.orig_dir)
        if not 'DEBUG_NOSETESTS' in os.environ:
            shutil.rmtree(cls.workdir)

    def __init__(self):
        self.tmpdir = None

    def setup(self):
        """Test case setup"""
        # Change to a temporary directory
        self.tmpdir = tempfile.mkdtemp(dir=self.workdir)
        os.chdir(self.tmpdir)

    def teardown(self):
        """Test case teardown"""
        # Restore original working dir
        os.chdir(self.workdir)
        if not 'DEBUG_NOSETESTS' in os.environ:
            shutil.rmtree(self.tmpdir)

    @staticmethod
    def update_repository_file(repo, filename, data):
        """Append data to file in git repository and commit changes"""
        with open(os.path.join(repo.path, filename), 'a') as filep:
            filep.write(data)
        repo.add_files(filename)
        repo.commit_files(filename, "Update %s" % filename)


class TestGbsService(UnitTestsBase):
    """Base class for unit tests"""

    def test_invalid_options(self):
        """Test invalid options"""
        # Non-existing option
        with assert_raises(SystemExit):
            service(['--foo'])
        # Option without argument
        with assert_raises(SystemExit):
            assert service(['--url'])
        # Invalid repo
        assert service(['--url=foo/bar.git']) != 0

    def test_basic_export(self):
        """Test that export works"""
        assert service(['--url', self.orig_repo.path]) == 0
        files = set(os.listdir('.'))
        expected = set(['test-package.spec', 'test-package-0.1.tar.bz2'])
        assert files == expected, 'expected: %s, found: %s' % (files, expected)

    def test_permission_problem(self):
        """Test git-buildpackage failure"""
        # Outdir creation fails
        os.makedirs('foo')
        os.chmod('foo', stat.S_IREAD | stat.S_IEXEC)
        assert service(['--url', self.orig_repo.path, '--outdir=foo/bar']) == 1
        os.chmod('foo', stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        # Tmpdir creation fails
        os.makedirs('foo/bar')
        os.chmod('foo/bar', stat.S_IREAD | stat.S_IEXEC)
        assert service(['--url', self.orig_repo.path, '--outdir=foo/bar']) == 1
        os.chmod('foo/bar', stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)

    def test_options_outdir(self):
        """Test the --outdir option"""
        outdir = os.path.join(self.tmpdir, 'outdir')
        args = ['--url', self.orig_repo.path, '--outdir=%s' % outdir]
        assert service(args) == 0
        assert os.path.isdir(outdir)

    def test_options_revision(self):
        """Test the --revision option"""
        assert service(['--url', self.orig_repo.path, '--revision=master']) == 0
        assert service(['--url', self.orig_repo.path, '--revision=foobar']) == 1

    def test_options_verbose(self):
        """Test the --verbose option"""
        assert service(['--url', self.orig_repo.path, '--verbose=yes']) == 0
        with assert_raises(SystemExit):
            service(['--url', self.orig_repo.path, '--verbose=foob'])


