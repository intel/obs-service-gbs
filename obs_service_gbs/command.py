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
import subprocess
import tempfile

from obs_service_gbp import logger, gbplog, CachedRepo, CachedRepoError, gbplog

class ServiceError(Exception):
    """Source service errors"""
    pass

def construct_gbs_args(args, outdir):
    """Construct args list for GBS"""
    global_argv = []
    cmd_argv = ['--outdir=%s' % outdir]
    if args.verbose == 'yes':
        global_argv.append('--verbose')
    if args.revision:
        cmd_argv.append('--commit=%s' % args.revision)
    return global_argv + ['export'] + cmd_argv

def parse_args(argv):
    """Argument parser"""

    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Remote repository URL', required=True)
    parser.add_argument('--outdir', help='Output direcory',
                        default=os.path.abspath(os.curdir))
    parser.add_argument('--revision', help='Remote repository URL',
                        default='HEAD')
    parser.add_argument('--verbose', '-v', help='Verbose output',
                        choices=['yes', 'no'])
    return parser.parse_args(argv)

def main(argv=None):
    """Main function"""

    logger.info('Starting GBS source service')
    ret = 0
    tmpdir = None

    try:
        args = parse_args(argv)
        args.outdir = os.path.abspath(args.outdir)

        if args.verbose == 'yes':
            gbplog.setup(color='auto', verbose=True)
            logger.setLevel(gbplog.DEBUG)

        # Create / update cached repository
        repo = CachedRepo(args.url)
        args.revision = repo.update_working_copy(args.revision,
                                                 submodules=False)

        # Create outdir and a temporary directory
        try:
            os.makedirs(args.outdir)
        except OSError as err:
            if err.errno != os.errno.EEXIST:
                raise ServiceError('Failed to create outdir: %s' % err, 1)
        try:
            tmpdir = tempfile.mkdtemp(dir=args.outdir)
        except OSError as err:
            raise ServiceError('Failed to create tmpdir: %s' % err, 1)

        # Export sources with GBS
        cmd = ['gbs'] + construct_gbs_args(args, tmpdir)
        logger.info('Exporting packaging files with GBS')
        popen = subprocess.Popen(cmd, cwd=repo.repodir)
        popen.communicate()
        if popen.returncode:
            raise ServiceError('GBS failed, unable to export packaging files',
                               2)
        # Move packaging files from tmpdir to actual outdir
        exportdir = os.path.join(tmpdir, os.listdir(tmpdir)[0])
        for fname in os.listdir(exportdir):
            shutil.move(os.path.join(exportdir, fname),
                        os.path.join(args.outdir, fname))

        logger.info('Packaging files successfully exported')

    except ServiceError as err:
        logger.error(err[0])
        ret = err[1]
    except CachedRepoError as err:
        logger.error('RepoCache: %s' % err)
        ret = 1
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir)

    return ret
