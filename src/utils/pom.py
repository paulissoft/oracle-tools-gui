"""
The Oracle Tools GUI for launching Maven builds based on Oracle Tools.
"""

# Python modules
import sys
import os
import argparse
import subprocess
import re
from pathlib import Path
import logging
from shutil import which
# from pkg_resources import packaging
import pkg_resources


# items to test
__all__ = ['db_order', 'initialize', 'check_environment', 'process_POM']


logger = None


def db_order(db):
    for i, e in enumerate(['dev', 'tst', 'test', 'acc', 'prod', 'prd']):
        if e in db.lower():
            return i
    return db.lower()


def initialize():
    global logger

    argv = [argc for argc in sys.argv[1:] if argc != '--']

    parser = argparse.ArgumentParser(description='Setup logging')
    parser.add_argument('-d', dest='debug', action='store_true', help='Enable debugging')
    parser.add_argument('--db-config-dir', help='The database configuration directory')
    parser.add_argument('file', nargs='?', help='The POM file')
    args, rest = parser.parse_known_args(argv)
    if args.db_config_dir:
        args.db_config_dir = os.path.abspath(args.db_config_dir)
    if args.file:
        args.file = os.path.abspath(args.file)
    logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG if args.debug else logging.INFO)
    logger = logging.getLogger()
    if len(rest) == 0 and args.file:
        check_environment()
    if '-d' in argv:
        argv.remove('-d')
    logger.debug('argv: %s; logger: %s; args: %s' % (argv, logger, args))
    return argv, logger, args


def check_environment():
    programs = [
        ['mvn', '-version', '3.3.1', r'Apache Maven ([0-9.]+)', True],
        ['perl', '--version', '5.16.0', r'\(v([0-9.]+)\)', True],
        ['sql', '-V', '18.0.0.0', r'SQLcl: Release ([0-9.]+)', True],
        ['java', '-version', '1.8.0', r'(?:java|openjdk) version "([0-9.]+).*"', False], # version is printed to stderr (!#$?)
        ['javac', '-version', '1.8.0', r'javac ([0-9.]+)', True],
    ]

    for i, p in enumerate(programs):
        proc = subprocess.run(p[0] + ' ' + p[1], shell=True, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        logger.debug('proc: {}'.format(proc))
        expected_version = p[2]
        regex = p[3]
        output = proc.stdout if p[4] else proc.stderr
        m = re.search(regex, output)
        assert m, 'Could not find {} in {}'.format(regex, output)
        actual_version = m.group(1)
        assert pkg_resources.packaging.version.parse(actual_version) >= pkg_resources.packaging.version.parse(expected_version), f'Version of program "{p[0]}" is "{actual_version}" which is less than the expected version "{expected_version}"'
        logger.info('Version of "{}" is "{}" and its location is "{}"'.format(p[0], actual_version, os.path.dirname(which(p[0]))))


def process_POM(pom_file, db_config_dir):
    """
    Process a single POM file and setup the GUI.
    The POM file must be either based on an Oracle Tools parent POM for the database or Apex.
    """
    def determine_POM_settings(pom_file, db_config_dir):
        properties = {}
        profiles = set()

        cmd = f"mvn --file {pom_file} -N help:all-profiles -Pconf-inquiry compile"
        if db_config_dir:
            cmd += f" -Ddb.config.dir={db_config_dir}"
        mvn = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, text=True)
        stdout, stderr = mvn.communicate()

        if mvn.returncode == 0:
            pass
        else:
            returncode = mvn.returncode
            error = ''
            for ch in stderr:
                error += ch
            raise Exception(f'The command "{cmd}" failed with return code {returncode} and error:\n{error}')

        # Profile Id: db-install (Active: false , Source: pom)
        line = ''
        for ch in stdout:
            if ch != "\n":
                line += ch
            else:
                logger.debug("line: %s" % (line))
                m = re.search(r"Profile Id: ([a-zA-Z0-9_.-]+) \(Active: .*, Source: pom\)", line)
                if m:
                    logger.debug("adding profile: %s" % (m.group(1)))
                    profiles.add(m.group(1))
                else:
                    m = re.match(r'\[echoproperties\] ([a-zA-Z0-9_.-]+)=(.+)$', line)
                    if m:
                        logger.debug("adding property %s = %s" % (m.group(1), m.group(2)))
                        properties[m.group(1)] = m.group(2)
                line = ''
        return properties, profiles

    logger.debug('process_POM()')
    properties, profiles = determine_POM_settings(pom_file, db_config_dir)
    apex_profiles = ['apex-export', 'apex-import']
    db_profiles = ['db-info', 'db-install', 'db-code-check', 'db-test', 'db-generate-ddl-full', 'db-generate-ddl-incr']
    if profiles.issuperset(set(apex_profiles)):
        profiles = apex_profiles
    elif profiles.issuperset(set(db_profiles)):
        profiles = db_profiles
    else:
        raise Exception('Profiles (%s) must be a super set of either the Apex (%s) or database (%s) profiles' % (profiles, set(apex_profiles), set(db_profiles)))
    if not db_config_dir:
        # C\:\\dev\\bc\\oracle-tools\\conf\\src => C:\dev\bc\oracle-tools\conf\src =>
        db_config_dir = properties.get('db.config.dir', '').replace('\\:', ':').replace('\\\\', '\\')
    assert db_config_dir, 'The property db.config.dir must have been set in order to choose a database (on of its subdirectories)'
    logger.debug('db_config_dir: ' + db_config_dir)

    p = Path(db_config_dir)
    dbs = []
    try:
        dbs = [d.name for d in filter(Path.is_dir, p.iterdir())]
    except Exception:
        pass
    assert len(dbs) > 0, 'The directory %s must have subdirectories, where each one contains information for one database (and Apex) instance' % (properties['db.config.dir'])

    db_proxy_username = properties.get('db.proxy.username', '')
    db_username = properties.get('db.username', '')
    assert db_proxy_username or db_username, f'The database acount (Maven property db.proxy.username {db_proxy_username} or db.username {db_username}) must be set'

    logger.debug('return: (%s, %s, %s, %s, %s)' % (db_config_dir, dbs, profiles, db_proxy_username, db_username))
    return db_config_dir, dbs, profiles, db_proxy_username, db_username
