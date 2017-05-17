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

def collect_for_nodes(nodes, arg_str):
    for node in nodes.split():
        if utillib.node_needs_pwd(node):
            pass
        else:
           p = multiprocessing.Process(target=utillib.start_slave_collector, args=(node, arg_str))
           p.start()
           p.join()

def dump_env():
    env_dict = {}
    env_dict["DEST"] = constants.DEST
    env_dict["FROM_TIME"] = constants.FROM_TIME
    env_dict["TO_TIME"] = constants.TO_TIME
    env_dict["USER_NODES"] = constants.USER_NODES
    env_dict["NODES"] = constants.NODES
    env_dict["HA_LOG"] = constants.HA_LOG
    #env_dict["UNIQUE_MSG"] = constants.UNIQUE_MSG
    env_dict["SANITIZE"] = constants.SANITIZE
    env_dict["DO_SANITIZE"] = int(constants.DO_SANITIZE)
    env_dict["SKIP_LVL"] = int(constants.SKIP_LVL)
    env_dict["EXTRA_LOGS"] = constants.EXTRA_LOGS
    env_dict["PCMK_LOG"] = constants.PCMK_LOG
    env_dict["VERBOSITY"] = int(constants.VERBOSITY)

    res_str = ""
    for k, v in env_dict.items():
        res_str += " {}={}".format(k, v)
    return res_str

def get_log():
    outf = os.path.join(constants.WORKDIR, constants.HALOG_F)

    # collect journal from systemd unless -M was passed
    if constants.EXTRA_LOGS:
        utillib.collect_journal(constants.FROM_TIME, \
                                constants.TO_TIME, \
                                os.path.join(constants.WORKDIR, constants.JOURNAL_F))

    if constants.HA_LOG and not os.path.isfile(constants.HA_LOG):
        if not is_collector():
            utillib.log_warning("%s not found; we will try to find log ourselves" % ha_log)
            constants.HA_LOG = ""
    if not constants.HA_LOG:
        constants.HA_LOG = utillib.find_log()
    if (not constants.HA_LOG) or (not os.path.isfile(constants.HA_LOG)):
        if constants.CTS:
            pass #TODO
        else:
            utillib.log_warning("not log at %s" % constants.WE)
        return

    if constants.CTS:
        pass #TODO
    else:
        getstampproc = utillib.find_getstampproc(constants.HA_LOG)
        if getstampproc:
            constants.GET_STAMP_FUNC = getstampproc
            utillib.dump_logset(constants.HA_LOG, constants.FROM_TIME, constants.TO_TIME, outf)
            utillib.log_size(constants.HA_LOG, outf+'.info')
        else:
            utillib.log_warning("could not figure out the log format of %s" % constants.HA_LOG)

def is_collector():
    if sys.argv[1] == "__slave":
        return True
    return False

def load_env(env_str):
    list_ = []
    for tmp in env_str.split():
        if re.search('=', tmp):
            item = tmp
        else:
            list_.remove(item)
            item += " %s" % tmp
        list_.append(item)

    env_dict = {}
    env_dict = crmutils.nvpairs2dict(list_)
    constants.DEST = env_dict["DEST"]
    constants.FROM_TIME = float(env_dict["FROM_TIME"])
    constants.TO_TIME = float(env_dict["TO_TIME"])
    constants.USER_NODES = env_dict["USER_NODES"]
    constants.NODES = env_dict["NODES"]
    constants.HA_LOG = env_dict["HA_LOG"]
    #constants.UNIQUE_MSG = env_dict["UNIQUE_MSG"]
    constants.SANITIZE = env_dict["SANITIZE"]
    constants.DO_SANITIZE = int(env_dict["DO_SANITIZE"])
    constants.SKIP_LVL = int(env_dict["SKIP_LVL"])
    constants.EXTRA_LOGS = env_dict["EXTRA_LOGS"]
    constants.PCMK_LOG = env_dict["PCMK_LOG"]
    constants.VERBOSITY = int(env_dict["VERBOSITY"])

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

    if is_collector():
        load_env(' '.join(sys.argv[2:]))

    utillib.compatibility_pcmk()
    if constants.CTS == "" or is_collector():
        utillib.get_log_vars()

    if not is_collector():
        constants.NODES = ' '.join(utillib.get_nodes())
        utillib.log_debug("nodes: %s"%constants.NODES)
    if constants.NODES == "":
        utillib.log_fatal("could not figure out a list of nodes; is this a cluster node?")
    if constants.WE in constants.NODES.split():
        constants.THIS_IS_NODE = 1 
  
    if not is_collector():
        if constants.THIS_IS_NODE != 1:
            utillib.log_warning("this is not a node and you didn't specify a list of nodes using -n")
#
# ssh business
#
        if not constants.NO_SSH:
            utillib.find_ssh_user()
            if constants.SSH_USER:
                constants.SSH_OPTS += " -o User=%s" % constants.SSH_USER
        if ((not constants.SSH_USER) and (os.getuid() != 0)) or \
           constants.SSH_USER and constants.SSH_USER != "root":
            utillib.log_debug("ssh user other than root, use sudo")
            constants.SUDO = "sudo -u root"
        if os.getuid() != 0:
            utillib.log_debug("local user other than root, use sudo")
            constants.LOCAL_SUDO = "sudo -u root"

    if constants.THIS_IS_NODE == 1:
        get_log()

    if not is_collector():
        arg_str = dump_env()
        if not constants.NO_SSH:
            collect_for_nodes(constants.NODES, arg_str)
        elif constants.THIS_IS_NODE == 1:
            collect_for_nodes(constants.WE, arg_str)

    if is_collector():
        utillib.collect_info()
        cmd = r"cd %s/.. && tar -h -cf - %s" % (constants.WORKDIR, constants.WE)
        code, out, err = crmutils.get_stdout_stderr(cmd)
        print out
    else:
        p_list = []
        p_list.append(multiprocessing.Process(target=utillib.analyze))
        p_list.append(multiprocessing.Process(target=utillib.events, args=(constants.WORKDIR,)))
        for p in p_list:
            p.start()

        utillib.check_if_log_is_empty()
        utillib.mktemplate(sys.argv)

        for p in p_list:
            p.join()

        if constants.COMPRESS == 1:
            utillib.pick_compress()
            cmd = r"(cd %s/.. && tar cf - %s)|%s > %s/%s.tar%s" % (\
                  constants.WORKDIR, constants.DEST, constants.COMPRESS_PROG,\
                  constants.DESTDIR, constants.DEST, constants.COMPRESS_EXT)
            crmutils.ext_cmd(cmd)
        else:
            shutil.move(constants.WORKDIR, constants.DESTDIR)
        utillib.finalword()

def set_dest(dest):
    if dest:
        constants.DESTDIR = utillib.get_dirname(dest)
        constants.DEST = os.path.basename(dest)
    if not os.path.isdir(constants.DESTDIR):
        utillib.log_fatal("%s is illegal directory name" % constants.DESTDIR)
    if not crmutils.is_filename_sane(constants.DEST):
        utillib.log_fatal("%s contains illegal characters" % constants.DEST)
    if not constants.COMPRESS and os.path.isdir(os.path.join(constants.DESTDIR, constants.DEST)):
        if constants.FORCE_REMOVE_DEST:
            shutil.rmtree(os.path.join(constants.DESTDIR, constants.DEST))   
        else:
            utillib.log_fatal("destination directory DESTDIR/DEST exists, please cleanup or use -Z")

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
    print utillib.crmsh_info().strip('\n')
    sys.exit(0)

run()
# vim:ts=4:sw=4:et:
