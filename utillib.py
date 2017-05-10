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

def base_check():
    if not which("which"):
        log_fatal("please install the which(1) program")

def check_env():   
    set_env()
    base_check()
    get_ocf_dir()
    load_ocf_dirs()

def check_time(var, option):
    if not var:
        log_fatal("""bad time specification: %s 
                        try these like: 2pm
                                        1:00
                                        "2007/9/5 12:30"
                                        "09-Sep-07 2:00"
                  """%option)

def create_tempfile(time=None):        
    random_str = random_string(4)  
    try:
        filename = tempfile.mkstemp(suffix=random_str, prefix="tmp.")[1]
    except:
        log_fatal("Can't create file %s" % filename)
    if time:
        os.utime(filename, (time, time))
    return filename

def crmsh_info():
    return get_command_info("crm report -V")[1]

def drop_tempfiles():
    with open(constants.TMPFLIST, 'r') as f:
        for line in f.read().split('\n'):
            if os.path.isdir(line):
                shutil.rmtree(line)
            if os.path.isfile(line):
                os.remove(line)
    os.remove(constants.TMPFLIST)

def get_command_info(cmd):
    code, out, err = crmutils.get_stdout_stderr(cmd)
    if out:
        return (code, out + '\n')  
    else:
        return (code, "")

def get_ocf_dir():
    ocf_dir = None
    try:
        ocf_dir = crmsh.config.path.ocf_root
    except:
        log_fatal("Can not find OCF_ROOT_DIR!")
    if not os.path.isdir(ocf_dir):
        log_fatal("Directory %s is not OCF_ROOT_DIR!" % ocf_dir)
    constants.OCF_DIR = ocf_dir

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

def is_collector():
    if sys.argv[1] == "__slave":
        return True
    return False

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

def log_warning(msg):
    crmmsg.common_warn("%s# %s" % (constants.WE, msg))

def make_temp_dir():          
    dir_path = r"/tmp/.hb_report.workdir.%s" % random_string(6)
    _mkdir(dir_path)          
    return dir_path

def random_string(num):       
    tmp = []
    if crmutils.is_int(num) and num > 0:
        s = string.letters + string.digits
        tmp = random.sample(s, num)
    return ''.join(tmp)

def set_env():
    os.environ["LC_ALL"] = "POSIX"

def which(prog):
    code, _ = get_command_info("which %s" % prog)
    if code == 0:
        return True
    else:
        return False
