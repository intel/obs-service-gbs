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

import grp
import mock
import json
import os
import shutil
import stat
import tempfile
# pylint: disable=E0611
from nose.tools import assert_raises, eq_, ok_

from gbp.git.repository import GitRepository
from obs_service_gbp_utils import GbpServiceError

from obs_service_gbs.command import main as export_service


TEST_DATA_DIR = os.path.abspath(os.path.join('tests', 'data'))


class MockGbsError(Exception):
    """Mock gbs crashes"""
    pass

def _mock_export():
    """Mock export main function for testing crashes"""
    raise MockGbsError()

def _mock_fork(*args, **kwargs):
    """Mock fork call function for testing crashes"""
    raise GbpServiceError(args, kwargs)



def service(argv=None):
    """Wrapper for service"""
    # Set non-existent config file so that user/system settings don't affect
    # tests
    dummy_conf = os.path.abspath(os.path.join(os.path.curdir, 'gbs.noconfig'))
    return export_service(['--config', dummy_conf] + argv)


class UnitTestsBase(object):
    """Base class for unit tests"""

    @classmethod
    def create_orig_repo(cls, name):
        """Create test repo"""
        orig_repo = GitRepository.create(os.path.join(cls.workdir, name))
        # First, add everything else except for packaging
        files = os.listdir(TEST_DATA_DIR)
        files.remove('packaging')
        orig_repo.add_files(files, work_tree=TEST_DATA_DIR)
        orig_repo.commit_staged('Initial version')
        # Then, add packaging files
        orig_repo.add_files('packaging', work_tree=TEST_DATA_DIR)
        orig_repo.commit_staged('Add packaging files')
        orig_repo.create_tag('v0.1', msg='Version 0.1')
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
                                      cls.__name__, dir='.'))
        cls.orig_dir = os.getcwd()
        os.chdir(cls.workdir)
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
        self.cachedir = None

    def setup(self):
        """Test case setup"""
        # Change to a temporary directory
        self.tmpdir = tempfile.mkdtemp(prefix='test_', dir=self.workdir)
        os.chdir(self.tmpdir)
        # Individual cache for every test case
        suffix = os.path.basename(self.tmpdir).replace('test', '')
        self.cachedir = os.path.join(self.workdir, 'cache' + suffix)
        os.environ['OBS_GBS_REPO_CACHE_DIR'] = self.cachedir

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

    def check_files(self, files, directory=''):
        """Check list of files"""
        found = set(os.listdir(os.path.join(self.tmpdir, directory)))
        expected = set(files)
        eq_(found, expected, "Expected: %s, Found: %s" % (expected, found))


