# Copyright (C) 2017 Xin Liang <XLiang@suse.com>
# See COPYING for license information.
import bz2
import datetime
import glob
import gzip
import multiprocessing
import os
import pwd
import random
import re
import shutil
import stat
import string
import subprocess
import sys
import tempfile
import contextlib
from dateutil import tz
from threading import Timer

import constants
import crmsh.config
from crmsh import msg as crmmsg
from crmsh import utils as crmutils

def _mkdir(directory):
    """
    from crmsh/tmpfiles.py
    """
    if not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError as err:
            log_fatal("Failed to create directory: %s"%(err))

def add_tmpfiles(contents):
    """
    add contents for removing when program exit
    """
    with open(constants.TMPFLIST, 'a') as f:
        f.write(contents+'\n')

# go through archived logs (timewise backwards) and see if there
# are lines belonging to us   
# (we rely on untouched log files, i.e. that modify time
# hasn't been changed)
def arch_logs(logf, from_time, to_time):
    ret = []
    files = [logf]
    files += glob.glob(logf+"*[0-z9]")
    for f in sorted(files, key=os.path.getctime):
        res = is_our_log(f, from_time, to_time)
        if res == 0:
            continue
        elif res == 1:
            ret.append(f)
            log_debug("found log %s" % f)
        elif res == 2:
            break
        elif res == 3:
            ret.append(f)
            log_debug("found log %s" % f)
            break
    return ret

def base_check():
    if not which("which"):
        log_fatal("please install the which(1) program")

def booth_info():
    if not which("booth"):
        return ""
    return get_command_info("booth --version")[1]

def check_env():   
    set_env()
    base_check()
    get_ocf_dir()
    load_ocf_dirs()

def check_perms():
    out_string = ""

    for check_dir in [constants.PCMK_LIB, constants.PE_STATE_DIR, constants.CIB_DIR]:
        flag = 0
        out_string += "##### Check perms for %s: " % check_dir
        stat_info = os.stat(check_dir)
        if not stat.S_ISDIR(stat_info.st_mode):
            flag = 1
            out_string += "\n%s wrong type or doesn't exist\n" % check_dir
            continue
        if stat_info.st_uid != pwd.getpwnam('hacluster')[2] or\
           stat_info.st_gid != pwd.getpwnam('hacluster')[3] or\
           "%04o"%(stat_info.st_mode&07777) != "0750":
            flag = 1
            out_string += "\nwrong permissions or ownership for %s: " % check_dir
            out_string += get_command_info("ls -ld %s"%check_dir)[1] + '\n'
        if flag == 0:
            out_string += "OK\n"

    perms_f = os.path.join(constants.WORKDIR, constants.PERMISSIONS_F)
    crmutils.str2file(out_string, perms_f)

def check_time(var, option):
    if not var:
        log_fatal("""bad time specification: %s 
                        try these like: 2pm
                                        1:00
                                        "2007/9/5 12:30"
                                        "09-Sep-07 2:00"
                  """%option)

def cluster_info():
    return get_command_info("corosync -v")[1]

def collect_info():
    process_list = []
    process_list.append(multiprocessing.Process(target=sys_info))
    process_list.append(multiprocessing.Process(target=sys_stats))
    process_list.append(multiprocessing.Process(target=get_pe_inputs))
    process_list.append(multiprocessing.Process(target=crm_config))
    process_list.append(multiprocessing.Process(target=touch_dc))

    for p in process_list[0:2]:
        p.start()
    get_config()
    for p in process_list[2:]:
        p.start()

    get_backtraces()
    get_configurations()
    check_perms()
    dlm_dump()
    time_status()
    corosync_blackbox()
    get_ratraces()

    for p in process_list:
        p.join()
    if constants.SKIP_LVL == 0:
        sanitize()

def collect_journal(from_t, to_t, outf):
    if not which("journalctl"):
        log_warning("Command journalctl not found")
        return

    if crmutils.is_int(from_t) and from_t == 0:
        from_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    elif crmutils.is_int(from_t):
        from_time = ts_to_dt(from_t).strftime("%Y-%m-%d %H:%M")
    if crmutils.is_int(to_t) and to_t == 0:
        to_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    elif crmutils.is_int(to_t):
        to_time = ts_to_dt(to_t).strftime("%Y-%m-%d %H:%M")
    if os.path.isfile(outf):
        log_warning("%s already exists" % outf)

    log_debug("journalctl from: '%d' until: '%d' from_time: '%s' to_time: '%s' > %s" % \
             (from_t, to_t, from_time, to_time, outf))
    cmd = 'journalctl -o short-iso --since "%s" --until "%s" --no-pager | tail -n +2' % \
          (from_time, to_time)
    crmutils.str2file(get_command_info(cmd)[1], outf)

