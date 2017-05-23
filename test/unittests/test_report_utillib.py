import sys
sys.path.append("/usr/share/crmsh")
import os

from nose.tools import eq_, ok_
from hb_report.utillib import which, ts_to_dt, sub_string, random_string,\
                              head, create_tempfile, tail, grep,\
                              get_stamp_rfc5424, get_stamp_syslog
import crmsh.utils

def get_command_info(cmd):
    code, out, err = crmsh.utils.get_stdout_stderr(cmd)
    if out:
        return (code, out)
    else:
        return (code, "")

def test_get_stamp_rfc5424():
    line = r"2017-01-26T11:04:19.562885+08:00 12sp2-4 kernel: [    0.000000]"
    ok_(get_stamp_rfc5424(line))      

def test_get_stamp_syslog():
    line = r"May 17 15:52:40 [13042] 12sp2-4 pacemakerd:   notice: main:"
    ok_(get_stamp_syslog(line))

def test_grep():
    res = grep("^Name", incmd="rpm -qi crmsh")[0]
    _, out = get_command_info("rpm -qi crmsh|grep \"^Name\"")
    eq_(res, out)
    ##################################
    in_string = """aaaa
bbbb
"""
    temp_file = create_tempfile()
    with open(temp_file, 'w') as f:
        f.write(in_string)
    res = grep("aaaa", infile=temp_file, flag='v')[0]
    _, out = get_command_info("grep -v aaaa %s"%temp_file)
    os.remove(temp_file)
    eq_(res, out)

def test_head():
    in_string = """some aaa
some bbbb
some cccc
some dddd
"""
    temp_file = create_tempfile()
    with open(temp_file, 'w') as f:
        f.write(in_string)
    _, out = get_command_info("cat %s|head -3" % temp_file)
    with open(temp_file, 'r') as f:
        data = f.read()
    res = head(3, data)

    os.remove(temp_file)
    eq_(out, '\n'.join(res))

def test_random_string():
    eq_(len(random_string(8)), 8)

def test_sub_string():
    in_string = """
some text some text
I like name="OSS" value="redhat" target="mememe".
I like name="password" value="123456" some="more".
some number some number
"""

    out_string = """
some text some text
I like name="OSS" value="******" target="mememe".
I like name="password" value="******" some="more".
some number some number
"""
    pattern = "passw.* OSS"
    eq_(sub_string(in_string, pattern), out_string)

def test_tail():
    in_string = """some aaa
some bbbb
some cccc
some dddd
"""
    temp_file = create_tempfile()
    with open(temp_file, 'w') as f:
        f.write(in_string)
    _, out = get_command_info("cat %s|tail -3" % temp_file)
    with open(temp_file, 'r') as f:
        data = f.read()
    res = tail(3, data)

    os.remove(temp_file)
    eq_(out, '\n'.join(res))

def test_ts_to_dt():
    ts1 = crmsh.utils.parse_to_timestamp("2pm")
    ts2 = crmsh.utils.parse_to_timestamp("2007/9/5 12:30")
    ts3 = crmsh.utils.parse_to_timestamp("1:00")
    ts4 = crmsh.utils.parse_to_timestamp("09-Sep-15 2:00")
    
    eq_(ts_to_dt(ts1).strftime("%-I%P"), "2pm")
    eq_(ts_to_dt(ts2).strftime("%Y/%-m/%-d %H:%M"), "2007/9/5 12:30")
    eq_(ts_to_dt(ts3).strftime("%-H:%M"), "1:00")
    eq_(ts_to_dt(ts4).strftime("%d-%b-%y %-H:%M"), "09-Sep-15 2:00")

def test_which():
    ok_(which("ls"))
    ok_(not which("llll"))
