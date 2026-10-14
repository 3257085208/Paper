#!/usr/bin/env python3
"""Debug the vm_cmd path used by tb_sweep.py."""
import json
import subprocess
import time

KEY = "/root/.ssh/tb_key"
SSH = ["-n", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
       "-o", "LogLevel=ERROR"]


def vm_cmd(ip, cmd, timeout=90):
    try:
        res = subprocess.run(["ssh"] + SSH + ["debian@" + ip, cmd],
                             capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return -999, "", "TIMEOUT"


print("=== 1) burner 启动 ===")
rc, out, err = vm_cmd("10.10.0.21",
                      'pkill -f "python3 /home/debian/burner.py" 2>/dev/null; '
                      'nohup python3 /home/debian/burner.py /tmp/burn_rate.txt 600 >/dev/null 2>&1 & echo on')
print("rc=%s out=%r err=%r" % (rc, out[-120:], err[-200:]))
time.sleep(3)
rc, out, err = vm_cmd("10.10.0.21", "pgrep -af burner.py | head -2; cat /tmp/burn_rate.txt")
print("check rc=%s out=%r" % (rc, out[-200:]))

print("=== 2) 宿主侧 CPU（间隔 2s 两次采样算瞬时）===")
pid = subprocess.run("cat /run/qemu-server/311.pid", shell=True, capture_output=True, text=True).stdout.strip()
def cpu2():
    with open("/proc/%s/stat" % pid) as fh:
        v = fh.read().split()
    return (int(v[13]) + int(v[14])) / (2.0 if False else 1.0)
a = cpu2(); time.sleep(2); b = cpu2()
print("qemu-311 instant cpu%% = %.1f" % (100.0 * (b - a) / (2.0 * 100.0) * 2.0))

print("=== 3) 探针执行（与 sweep 相同构造）===")
cmd = ("python3 /home/debian/probe.py --mode http --host 10.10.0.11 --rate 100 "
       "--duration 5 --tag dbgpy --raw /home/debian/dbgpy_http.raw")
rc, out, err = vm_cmd("10.10.0.20", cmd, timeout=120)
print("rc=%s" % rc)
print("OUT_TAIL=%r" % out[-300:])
print("ERR_TAIL=%r" % err[-300:])
parsed = None
for line in reversed(out.splitlines()):
    if line.strip().startswith("{"):
        parsed = json.loads(line)
        break
print("parsed p99=", (parsed or {}).get("p99_ms"))

print("=== 4) 收尾：杀掉 burner ===")
vm_cmd("10.10.0.21", 'pkill -f "python3 /home/debian/burner.py" 2>/dev/null; true')
print("DONE")