def compatibility_pcmk():     
    get_crm_daemon_dir()      
    if not constants.CRM_DAEMON_DIR:
        log_fatal("cannot find pacemaker daemon directory!")
    get_pe_state_dir()        
    if not constants.PE_STATE_DIR:     
        log_fatal("cannot find pe daemon directory!")
    get_cib_dir()  
    if not constants.CIB_DIR:
        log_fatal("cannot find cib daemon directory!")

    constants.PCMK_LIB = os.path.dirname(constants.CIB_DIR)
    log_debug("setting PCMK_LIB to %s" % constants.PCMK_LIB)
    constants.CORES_DIRS = os.path.join(constants.PCMK_LIB, "cores")
    constants.CONF = "/etc/corosync/corosync.conf"
    if os.path.isfile(constants.CONF): 
        constants.CORES_DIRS += " /var/lib/corosync"
    constants.B_CONF = os.path.basename(constants.CONF)

def corosync_blackbox():
    fdata_list = []
    for f in find_files("/var/lib/corosync", constants.FROM_TIME, constants.TO_TIME):
        if re.search("fdata", f):
            fdata_list.append(f)
    if fdata_list:
        blackbox_f = os.path.join(constants.WORKDIR, constants.COROSYNC_RECORDER_F)
        crmutils.str2file(get_command_info("corosync-blackbox")[1], blackbox_f)

def create_tempfile(time=None):        
    random_str = random_string(4)  
    try:
        filename = tempfile.mkstemp(suffix=random_str, prefix="tmp.")[1]
    except:
        log_fatal("Can't create file %s" % filename)
    if time:
        os.utime(filename, (time, time))
    return filename

def crm_config():
    workdir = constants.WORKDIR
    if os.path.isfile(os.path.join(workdir, constants.CIB_F)):
        cmd = r"CIB_file=%s/%s crm configure show" % (workdir, constants.CIB_F)
        crmutils.str2file(get_command_info(cmd)[1], os.path.join(workdir, constants.CIB_TXT_F))

def crm_info():
    return get_command_info("%s/crmd version" % constants.CRM_DAEMON_DIR)[1]

def crmsh_info():
    return get_command_info("crm report -V")[1]

def dlm_dump():
    #TODO
    pass

def drop_tempfiles():
    with open(constants.TMPFLIST, 'r') as f:
        for line in f.read().split('\n'):
            if os.path.isdir(line):
                shutil.rmtree(line)
            if os.path.isfile(line):
                os.remove(line)
    os.remove(constants.TMPFLIST)

def dump_log(logf, from_line, to_line):
    if not from_line:
        return
    return filter_lines(logf, from_line, to_line)

def dump_logset(logf, from_time, to_time, outf):
    """
    find log/set of logs which are interesting for us
    """
    if os.stat(logf).st_size == 0:
        return
    logf_set = arch_logs(logf, from_time, to_time)
    if not logf_set:
        return
    num_logs = len(logf_set)
    oldest = logf_set[-1]
    newest = logf_set[0]
    mid_logfiles = logf_set[1:-1]
    out_string = ""
    if num_logs == 1:
        out_string += print_logseg(newest, from_time, to_time)
    else:
        out_string += print_logseg(oldest, from_time, 0)
        for f in mid_logfiles:
            out_string += print_log(f)
            log_debug("including complete %s logfile" % f)
        out_string += print_logseg(newest, 0, to_time)

    crmutils.str2file(out_string, outf)

def dump_state(workdir):
    res = grep("^Last upd", incmd="crm_mon -1", flag="v")
    crmutils.str2file('\n'.join(res), os.path.join(workdir, constants.CRM_MON_F))
    cmd = "cibadmin -Ql"
    crmutils.str2file(get_command_info(cmd)[1], os.path.join(workdir, constants.CIB_F))
    cmd = "crm_node -p"
    crmutils.str2file(get_command_info(cmd)[1], os.path.join(workdir, constants.MEMBERSHIP_F))

def find_decompressor(log_file):
    decompressor = "echo"
    if re.search("bz2$", log_file):
        decompressor = "bzip2 -dc"
    elif re.search("gz$", log_file):
        decompressor = "gzip -dc"
    elif re.search("xz$", log_file):
        decompressor = "xz -dc"
    else:
        if re.search("text", get_command_info("file %s" % log_file)[1]):
            decompressor = "cat"
    return decompressor

