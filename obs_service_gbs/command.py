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

from gbp.rpm import guess_spec, NoSpecError
import gbp_repocache
from gbp_repocache import CachedRepo, CachedRepoError




# Setup logging
LOGGER = gbplog.getLogger('source_service')
LOGGER.setLevel(gbplog.INFO)


class ServiceError(Exception):
    """Source service errors"""
    pass


# Implementation taken from http://hetland.org
def levenshtein( a, b ):
    """Calculates the Levenshtein distance between a and b."""
    n, m = len( a ), len( b )
    if n > m:
        # Make sure n <= m, to use O(min(n,m)) space
        a, b = b, a
        n, m = m, n

    current = range( n + 1 )
    for i in range( 1, m + 1 ):
        previous, current = current, [i] + [0] * n
        for j in range( 1, n + 1 ):
            add, delete = previous[j] + 1, current[j - 1] + 1
            change = previous[j - 1]
            if a[j - 1] != b[i - 1]:
                change = change + 1
            current[j] = min( add, delete, change )

    return current[n]

def get_packaging_files(package_path):
    res=[]
    for tmp_res in os.listdir( package_path ):
        if tmp_res.endswith( ".spec" ) and \
           os.path.isfile( package_path + "/" + tmp_res ):
            res.append(tmp_res)
    return res

def findBestSpecFile( package_path, package_name ):
    """Find the name of the spec file
       which matches best with `package_name`"""
    specFileList = get_packaging_files( package_path )

    specFile = None
    if len( specFileList ) < 1:
        # No spec file in list
        specFile = None
    elif len( specFileList ) == 1:
        # Only one spec file
        specFile = specFileList[0]
    else:
        sameStart = []
        for spec in specFileList:
            if str( spec[:-5] ) == str( package_name ):
                # This spec file has the same name as the package
                specFile = spec
                break
            elif spec.startswith( package_name ):
                # This spec file has a name which looks like the package
                sameStart.append( spec )

        if specFile is None:
            if len( sameStart ) > 0:
                # Sort the list of 'same start' by the Levenshtein distance
                sameStart.sort( key = lambda x: \
		                levenshtein( x, package_name ) )
                specFile = sameStart[0]
            else:
                # No spec file starts with the name of the package,
                # sort the whole spec file list by the Levenshtein distance
                specFileList.sort( key = lambda x: \
		                   levenshtein( x, package_name ) )
                specFile = specFileList[0]

    if specFile is None:
        msg = "Found no spec file matching package name '%s'" % package_name
        raise ServiceError(msg, 2)

    return specFile

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
    if args.spec:
        gbs_args['spec'] = args.spec
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
    parser.add_argument('--spec',
                        help='specify a spec file to use. It should be a file '
                        'name that GBS will find it in packaging dir')
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
        os.chdir(repo.repodir)
        LOGGER.info('args.spec %s' % args.spec)
        if args.spec is None:
            spec_name=os.path.basename(args.url)
            if spec_name.endswith(".git"):
                  spec_name=spec_name[:-4]
            args.spec = findBestSpecFile('./packaging', spec_name)
        else:
            args.spec = findBestSpecFile('./packaging', args.spec)
        if args.spec is None:
            LOGGER.error('no spec file available in packaging'
                                                         ' directory')
            return 2

        # Export sources with GBS
        gbs_export(repo, args)

    except ServiceError as err:
        LOGGER.error(err[0])
        ret = err[1]
    except CachedRepoError as err:
        LOGGER.error('RepoCache: %s' % err)
        ret = 1

    return ret
