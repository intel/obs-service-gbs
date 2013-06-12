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
import traceback
from ConfigParser import SafeConfigParser

from gitbuildsys.cmd_export import main as cmd_export
from gitbuildsys import log as gbs_log
from gitbuildsys.errors import CmdError
import gbp.log as gbplog

import gbp_repocache
from gbp_repocache import CachedRepo, CachedRepoError


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
    defaults = {'repo-cache-dir': '/var/cache/obs/gbs-repos/'}

    filenames = [os.path.expanduser(fname) for fname in filenames]
    LOGGER.debug('Trying %s config files: %s' % (len(filenames), filenames))
    parser = SafeConfigParser(defaults=defaults)
    read = parser.read(filenames)
    LOGGER.debug('Read %s config files: %s' % (len(read), read))

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

def gbs_export(repo, args):
    '''Export packaging files with GBS'''
    # Create temporary directory
    try:
        tmpdir = tempfile.mkdtemp(dir=args.outdir)
    except OSError as err:
        raise ServiceError('Failed to create tmpdir: %s' % err, 1)

    # Do export
    try:
        gbs_args = construct_gbs_args(args, tmpdir, repo.repodir)
        LOGGER.info('Exporting packaging files with GBS')
        LOGGER.debug('gbs args: %s' % gbs_args)
        try:
            cmd_export(gbs_args)
        except CmdError as err:
            raise ServiceError('GBS export failed: %s' % err, 2)
        except Exception as err:
            LOGGER.debug(traceback.format_exc())
            raise ServiceError('Encatched exception in GBS, export failed', 2)

        # Move packaging files from tmpdir to actual outdir
        exportdir = os.path.join(tmpdir, os.listdir(tmpdir)[0])
        for fname in os.listdir(exportdir):
            shutil.move(os.path.join(exportdir, fname),
                        os.path.join(args.outdir, fname))
        LOGGER.info('Packaging files successfully exported')
    finally:
        shutil.rmtree(tmpdir)

def parse_args(argv):
    """Argument parser"""
    default_configs = ['/etc/obs/services/gbs',
                       '~/.obs/gbs']

    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Remote repository URL', required=True)
    parser.add_argument('--outdir', help='Output direcory',
                        default=os.path.abspath(os.curdir))
    parser.add_argument('--revision', help='Remote repository URL',
                        default='HEAD')
    parser.add_argument('--verbose', '-v', help='Verbose output',
                        choices=['yes', 'no'])
    parser.add_argument('--config', action='append',
                        help='Config file to use, can be given multiple times')
    args = parser.parse_args(argv)
    if not args.config:
        args.config = default_configs

    return args

def main(argv=None):
    """Main function"""

    ret = 0
    try:
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

        LOGGER.info('Starting GBS source service')

        config = read_config(args.config)
        # Create / update cached repository
        repo = CachedRepo(config['repo-cache-dir'], args.url)
        args.revision = repo.update_working_copy(args.revision,
                                                 submodules=False)
        # Create outdir
        try:
            os.makedirs(args.outdir)
        except OSError as err:
            if err.errno != os.errno.EEXIST:
                raise ServiceError('Failed to create outdir: %s' % err, 1)

        # Export sources with GBS
        gbs_export(repo, args)

    except ServiceError as err:
        LOGGER.error(err[0])
        ret = err[1]
    except CachedRepoError as err:
        LOGGER.error('RepoCache: %s' % err)
        ret = 1

    return ret