def find_files(dirs, from_time, to_time):
    res = []

    if (not crmutils.is_int(from_time)) or (from_time <= 0):
        log_warning("sorry, can't find files based on time if you don't supply time")
        return

    from_stamp = create_tempfile(from_time)
    add_tmpfiles(from_stamp)
    findexp = "-newer %s" % from_stamp

    if crmutils.is_int(to_time) and to_time > 0:
        to_stamp = create_tempfile(to_time)
        add_tmpfiles(to_stamp)
        findexp += " ! -newer %s" % to_stamp

    cmd = r"find %s -type f %s" % (dirs, findexp)
    cmd_res = get_command_info(cmd)[1].strip()
    if cmd_res:
        res = cmd_res.split('\n')

    return res

def find_first_ts(data):
    for line in data:
        ts = get_ts(line)
        if ts:
            break
    return ts

def filter_lines(logf, from_line, to_line=None):
    out_string = ""
    if not to_line:
        to_line = sum(1 for l in open(logf, 'r'))

    count = 1
    with open(logf, 'r') as f:
        for line in f.readlines():
            if count >= from_line and count <= to_line:
                out_string += line
            if count > to_line:
                break
            count += 1
    return out_string

def find_getstampproc(log_file):
    func = None
    loop_cout = 10
    with open(log_file, 'r') as f:
        for line in f.readlines():
            if loop_cout == 0:
                break
            else:
                loop_cout -= 1
            with stdchannel_redirected(sys.stderr, os.devnull):
                func = find_getstampproc_raw(line.strip('\n'))
                if func:
                    break
    return func

def find_getstampproc_raw(line):
    func = None
    res = get_stamp_rfc5424(line)
    if res:
        func = "rfc5424"
        log_debug("the log file is in the rfc5424 format")
        return func
    res = get_stamp_syslog(line)
    if res:
        func = "syslog"
        log_debug("the log file is in the syslog format")
        return func
    res = get_stamp_legacy(line)
    if res:
        func = "legacy"
        log_debug("the log file is in the legacy format (please consider switching to syslog format)")
        return func
    return func

def find_log():
    if constants.EXTRA_LOGS:
        for l in constants.EXTRA_LOGS.split():
            if os.path.isfile(l) and l != constants.PCMK_LOG:
                return l

        tmp_f = os.path.join(constants.WORKDIR, constants.JOURNAL_F)
        if os.path.isfile(tmp_f):
            return tmp_f

        if os.path.isfile(constants.PCMK_LOG):
            return constants.PCMK_LOG

    if constants.HA_DEBUGFILE:
        log_debug("will try with %s" % constants.HA_DEBUGFILE)
    return constants.HA_DEBUGFILE

def find_ssh_user():
    ssh_user = "__undef"
    if not constants.SSH_USER:
        try_user_list = "__default " + constants.TRY_SSH
    else:
        try_user_list = constants.SSH_USER

    for n in constants.NODES.split():
        rc = 1
        if n == constants.WE:
            continue
        for u in try_user_list.split():
            if u != '__default':
                ssh_s = '@'.join((u, n))
            else:
                ssh_s = n

            if test_ssh_conn(ssh_s):
                log_debug("ssh %s OK" % ssh_s)
                ssh_user = u
                try_user_list = u
                rc = 0
                break
            else:
                log_debug("ssh %s failed" % ssh_s)
        if rc == 1:
            constants.SSH_PASSWORD_NODES += " %s" % n

    if constants.SSH_PASSWORD_NODES:
        log_warning("passwordless ssh to node(s) %s does not work" % constants.SSH_PASSWORD_NODES)
    if ssh_user == "__undef":
        return
    if ssh_user != "__default":
        constants.SSH_USER = ssh_user

def findln_by_time(logf, tm):
    tmid = None
    first = 1
    last = sum(1 for l in open(logf, 'r'))
    while first <= last:
        mid = (last+first)/2
        trycnt = 10
        while trycnt > 0:
            res = line_time(logf, mid)
            if res:
                tmid = int(res)
                break
            log_debug("cannot extract time: %s:%d; will try the next one" % (logf, mid))
            trycnt -= 1
            prevmid = mid
            while prevmid == mid:
                first -= 1
                if first < 1:
                    first = 1
                last -= 1
                if last < first:
                    last = first
                prevmid = mid
                mid = (last+first)/2
                if first == last:
                    break
        if not tmid:
            log_warning("giving up on log...")
            return
        if int(tmid) > tm:
            last = mid - 1
        elif int(tmid) < tm:
            first = mid + 1
        else:
            break
    return mid

