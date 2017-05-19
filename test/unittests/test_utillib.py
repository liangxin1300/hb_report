from nose.tools import eq_, ok_
from hbreport.utillib import which, ts_to_dt, sub_string, random_string
import crmsh.utils

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
