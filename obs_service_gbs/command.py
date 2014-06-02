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
"""The GBS source service for OBS"""

import argparse
import os
import shutil
import tempfile
from ConfigParser import SafeConfigParser

from gitbuildsys.cmd_export import main as cmd_export
from gitbuildsys import log as gbs_log
from gitbuildsys.errors import CmdError
import gbp.log as gbplog

import gbp_repocache
from gbp_repocache import CachedRepo, CachedRepoError
from obs_service_gbp_utils import GbpServiceError, GbpChildBTError, fork_call
from obs_service_gbp_utils import sanitize_uid_gid, write_treeish_meta


# Exit codes
EXIT_OK = 0
EXIT_ERR_SERVICE = 1
EXIT_ERR_GBS_EXPORT = 2
EXIT_ERR_GBS_CRASH = 3

# Template spec file for the "error package"
ERROR_PKG_SPEC = """
Name:           service-error
Version:        1
Release:        0
License:        GPL-2.0+
Summary:        Package indicating an export error in gbs source service
Source0:        service-error

%description
This is a dummy package created by obs-service-gbs that indicates that
exporting the packaging files failed. This is a special hack to prevent the
creation of broken packages in case of service failures. This behaviour was
implicitly enabled with the 'error-pkg' parameter of the service.

%build
cat << EOF
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!
!!!
!!! OBS-SERVICE-GBS FAILED
!!!
!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
--- SERVICE ERROR LOG --------------------------------------------------------
`sed s'/^/  /' %{SOURCE0}`
--- END OF SERVICE ERROR LOG -------------------------------------------------
EOF
exit 1
"""

# Setup logging
LOGGER = gbplog.getLogger('source_service')
LOGGER.setLevel(gbplog.INFO)


class ServiceError(Exception):
    """Source service errors"""
    pass

def construct_gbs_args(args, outdir, gitdir):
    """Construct args list for GBS"""
    # Replicate gbs export command line arguments
    gbs_args = {'outdir': outdir,
                'gitdir': gitdir,
                'spec': None,
                'commit': None,
                'include_all': None,
                'source_rpm': None,
                'no_patch_export': None,
                'upstream_branch': None,
                'upstream_tag': None,
                'squash_patches_until': None,
                'packaging_dir': None,
                'debug': None}
    if args.revision:
        gbs_args['commit'] = args.revision
    return argparse.Namespace(**gbs_args)

def read_config(filenames):
    '''Read configuration file(s)'''
    defaults = {'repo-cache-dir': '/var/cache/obs/gbs-repos/',
                'gbs-user': None,
                'gbs-group': None}

    filenames = [os.path.expanduser(fname) for fname in filenames]
    LOGGER.debug('Trying %s config files: %s', len(filenames), filenames)
    parser = SafeConfigParser(defaults=defaults)
    read = parser.read(filenames)
    LOGGER.debug('Read %s config files: %s', len(read), read)

    # Add our one-and-only section, if it does not exist
    if not parser.has_section('general'):
        parser.add_section('general')

    # Read overrides from environment
    for key in defaults.keys():
        envvar ='OBS_GBS_%s' % key.replace('-', '_').upper()
        if envvar in os.environ:
            parser.set('general', key, os.environ[envvar])

    # We only use keys from one section, for now
    return dict(parser.items('general'))

def gbs_export(repo, args, config):
    '''Export packaging files with GBS'''
    # Create temporary directory
    try:
        tmpdir = tempfile.mkdtemp(dir=args.outdir)
    except OSError as err:
        raise ServiceError('Failed to create tmpdir: %s' % err,
                           EXIT_ERR_SERVICE)

    # Determine UID/GID and grant permissions to tmpdir
    try:
        uid, gid = sanitize_uid_gid(config['gbs-user'], config['gbs-group'])
    except GbpServiceError as err:
        raise ServiceError(err, EXIT_ERR_SERVICE)
    os.chown(tmpdir, uid, gid)

    # Do export
    try:
        gbs_args = construct_gbs_args(args, tmpdir, repo.repodir)
        LOGGER.info('Exporting packaging files with GBS')
        LOGGER.debug('gbs args: %s', gbs_args)
        try:
            fork_call(uid, gid, cmd_export)(gbs_args)
        except GbpServiceError as err:
            LOGGER.error('Internal service error when trying to run GBS: '
                         '%s', err)
            LOGGER.error('Most likely a configuration error (or a BUG)!')
            raise ServiceError('Failed to run GBS thread: %s' % err,
                               EXIT_ERR_SERVICE)
        except GbpChildBTError as err:
            # CmdError and its sublasses are exptected errors
            if issubclass(err.typ, CmdError):
                raise ServiceError('GBS export failed: %s' % err.val,
                                   EXIT_ERR_GBS_EXPORT)
            else:
                LOGGER.error('Uncaught exception in GBS:\n'
                             '%s', err.prettyprint_tb())
                raise ServiceError('GBS crashed, export failed',
                                   EXIT_ERR_GBS_CRASH)

        # Move packaging files from tmpdir to actual outdir
        exportdir = os.path.join(tmpdir, os.listdir(tmpdir)[0])
        for fname in os.listdir(exportdir):
            shutil.move(os.path.join(exportdir, fname),
                        os.path.join(args.outdir, fname))
        LOGGER.info('Packaging files successfully exported')
    finally:
        shutil.rmtree(tmpdir)