def get_backtraces():
    flist = []
    for f in find_files(constants.CORES_DIRS, constants.FROM_TIME, constants.TO_TIME):
        bf = os.path.basename(f)
        if re.search("core", bf):
            flist.append(f)
    if flist:
        get_bt(flist)
        log_debug("found backtraces: %s" % ' '.join(flist))

def get_cib_dir():
    try:
        constants.CIB_DIR = crmsh.config.path.crm_config
    except:
        return
    if not os.path.isdir(constants.CIB_DIR):
        constants.CIB_DIR = None

def get_command_info(cmd):
    code, out, err = crmutils.get_stdout_stderr(cmd)
    if out:
        return (code, out + '\n')  
    else:
        return (code, "")

def get_conf_var(option, default=None):
    ret = default
    with open(constants.CONF, 'r') as f:
        for line in f.read().split('\n'):
            if re.match("^\s*%s\s*:"%option, line):
                ret = line.split(':')[1].lstrip()
    return ret

def get_config():
    workdir = constants.WORKDIR
    if os.path.isfile(constants.CONF):
        shutil.copy2(constants.CONF, workdir)
    if crmutils.is_process("crmd"):
        dump_state(workdir)
        with open(os.path.join(workdir, "RUNNING"), 'w') as f:
            pass
    else:
        shutil.copy2(os.path.join(constants.CIB_DIR, constants.CIB_F), workdir)
        with open(os.path.join(workdir, "STOPPED"), 'w') as f:
            pass
    if os.path.isfile(os.path.join(workdir, constants.CIB_F)):
        cmd = "crm_verify -V -x %s" % os.path.join(workdir, constants.CIB_F)
        crmutils.str2file(get_command_info(cmd)[1], os.path.join(workdir, constants.CRM_VERIFY_F))

def get_configurations():
    workdir = constants.WORKDIR
    for conf in constants.CONFIGURATIONS:
        if os.path.isfile(conf):
            shutil.copy2(conf, workdir)
        elif os.path.isdir(conf):
            shutil.copytree(conf, os.path.join(workdir, os.path.basename(conf)))

def get_crm_daemon_dir():
    try:
        constants.CRM_DAEMON_DIR = crmsh.config.path.crm_daemon_dir
    except:
        return
    if not os.path.isdir(constants.CRM_DAEMON_DIR) or \
       not is_exec(os.path.join(constants.CRM_DAEMON_DIR, "crmd")):
        constants.CRM_DAEMON_DIR = None

def get_dirname(path):
    tmp = os.path.dirname(path)
    if not tmp:
        tmp = "."
    return tmp

def get_log_vars():
    if is_conf_set("debug"):
        constants.HA_LOGLEVEL = "debug"
    if is_conf_set("to_logfile"):
        constants.HA_LOGFILE = get_conf_var("logfile", default="syslog")
        constants.HA_DEBUGFILE = constants.HA_LOGFILE
    elif is_conf_set("to_syslog"):
        constants.HA_LOGFACILITY = get_conf_var("syslog_facility", default="daemon")

    log_debug("log settings: facility=%s logfile=%s debugfile=%s" % \
             (constants.HA_LOGFACILITY, constants.HA_LOGFILE, constants.HA_DEBUGFILE))

def get_nodes():
    nodes = []
    # 1. set by user?
    if constants.USER_NODES:
        nodes = constants.USER_NODES.split()
    # 2. running crm
    elif crmutils.is_process("crmd"):
        cmd = "crm node server"
        nodes = get_command_info(cmd)[1].strip().split('\n')
    # 3. if the cluster's stopped, try the CIB
    else:
        cmd = r"(CIB_file=%s/%s crm node server)" % (constants.CIB_DIR, constants.CIB_F)
        nodes = get_command_info(cmd)[1].strip().split('\n')

    return nodes

def get_ratraces():
    trace_dir = os.path.join(constants.HA_VARLIB, "trace_ra")
    if not os.path.isdir(trace_dir):
        return
    log_debug("looking for RA trace files in %s" % trace_dir)
    flist = []
    for f in find_files(trace_dir, constants.FROM_TIME, constants.TO_TIME):
        flist.append(os.path.join("trace_ra", '/'.join(f.split('/')[-2:])))
    if flist:
        cmd = "tar -cf - -C `dirname %s` %s | tar -xf - -C %s" % (trace_dir, ' '.join(flist), constants.WORKDIR)
        crmutils.ext_cmd(cmd)
        log_debug("found %d RA trace files in %s" % (len(flist), trace_dir))

