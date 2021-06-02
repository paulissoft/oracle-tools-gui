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
from gooey import Gooey, GooeyParser
import json

# local module(s)
import about


# logging.basicConfig(force=True, filename='oracle-tools-gui.log', encoding='utf-8', level=logging.INFO)
# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_SIZE = (1200, 800)
MENU = [{
           'name': 'Help',
           'items': [{
               'type': 'Link',
               'menuTitle': 'Documentation',
               'url': about.__help_url__
           }, {
               'type': 'AboutDialog',
               'menuTitle': 'About',
               'name': 'Oracle Tools',
               'description': 'Run the various Oracle Tools commands',
               'version': about.__version__,
               'copyright': about.__copyright__,
               'website': about.__url__,
               'author(s)': about.__author__,
               'license': about.__license__
           }]
       }]
TERMINAL_FONT_FAMILY = 'Courier New'


@Gooey(program='Get POM file',
       show_success_modal=False,
       show_failure_modal=True,
       show_restart_button=True,
       disable_progress_bar_animation=True,
       clear_before_run=True,
       default_size=DEFAULT_SIZE,
       menu=MENU,
       terminal_font_family=TERMINAL_FONT_FAMILY)
def get_POM_file(argv):
    logger.info('get_POM_file(%s)' % (argv))
    parser = GooeyParser(description='Get a POM file to work with')
    parser.add_argument(
        'file',
        help='The POM file',
        widget="FileChooser",
        gooey_options={
            'validator':{
                'test': "user_input[-7:] == 'pom.xml'",
                'message': 'This is not a POM file'
            }
        })
    args = parser.parse_args(argv)
    logger.info('args: %s' % (args))
    logger.info('return')


@Gooey(program='Run POM file',
       show_success_modal=True,
       show_failure_modal=True,
       show_restart_button=True,
       disable_progress_bar_animation=False,
       clear_before_run=True,
       required_cols=3,
       default_size=DEFAULT_SIZE,
       menu=MENU,
       terminal_font_family=TERMINAL_FONT_FAMILY)
def run_POM_file(pom_file):
    def db_order(db):
        for i, e in enumerate(['dev', 'tst', 'test', 'acc', 'prod', 'prd']):
            if e in db.lower():
                return i
        return 0

    logger.info('run_POM_file(%s)' % (pom_file))
    parser = GooeyParser(description='Get the POM settings to work with and run the POM file')
    dbs, profiles, db_proxy_username = process_POM(pom_file)
    db_proxy_password_help = f'The password for database account {db_proxy_username}'
    # 4 positional arguments
    parser.add_argument('action', help='The action to perform', choices=profiles, default=profiles[0])
    dbs_sorted = sorted(dbs, key=db_order)
    parser.add_argument('db', help='The database to log on to', choices=dbs_sorted, default=dbs_sorted[0])
    parser.add_argument('db-proxy-password', help=db_proxy_password_help, widget="PasswordField")
    parser.add_argument(
        'file',
        default=pom_file,
        help='The POM file (DO NOT CHANGE!)',
        gooey_options={
            'validator':{
                'test': "hash(user_input) == {}".format(hash(pom_file)),
                'message': 'Did you change the POM file?'
            }
        })
    args = parser.parse_args(list(pom_file))
    logger.info('args: %s' % (args))
    logger.info('return')


def process_POM(pom_file):
    """
    Process a single POM file and setup the GUI.
    The POM file must be either based on an Oracle Tools parent POM for the database or Apex.
    """
    def determine_POM_settings(pom_file):
        properties = {}
        profiles = set()

        cmd = f"mvn --file {pom_file} -N help:all-profiles -Pconf-inquiry compile"
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
                m = re.search("Profile Id: ([a-zA-Z0-9_.-]+) \(Active: .*, Source: pom\)", line)
                if m:
                    logger.info("adding profile: %s" % (m.group(1)))
                    profiles.add(m.group(1))
                else:
                    m = re.match('\[echoproperties\] ([a-zA-Z0-9_.-]+)=(.+)$', line)
                    if m:
                        logger.info("adding property %s = %s" % (m.group(1), m.group(2)))
                        properties[m.group(1)] = m.group(2)
                line = ''
        return properties, profiles

    logger.info('process_POM()')
    properties, profiles = determine_POM_settings(pom_file)
    apex_profiles = ['apex-export', 'apex-import']
    db_profiles = ['db-install', 'db-test', 'db-generate-ddl-full', 'db-generate-ddl-incr']
    if profiles.issuperset(set(apex_profiles)):
        profiles = apex_profiles
    elif profiles.issuperset(set(db_profiles)):
        profiles = db_profiles
    else:
        raise Exception('Profiles (%s) must be a super set of either the Apex (%s) or database (%s) profiles' % (profiles, set(apex_profiles), set(db_profiles)))
    assert properties['db.config.dir'], 'The property db.config.dir must have been set in order to choose a database (on of its subdirectories)'

    p = Path(properties['db.config.dir'])
    dbs = []
    try:
        dbs = [d.name for d in filter(Path.is_dir, p.iterdir())]
    except:
        pass
    assert len(dbs) > 0, 'The directory %s must have subdirectories, where each one contains information for one database (and Apex) instance' % (properties['db.config.dir'])

    db_proxy_username = properties['db.proxy.username']
    assert db_proxy_username, 'The Maven property db.proxy.username (the database proxy acount) must be set'

    logger.info('return: (%s, %s, %s)' % (dbs, profiles, db_proxy_username))
    return dbs, profiles, db_proxy_username


if __name__ == '__main__':
    logger.info('__main__(%s)' % (sys.argv))
    try:
        argv = [argc for argc in sys.argv[1:] if argc != '--']
        if len(argv) <= 1:
            if len(argv) == 0:
                argv.append(get_POM_file(argv))
            run_POM_file(argv[-1])
        else:
            assert len(argv) == 4
            profile, db, db_proxy_password, file = argv[0], argv[1], argv[2], argv[3]
            cmd = f'mvn -P{profile} -Ddb={db} -Ddb.proxy.password={db_proxy_password} --file {file}'
            logger.info('cmd: %s' % (cmd))
            subprocess.run(cmd, check=True, shell=True)
    except Exception as error:
        logger.exception(error)
        raise
    finally:
        logger.info('exit')
        logging.shutdown()