def integer_list(string):
    """Convert a string of comma-separated integers into a list of ints"""
    return [int(val.strip()) for val in string.split(',') if val]

def parse_args(argv):
    """Argument parser"""
    default_configs = ['/etc/obs/services/gbs',
                       '~/.obs/gbs']

    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Remote repository URL', required=True)
    parser.add_argument('--outdir', help='Output direcory',
                        default=os.path.abspath(os.curdir))
    parser.add_argument('--revision', help='Git tree-ish to export files from',
                        default='HEAD')
    parser.add_argument('--verbose', '-v', help='Verbose output',
                        choices=['yes', 'no'])
    parser.add_argument('--config', action='append',
                        help='Config file to use, can be given multiple times')
    parser.add_argument('--git-meta', metavar='FILENAME',
                        help='Create a json-formatted file FILENAME containing'
                             'metadata about the exported revision')
    parser.add_argument('--error-pkg', metavar='EXIT_CODES', type=integer_list,
                        default=[],
                        help='Comma-separated list of exit codes that cause '
                             'an "error package" to be created instead of '
                             'causing a service error.')
    args = parser.parse_args(argv)
    if not args.config:
        args.config = default_configs

    return args

def main(argv=None):
    """Main function"""

    ret = EXIT_OK
    args = parse_args(argv)
    args.outdir = os.path.abspath(args.outdir)

    if args.verbose == 'yes':
        gbplog.setup(color='auto', verbose=True)
        LOGGER.setLevel(gbplog.DEBUG)
        gbp_repocache.LOGGER.setLevel(gbplog.DEBUG)
        gbs_log.setup(verbose=True)
    else:
        gbplog.setup(color='auto', verbose=False)
        gbs_log.setup(verbose=False)
    # Add a new handler writing to a tempfile into the root logger
    file_log = tempfile.NamedTemporaryFile(prefix='gbs-service_')
    file_handler = gbplog.GbpStreamHandler(file_log)
    gbplog.getLogger().addHandler(file_handler)

    LOGGER.info('Starting GBS source service')

    # Create outdir
    try:
        os.makedirs(args.outdir)
    except OSError as err:
        if err.errno != os.errno.EEXIST:
            LOGGER.error('Failed to create outdir: %s', err)
            return EXIT_ERR_SERVICE

    try:
        config = read_config(args.config)
        # Create / update cached repository
        try:
            repo = CachedRepo(config['repo-cache-dir'], args.url)
            args.revision = repo.update_working_copy(args.revision,
                                                     submodules=False)
        except CachedRepoError as err:
            raise ServiceError('RepoCache: %s' % err, EXIT_ERR_SERVICE)

        # Export sources with GBS
        gbs_export(repo, args, config)

        # Write git-meta
        if args.git_meta:
            try:
                write_treeish_meta(repo.repo, args.revision, args.outdir,
                                   args.git_meta)
            except GbpServiceError as err:
                raise ServiceError(str(err), EXIT_ERR_SERVICE)
    except ServiceError as err:
        LOGGER.error(err[0])
        if err[1] in args.error_pkg:
            file_handler.flush()
            error_fn = os.path.join(args.outdir, 'service-error')
            shutil.copy2(file_log.name, error_fn)
            with open(error_fn + '.spec', 'w') as error_spec:
                error_spec.write(ERROR_PKG_SPEC)
            ret = EXIT_OK
        else:
            ret = err[1]

    return ret