def get_pe_inputs():
    from_time = constants.FROM_TIME
    to_time = constants.TO_TIME
    work_dir = constants.WORKDIR
    pe_dir = constants.PE_STATE_DIR
    log_debug("looking for PE files in %s in %s" % (pe_dir, constants.WE))

    flist = []
    for f in find_files(pe_dir, from_time, to_time):
        if re.search("[.]last$", f):
            continue
        flist.append(f)

    if flist:
        flist_dir = os.path.join(work_dir, os.path.basename(pe_dir))
        _mkdir(flist_dir)
        for f in flist:
            os.symlink(f, os.path.join(flist_dir, os.path.basename(f)))
        log_debug("found %d pengine input files in %s" % (len(flist), pe_dir))

    if len(flist) <= 20:
        if constants.SKIP_LVL == 0:
            for f in flist:
                pe_to_dot(os.path.join(flist_dir, os.path.basename(f)))
    else:
        log_debug("too many PE inputs to create dot files")

def get_ocf_dir():
    ocf_dir = None
    try:
        ocf_dir = crmsh.config.path.ocf_root
    except:
        log_fatal("Can not find OCF_ROOT_DIR!")
    if not os.path.isdir(ocf_dir):
        log_fatal("Directory %s is not OCF_ROOT_DIR!" % ocf_dir)
    constants.OCF_DIR = ocf_dir

def get_pe_state_dir():
    try:
        constants.PE_STATE_DIR = crmsh.config.path.pe_state_dir
    except:
        return
    if not os.path.isdir(constants.PE_STATE_DIR):
        constants.PE_STATE_DIR = None

def get_pkg_mgr():
    pkg_mgr = None

    if which("dpkg"):
        pkg_mgr = "deb"
    elif which("rpm"):
        pkg_mgr = "rpm"
    elif which("pkg_info"):
        pkg_mgr = "pkg_info"
    elif which("pkginfo"):
        pkg_mgr = "pkginfo"
    else:
        log_warning("Unknown package manager!")

    return pkg_mgr

def get_stamp_legacy(line):   
    try:
        res = crmutils.parse_time(line.split()[1])
    except:
        return None
    return res

def get_stamp_rfc5424(line):  
    try:
        res = crmutils.parse_time(line.split()[0])
    except:
        return None
    return res

def get_stamp_syslog(line):   
    try:
        res = crmutils.parse_time(' '.join(line.split()[0:3]))
    except:
        return None
    return res

def get_ts(line):
    ts = None
    with stdchannel_redirected(sys.stderr, os.devnull):
        if not constants.GET_STAMP_FUNC:
            func = find_getstampproc_raw(line)
        else:
            func = constants.GET_STAMP_FUNC
        if func:
            if func == "rfc5424":
                ts = crmutils.parse_to_timestamp(line.split()[0])
            if func == "syslog":
                ts = crmutils.parse_to_timestamp(line.split()[1])
            if func == "legacy":
                ts = crmutils.parse_to_timestamp(' '.join(line.split()[0:3]))
    return ts

def grep(pattern, infile=None, incmd=None, flag=None):
    res = []
    if not infile and not incmd:
        return res

    if infile:
        if os.path.isfile(infile):
            res = grep_file(pattern, infile, flag)
        elif os.path.isdir(infile):
            for root, dirs, files in os.walk(infile):
                for f in files:
                    res += grep_file(pattern, os.path.join(root, f), flag)
        else:
            for f in glob.glob(infile):
                res += grep_file(pattern, f, flag)
    elif incmd:
        res += grep_row(pattern, get_command_info(incmd)[1], flag)

    if flag and "q" in flag:
        return len(res) != 0
    return res

def grep_file(pattern, infile, flag):
    res = []
    with open(infile, 'r') as fd:
        res = grep_row(pattern, fd.read(), flag)
        if res:
            if flag and "l" in flag:
                return [infile]
        return res

def grep_row(pattern, indata, flag):
    INVERT = False
    SHOWNUM = False
    reflag = 0
    if flag:
        if "v" in flag:
            INVERT = True
        if "i" in flag:
            reflag |= re.I
        if "w" in flag:
            pattern = r"\b%s\b" % pattern
        if "n" in flag:
            SHOWNUM = True

    res = []
    count = 0
    for line in indata.split('\n')[:-1]:
        count += 1
        if re.search(pattern, line, reflag):
            if not INVERT:
                if SHOWNUM:
                    res.append("%d:%s"%(count, line))
                else:
                    res.append(line)
        elif INVERT:
            if SHOWNUM:
                res.append("%d:%s"%(count, line))
            else:
                res.append(line)
    return res

