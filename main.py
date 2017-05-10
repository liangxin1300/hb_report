# Copyright (C) 2017 Xin Liang <XLiang@suse.com>
# See COPYING for license information.
import atexit
import getopt
import multiprocessing
import os
import re
import sys
import datetime
import shutil

import constants
import utillib
from crmsh import utils as crmutils

def parse_argument(argv):
    try:
        opt, arg = getopt.getopt(argv[1:], constants.ARGOPTS_VALUE)
    except getopt.GetoptError:
        usage("short")

    if len(arg) == 0:
        constants.DESTDIR = "."
        constants.DEST = "hb_report-%s" % datetime.datetime.now().strftime('%w-%d-%m-%Y')
    elif len(arg) == 1:
        constants.TMP = arg[0]
    else:
        usage("short")

    for args, option in opt:
        if args == '-h':
            usage()
        if args == "-V":
            version()
        if args == '-f':
            constants.FROM_TIME = crmutils.parse_to_timestamp(option)
            utillib.check_time(constants.FROM_TIME, option)
        if args == '-t':
            constants.TO_TIME = crmutils.parse_to_timestamp(option)
            utillib.check_time(constants.TO_TIME, option)
        if args == "-n":
            constants.USER_NODES += " %s" % option
        if args == "-u":
            constants.SSH_USER = option
        if args == "-X":
            constants.SSH_OPTS += " %s" % option
        if args == "-l":
            constants.HA_LOG = option
        if args == "-e":
            constants.EDITOR = option
        if args == "-p":
            constants.SANITIZE += " %s" % option
        if args == "-s":
            constants.DO_SANITIZE = 1
        if args == "-Q":
            constants.SKIP_LVL += 1
        if args == "-L":
            constants.LOG_PATTERNS += " %s" % option
        if args == "-S":
            constants.NO_SSH = 1
        if args == "-D":
            constants.NO_DESCRIPTION = 1
        if args == "-Z":
            constants.FORCE_REMOVE_DEST = 1
        if args == "-M":
            constants.EXTRA_LOGS = ""
        if args == "-E":
            constants.EXTRA_LOGS += " %s" % option
        if args == "-v":
            constants.VERBOSITY += 1
        if args == '-d':
            constants.COMPRESS = ""

def run():
    if len(sys.argv) == 1:
        usage()

    utillib.check_env()
    constants.TMPFLIST = utillib.create_tempfile()
    atexit.register(utillib.drop_tempfiles)
    tmpdir = utillib.make_temp_dir()
    utillib.add_tmpfiles(tmpdir)

    if not is_collector():
        parse_argument(sys.argv)
        set_dest(constants.TMP)
        constants.WORKDIR = os.path.join(tmpdir, constants.DEST)
    else:
        constants.WORKDIR = os.path.join(tmpdir, constants.DEST, constants.WE)
    utillib._mkdir(constants.WORKDIR)

def set_dest(dest):
    if dest:
        constants.DESTDIR = utillib.get_dirname(dest)
        constants.DEST = os.path.basename(dest)
    if not os.path.isdir(constants.DESTDIR):
        utillib.log_fatal("%s is illegal directory name" % constants.DESTDIR)
    if not crmutils.is_filename_sane(constants.DEST):
        utillib.log_fatal("%s contains illegal characters" % constants.DEST)
    if not constants.COMPRESS:
        pass

def usage(short_msg=''):
    print("""
usage: report -f {time} [-t time]
       [-u user] [-X ssh-options] [-l file] [-n nodes] [-E files]
       [-p patt] [-L patt] [-e prog] [-MSDZQVsvhd] [dest]

        -f time: time to start from
        -t time: time to finish at (dflt: now)
        -d     : don't compress, but leave result in a directory
        -n nodes: node names for this cluster; this option is additive
                 (use either -n "a b" or -n a -n b)
                 if you run report on the loghost or use autojoin,
                 it is highly recommended to set this option
        -u user: ssh user to access other nodes (dflt: empty, root, hacluster)
        -X ssh-options: extra ssh(1) options
        -l file: log file
        -E file: extra logs to collect; this option is additive
                 (dflt: /var/log/messages)
        -s     : sanitize the PE and CIB files
        -p patt: regular expression to match variables containing sensitive data;
                 this option is additive (dflt: "passw.*")
        -L patt: regular expression to match in log files for analysis;
                 this option is additive (dflt: CRIT: ERROR:)
        -e prog: your favourite editor
        -Q     : don't run resource intensive operations (speed up)
        -M     : don't collect extra logs (/var/log/messages)
        -D     : don't invoke editor to write description
        -Z     : if destination directories exist, remove them instead of exiting
                 (this is default for CTS)
        -S     : single node operation; don't try to start report
                 collectors on other nodes
        -v     : increase verbosity
        -V     : print version
        dest   : report name (may include path where to store the report)
    """)
    if short_msg != "short":
        print("""
        . the multifile output is stored in a tarball {dest}.tar.bz2
        . the time specification is as in either Date::Parse or
          Date::Manip, whatever you have installed; Date::Parse is
          preferred
        . we try to figure where is the logfile; if we can't, please
          clue us in ('-l')
        . we collect only one logfile and /var/log/messages; if you
          have more than one logfile, then use '-E' option to supply
          as many as you want ('-M' empties the list)

        Examples

          report -f 2pm report_1
          report -f "2007/9/5 12:30" -t "2007/9/5 14:00" report_2
          report -f 1:00 -t 3:00 -l /var/log/cluster/ha-debug report_3
          report -f "09-sep-07 2:00" -u hbadmin report_4
          report -f 18:00 -p "usern.*" -p "admin.*" report_5

         . WARNING . WARNING . WARNING . WARNING . WARNING . WARNING .

          We won't sanitize the CIB and the peinputs files, because
          that would make them useless when trying to reproduce the
          PE behaviour. You may still choose to obliterate sensitive
          information if you use the -s and -p options, but in that
          case the support may be lacking as well. The logs and the
          crm_mon, ccm_tool, and crm_verify output are *not* sanitized.

          Additional system logs (/var/log/messages) are collected in
          order to have a more complete report. If you don't want that
          specify -M.

          IT IS YOUR RESPONSIBILITY TO PROTECT THE DATA FROM EXPOSURE!
        """)
    sys.exit(1)

def version():
    utillib.crmsh_info()
