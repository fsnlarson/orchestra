"""Increments the Orchestra version and pushes a new release to PyPI.

This script can only be called by orchestra core committers, and will result
in permission errors otherwise.
"""
from argparse import ArgumentParser
from distutils.version import StrictVersion
import os
import re
import shutil
from subprocess import check_output, CalledProcessError
from tempfile import mkdtemp

VERSION_RE = re.compile("__version__ = ['\"]([^'\"]+)['\"]")


def main(args):
    # Compute the new version number
    old_version = get_version('orchestra')
    new_version = increment_version_number(old_version, args.version_part)

    # Verify that our git setup is reasonable and print a loud warning.
    verify_and_warn(old_version, new_version)

    # Update orchestra/__init__.py with the new version
    update_version('orchestra', new_version, fake=args.fake)

    # Commit the update to the repo
    commit_and_push(fake=args.fake)

    # Create a new tag for the release
    tag_str = tag_release(new_version, fake=args.fake)

    # Release the new version on pypi
    pypi_release(tag_str, fake=args.fake)


def verify_and_warn(old_version, new_version):
    # verify that we're on the master branch
    branch_cmd = ['git', 'symbolic-ref', '--short', 'HEAD']
    cur_branch = run_command(branch_cmd).strip().lower()
    if cur_branch != 'master':
        print('This script must be run from the master branch. Exiting.')
        exit()

    # verify that master is up to date
    rev_cmd = ['git', 'rev-list']
    unpushed_cmd = rev_cmd + ['origin/master..']
    unpushed_commits = run_command(unpushed_cmd).strip()
    if unpushed_commits:
        print('Your branch has commits not yet on origin/master. Exiting.')
        exit()

    unpulled_cmd = rev_cmd + ['..origin/master']
    unpulled_commits = run_command(unpulled_cmd).strip()
    if unpulled_commits:
        print('Your branch is behind origin/master. Exiting.')
        exit()

    # verify that there are no outstanding changes
    status_cmd = ['git', 'status', '--porcelain']
    status_output = run_command(status_cmd).strip()
    if status_output:
        print('There are outstanding changes to your branch. Exiting.')
        exit()

    print('WARNING: running this script will increment the Orchestra version '
          'from {} to {}. This involves pushing a new commit to master and '
          'releasing a new PyPI distribution, changes you CANNOT TAKE BACK. '
          'Before proceeding, ensure that you are on the master branch, have '
          'pulled the latest changes, and have no outstanding local changes. '
          'THIS SCRIPT WILL FAIL if you do not have credentials to push to '
          'the Orchestra GitHub repository or the Orchestra PyPI account.'
          .format(old_version, new_version))
    ack = input('ARE YOU SURE YOU WISH TO PROCEED? (y/n): ').lower()
    while ack not in ['y', 'n']:
        ack = input('Please respond with "y" or "n": ').lower()
    if ack == 'n':
        exit()


def increment_version_number(old_version, version_part):
    version_parsed = StrictVersion(old_version)
    major, minor, patch = version_parsed.version
    if version_part == 'major':
        major += 1
        minor = 0
        patch = 0
    elif version_part == 'minor':
        minor += 1
        patch = 0
    elif version_part == 'patch':
        patch += 1
    new_version = '{}.{}.{}'.format(major, minor, patch)
    return new_version


def version_file(package):
    return os.path.join(package, '__init__.py')


def get_version(package):
    """ Return package version as listed in `__version__` in `init.py`."""
    # Parsing the file instead of importing it Pythonically allows us to make
    # this script completely Django-independent. This function is also used by
    # setup.py, which cannot import the package it is installing.
    with open(version_file(package), 'r') as f:
        init_py = f.read()
    return VERSION_RE.search(init_py).group(1)


def update_version(package, new_version, fake=False):
    # Update the __init__.py file with the new version.
    init_file = version_file(package)
    with open(init_file, 'r') as f:
        old_initpy = f.read()
    new_initpy = VERSION_RE.sub("__version__ = '{}'".format(new_version),
                                old_initpy)

    # Write the file out to disk.
    if fake:
        print('--fake passed, not updating {}'.format(init_file))
    else:
        print('Updating version in {}'.format(init_file))
        with open(version_file(package), 'w') as f:
            f.write(new_initpy)


def commit_and_push(fake=False):
    # commit all changes
    wrap_command(['git', 'commit', '-am', '"Version bump."'], fake)

    # Push changes
    wrap_command(['git', 'push', 'origin', 'master'], fake)


def tag_release(version, fake=False):
    # Create the tag
    tag_str = 'v{}'.format(version)
    tag_msg = 'Version {} of Orchestra'.format(version)
    tag_cmd = ['git', 'tag', '-am', '"{}"'.format(tag_msg), tag_str]
    wrap_command(tag_cmd, fake)

    # Update the stable tag
    stable_tag_msg = 'The latest stable release of Orchestra.'
    stable_tag_cmd = ['git', 'tag', '-afm', '"{}"'.format(stable_tag_msg),
                      'stable']
    wrap_command(stable_tag_cmd, fake)

    # Push the tags
    wrap_command(['git', 'push', '--tags'], fake)

    return tag_str


def pypi_release(tag_str, fake=False):
    # Create a temporary directory for the release
    release_dir = mkdtemp()
    print('Created release directory in {}'.format(release_dir))

    # Move into the release directory
    old_dir = os.getcwd()
    os.chdir(release_dir)

    # Clone the git repo for release
    print('Cloning Orchestra into the new release directory.')
    clone_cmd = ['git', 'clone', 'https://github.com/unlimitedlabs/orchestra',
                 '-b', tag_str]
    wrap_command(clone_cmd, fake)  # This is safe to always run.
    if not fake:
        os.chdir('orchestra')

    # Release to pypi
    print('Releasing Orchestra to PyPI.')
    pypi_cmd = ['python3', 'setup.py', 'sdist', 'upload', '-r', 'pypi']
    wrap_command(pypi_cmd, fake)

    # Clean up
    print('Cleaning up release directory.')
    os.chdir(old_dir)
    shutil.rmtree(release_dir)


def wrap_command(cmd, fake):
    cmd_str = ' '.join(cmd)
    if fake:
        print('--fake passed, not running "{}"'.format(cmd_str))
        return ''
    print('Running command "{}"'.format(cmd_str))
    run_command(cmd)


def run_command(cmd):
    try:
        return check_output(cmd).decode()
    except CalledProcessError as e:
        print('Error running command! Code: {}, output: {}'
              .format(e.returncode, e.output))


def parse_args():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        'version_part',
        choices=['major', 'minor', 'patch'],
        help=('The part of the version to increase: major (e.g., 1.0.0 => '
              '2.0.0), minor (e.g., 0.1.0 => 0.2.0), or patch (e.g., 0.0.1 => '
              '0.0.2).'))
    parser.add_argument(
        '--fake',
        action='store_true',
        help=('Fake the release without actually changing anything (useful '
              'for testing).'))
    return parser.parse_args()


if __name__ == '__main__':
    main(parse_args())