def is_conf_set(option, subsys=None):
    subsys_start = 0
    with open(constants.CONF, 'r') as f:
        for line in f.read().split('\n'):
            if re.search("^\s*subsys\s*:\s*%s$" % subsys, line):
                subsys_start = 1
            if subsys_start == 1 and re.search("^\s*}", line):
                subsys_start = 0
            if re.match("^\s*%s\s*:\s*(on|yes)$" % option, line):
                if not subsys or subsys_start == 1:
                    return True
    return False

def is_exec(filename):
    return os.path.isfile(filename) and os.access(filename, os.X_OK)

#
# check if the log contains a piece of our segment
#
def is_our_log(logf, from_time, to_time):
    with open(logf, 'r') as fd:
        data = fd.read()
        first_time = find_first_ts(head(10, data))
        last_time = find_first_ts(tail(10, data)[::-1])

    if (not first_time) or (not last_time):
        return 0 # skip (empty log?)
    if from_time > last_time:
        # we shouldn't get here anyway if the logs are in order 
        return 2 # we're past good logs; exit
    if from_time >= first_time:
        return 3 # this is the last good log
    if to_time == 0 or to_time >= first_time:
        return 1 # include this log
    else:
        return 0 # don't include this log

def line_time(logf, line_num):
    ts = None
    with open(logf, 'r') as fd:
        ts = get_ts(tail(line_num, fd.read())[0])
    return ts

def load_ocf_dirs():
    inf = "%s/lib/heartbeat/ocf-directories" % constants.OCF_DIR
    if not os.path.isfile(inf):
        log_fatal("file %s not exist" % inf)
    constants.HA_VARLIB = grep("HA_VARLIB:=", infile=inf)[0].split(':=')[1].strip('}')
    constants.HA_BIN = grep("HA_BIN:=", infile=inf)[0].split(':=')[1].strip('}')

def log_debug(msg):           
    if constants.VERBOSITY > 0 or crmsh.config.core.debug:
        crmmsg.common_info("%s# %s" % (constants.WE, msg))

def log_info(msg):
    crmmsg.common_info("%s# %s" % (constants.WE, msg))

def log_fatal(msg):
    crmmsg.common_err("%s# %s" % (constants.WE, msg))
    sys.exit(1)

def log_size(logf, outf):
    l_size = os.stat(logf).st_size + 1
    out_string = "%s %d" % (logf, l_size)
    crmutils.str2file(out_string, outf)

def log_warning(msg):
    crmmsg.common_warn("%s# %s" % (constants.WE, msg))

def make_temp_dir():          
    dir_path = r"/tmp/.hb_report.workdir.%s" % random_string(6)
    _mkdir(dir_path)          
    return dir_path

def node_needs_pwd(node):
    for n in constants.SSH_PASSWORD_NODES.split():
        if n == node:
            return True
    return False

def pkg_ver_deb(packages):
    pass

def pkg_ver_pkg_info(packages):
    pass

def pkg_ver_pkginfo(packages):
    pass

def pkg_ver_rpm(packages):
    res = ""
    for pack in packages.split():
        code, out = get_command_info("rpm -qi %s"%pack)
        if code != 0:
            continue
        for line in out.split('\n'):
            if re.match("^Name\s*:", line):
                name = line.split(':')[1].lstrip()
            elif re.match("^Version\s*:", line):
                version = line.split(':')[1].lstrip()
            elif re.match("^Release\s*:", line):
                release = line.split(':')[1].lstrip()
            elif re.match("^Distribution\s*:", line):
                distro = line.split(':')[1].lstrip()
            elif re.match("^Architecture\s*:", line):
                arch = line.split(':')[1].lstrip()
        res += "%s %s-%s - %s %s\n" % (name, version, release, distro, arch)
    return res

def pkg_versions(packages):
    pkg_mgr = get_pkg_mgr()
    if not pkg_mgr:
        return ""
    log_debug("the package manager is %s" % pkg_mgr)
    if pkg_mgr == "deb":
        return pkg_ver_deb(packages)
    if pkg_mgr == "rpm":
        return pkg_ver_rpm(packages)
    if pkg_mgr == "pkg_info":
        return pkg_ver_pkg_info(packages)
    if pkg_mgr == "pkginfo":
        return pkg_ver_pkginfo(packages)