class TestGbsService(UnitTestsBase):
    """Base class for unit tests"""

    def test_invalid_options(self):
        """Test invalid options"""
        # Non-existing option
        with assert_raises(SystemExit):
            service(['--foo'])
        # Option without argument
        with assert_raises(SystemExit):
            service(['--url'])
        # Invalid repo
        eq_(service(['--url=foo/bar.git']), 1)

    def test_basic_export(self):
        """Test that export works"""
        eq_(service(['--url', self.orig_repo.path]), 0)
        self.check_files(['test-package.spec', 'test-package-0.1.tar.bz2'])

    def test_permission_problem(self):
        """Test git-buildpackage failure"""
        # Outdir creation fails
        os.makedirs('foo')
        os.chmod('foo', stat.S_IREAD | stat.S_IEXEC)
        eq_(service(['--url', self.orig_repo.path, '--outdir=foo/bar']), 1)
        os.chmod('foo', stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        # Tmpdir creation fails
        os.makedirs('foo/bar')
        os.chmod('foo/bar', stat.S_IREAD | stat.S_IEXEC)
        eq_(service(['--url', self.orig_repo.path, '--outdir=foo/bar']), 1)
        os.chmod('foo/bar', stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)

    def test_gbs_error(self):
        """Test GBS export failure"""
        eq_(service(['--url', self.orig_repo.path, '--revision', 'v0.1~1']), 2)
        eq_(os.listdir('.'), [])

    @mock.patch('obs_service_gbs.command.cmd_export', _mock_export)
    def test_gbs_crash(self):
        """Test crash of gbs export"""
        eq_(service(['--url', self.orig_repo.path, '--revision', 'master']), 3)

    @mock.patch('obs_service_gbs.command.fork_call', _mock_fork)
    def test_fork_call_crash(self):
        """Test handling of crash in the obs_service_gbp_utils fork_call()"""
        eq_(service(['--url', self.orig_repo.path, '--revision', 'master']), 1)

    def test_options_outdir(self):
        """Test the --outdir option"""
        outdir = os.path.join(self.tmpdir, 'outdir')
        args = ['--url', self.orig_repo.path, '--outdir=%s' % outdir]
        eq_(service(args), 0)
        ok_(os.path.isdir(outdir))

    def test_options_revision(self):
        """Test the --revision option"""
        eq_(service(['--url', self.orig_repo.path, '--revision=master']), 0)
        eq_(service(['--url', self.orig_repo.path, '--revision=foobar']), 1)

    def test_options_verbose(self):
        """Test the --verbose option"""
        eq_(service(['--url', self.orig_repo.path, '--verbose=yes']), 0)
        with assert_raises(SystemExit):
            service(['--url', self.orig_repo.path, '--verbose=foob'])

    def test_options_config(self):
        """Test the --config option"""
        # First, test without using the wrapper so that no --config option is
        # given to the service
        eq_(export_service(['--url', 'non-existent-repo']), 1)

        # Create config file
        with open('my.conf', 'w') as conf:
            conf.write('[general]\n')
            conf.write('repo-cache-dir = my-repo-cache\n')

        # Mangle environment and remove default cache
        default_cache = os.environ['OBS_GBS_REPO_CACHE_DIR']
        del os.environ['OBS_GBS_REPO_CACHE_DIR']
        shutil.rmtree(default_cache)

        # Check that the repo cache we configured is actually used
        eq_(service(['--url', self.orig_repo.path, '--config', 'my.conf']), 0)
        ok_(not os.path.exists(default_cache), os.listdir('.'))
        ok_(os.path.exists('my-repo-cache'), os.listdir('.'))

    def test_options_git_meta(self):
        """Test the --git-meta option"""
        eq_(service(['--url', self.orig_repo.path, '--git-meta=_git_meta']), 0)

        # Check that the file was created and is json-parseable
        with open('_git_meta') as meta_fp:
            json.load(meta_fp)

        # Test failure
        eq_(service(['--url', self.orig_repo.path,
                     '--git-meta=test-package.spec']), 1)

    def test_options_error_pkg(self):
        """Test the --error-pkg option"""
        # Do not create err-pkg if exit code not listed
        eq_(service(['--url', self.orig_repo.path, '--error-pkg=2,3',
                     '--revision=foobar']), 1)
        self.check_files([])

        # Catch error and create err-pkg
        eq_(service(['--url', self.orig_repo.path, '--error-pkg=1,2,3',
                     '--revision=foobar', '--outdir=foo']), 0)
        self.check_files(['service-error.spec', 'service-error'],
                         directory='foo')

    def test_user_group_config(self):
        """Test the user/group settings"""
        # Changing to current user/group should succeed
        os.environ['OBS_GBS_GBS_USER'] = str(os.getuid())
        os.environ['OBS_GBS_GBS_GROUP'] = grp.getgrgid(os.getgid()).gr_name
        eq_(service(['--url', self.orig_repo.path]), 0)

        # Changing to non-existent user should fail
        os.environ['OBS_GBS_GBS_USER'] = '_non_existent_user'
        del os.environ['OBS_GBS_GBS_GROUP']
        eq_(service(['--url', self.orig_repo.path]), 1)

        # Return env
        del os.environ['OBS_GBS_GBS_USER']