def print_log(logf):
    cat = find_decompressor(logf)
    cmd = "%s %s" % (cat, logf)
    _. out = crmutils.get_stdout(cmd)
    return out

def print_logseg(logf, from_time, to_time):
    cat = find_decompressor(logf)
    if cat != "cat":
        tmp = create_tempfile()
        add_tmpfiles(tmp)
        cmd = "%s %s > %s" % (cat, logf, tmp)
        code, out, err = crmutils.get_stdout_stderr(cmd)
        if code != 0:
            log_fatal("maybe disk full: %s" % err)
        sourcef = tmp
    else:
        sourcef = logf
        tmp = ""

    if from_time == 0:
        FROM_LINE = 1
    else:
        FROM_LINE = findln_by_time(sourcef, from_time)

    if not FROM_LINE:
        log_warning("couldn't find line for time %d; corrupt log file?" % from_time)
        return

    TO_LINE = ""
    if to_time != 0:
        TO_LINE = findln_by_time(sourcef, to_time)
        if not TO_LINE:
            log_warning("couldn't find line for time %d; corrupt log file?" % to_time)
            return

    log_debug("including segment [%s-%s] from %s" % (FROM_LINE, TO_LINE, sourcef))
    return dump_log(sourcef, FROM_LINE, TO_LINE)

def ra_build_info():
    inf = "%s/lib/heartbeat/ocf-shellfuncs" % constants.OCF_DIR
    out = grep("Build version:", infile=inf)[0]
    if re.search(r"\$Format:%H\$", out):
        out = "UNKnown"
    return "resource-agents: %s\n" % out

def random_string(num):       
    tmp = []
    if crmutils.is_int(num) and num > 0:
        s = string.letters + string.digits
        tmp = random.sample(s, num)
    return ''.join(tmp)

def sanitize():
    workdir = constants.WORKDIR
    conf = os.path.join(workdir, constants.B_CONF)
    if os.path.isfile(conf):
        sanitize_one(conf)
    cib_f = os.path.join(workdir, constants.CIB_F)
    rc = 0
    for f in [cib_f] + glob.glob(os.path.join(workdir, "pengine", "*")):
        if os.path.isfile(f):
            if constants.DO_SANITIZE == 1:
                sanitize_one(f)
            else:
                rc = sanitize_one(f, "test")
    if rc != 0:
        log_warning("some PE or CIB files contain possibly sensitive data")
        log_warning("you may not want to send this report to a public mailing list")

def sanitize_one(in_file, mode=None):
    open_ = None
    if re.search("gz$", in_file):
        open_ = gzip.open
    elif re.search("bz2$", in_file):
        open_ = bz2.BZ2File
    else:
        open_ = open
    with open_(in_file, 'r') as f:
        data = f.read()

    if mode == "test":
        if sub_string_test(data):
            return 1
        else:
            return 0

    ref = create_tempfile()
    add_tmpfiles(ref)
    touch_r(in_file, ref)

    with open_(in_file, 'w') as f:
        f.write(sub_string(data))

    touch_r(ref, in_file)

def set_env():
    os.environ["LC_ALL"] = "POSIX"

@contextlib.contextmanager
def stdchannel_redirected(stdchannel, dest_filename):
    """
    A context manager to temporarily redirect stdout or stderr
    e.g.:
    with stdchannel_redirected(sys.stderr, os.devnull):
        if compiler.has_function('clock_gettime', libraries=['rt']):
            libraries.append('rt')
    """

    try:
        oldstdchannel = os.dup(stdchannel.fileno())
        dest_file = open(dest_filename, 'w')
        os.dup2(dest_file.fileno(), stdchannel.fileno())
        yield

    finally:
        if oldstdchannel is not None:
            os.dup2(oldstdchannel, stdchannel.fileno())
        if dest_file is not None:
            dest_file.close()

def start_slave_collector(node, arg_str):
    if node == constants.WE:
        cmd = r"python {}/main.py __slave".format(os.getcwd())
        for item in arg_str.split():
            cmd += " {}".format(str(item))
        _, out = crmutils.get_stdout(cmd)
        cmd = r"(cd {} && tar xf -)".format(constants.WORKDIR)
        crmutils.get_stdout(cmd, input_s=out)

    else:
        cmd = r'ssh {} {} "{} python {}/main.py __slave"'.\
              format(constants.SSH_OPTS, node, \
                     constants.SUDO, os.getcwd())
        for item in arg_str.split():
            cmd += " {}".format(str(item))
        _, out = crmutils.get_stdout(cmd)
        cmd = r"(cd {} && tar xf -)".format(constants.WORKDIR)
        crmutils.get_stdout(cmd, input_s=out)

def sub_string_test(in_string, pattern=constants.SANITIZE):
    pattern_string = re.sub(" ", "|", pattern)
    for line in in_string.split('\n'):
        if re.search('name="%s"'%pattern_string, line):
            return True
    return False

def sys_info():
    out_string = "#####Cluster info:\n"
    out_string += cluster_info()
    out_string += crmsh_info()
    out_string += ra_build_info()
    out_string += crm_info()
    out_string += booth_info()
    out_string += "\n"
    out_string += "#####Cluster related packages:\n"
    out_string += pkg_versions(constants.PACKAGES)
    if constants.SKIP_LVL == 0:
        out_string += verify_packages(constants.PACKAGES)
    out_string += "\n"
    out_string += "#####System info:\n"
    out_string += "Platform: %s\n" % os.uname()[0]
    out_string += "Kernel release: %s\n" % os.uname()[2]
    out_string += "Architecture: %s\n" % os.uname()[-1]
    if os.uname()[0] == "Linux":
        out_string += "Distribution: %s\n" % distro()

    sys_info_f = os.path.join(constants.WORKDIR, constants.SYSINFO_F)
    crmutils.str2file(out_string, sys_info_f)

def sys_stats():
    out_string = ""
    cmd_list = ["hostname", "uptime", "ps axf", "ps auxw", "top -b -n 1",\
                "ip addr", "netstat -i", "arp -an", "lsscsi", "lspci",\
                "mount", "cat /proc/cpuinfo", "df"]
    for cmd in cmd_list:
        out_string += "##### run \"%s\" on %s\n" % (cmd, constants.WE)
        if cmd != "df":
            out_string += get_command_info(cmd)[1] + '\n'
        else:
            out_string += get_command_info_timeout(cmd) + '\n'

    sys_stats_f = os.path.join(constants.WORKDIR, constants.SYSSTATS_F)
    crmutils.str2file(out_string, sys_stats_f)

def tail(n, indata):
    return indata.split('\n')[n-1:-1]

def test_ssh_conn(addr):
    cmd = r"ssh %s -T -o Batchmode=yes %s true" % (constants.SSH_OPTS, addr)
    code, _ = get_command_info(cmd)
    if code == 0:
        return True
    else:
        return False

def time_status():
    out_string = "Time: "
    out_string += datetime.datetime.now().strftime('%c') + '\n'
    out_string += "ntpdc: "
    out_string += get_command_info("ntpdc -pn")[1] + '\n'

    time_f = os.path.join(constants.WORKDIR, constants.TIME_F)
    crmutils.str2file(out_string, time_f)

def touch_dc():
    if constants.SKIP_LVL == 1:
        return
    node = crmutils.get_dc()
    if node and node == constants.WE:
        with open(os.path.join(constants.WORKDIR, "DC"), 'w') as f:
            pass

def touch_r(src, dst):
    """
    like shell command "touch -r src dst"
    """
    if not os.path.exists(src):
        log_warning("In touch_r function, %s not exists" % src)
        return
    stat_info = os.stat(src)
    os.utime(dst, (stat_info.st_atime, stat_info.st_mtime))

def ts_to_dt(timestamp):
    """
    timestamp convert to datetime; consider local timezone
    """
    dt = crmutils.timestamp_to_datetime(timestamp)
    dt += tz.tzlocal().utcoffset(dt)
    return dt

def verify_deb(packages):
    pass

def verify_packages(packages):
    pkg_mgr = get_pkg_mgr()
    if not pkg_mgr:
        return ""
    if pkg_mgr == "deb":
        return verify_deb(packages)
    if pkg_mgr == "rpm":
        return verify_rpm(packages)
    if pkg_mgr == "pkg_info":
        return verify_pkg_info(packages)
    if pkg_mgr == "pkginfo":
        return verify_pkginfo(packages)

def verify_pkg_info(packages):
    pass

def verify_pkginfo(packages):
    pass

def verify_rpm(packages):
    res = ""
    for pack in packages.split():
        cmd = r"rpm --verify %s|grep -v 'not installed'" % pack
        code, out = crmutils.get_stdout(cmd)
        if code != 0 and out:
            res = "For package %s:\n" % pack
            res += out + "\n"
    return res

def which(prog):
    code, _ = get_command_info("which %s" % prog)
    if code == 0:
        return True
    else:
        return False
