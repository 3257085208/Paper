#!/bin/bash
# One-shot read-only inventory for the HK production host (piped via ssh stdin;
# no PVE API, no remote writes; prints only aggregate numbers, no VM names).
set -u

echo "== uname =="; uname -a
echo "== uptime =="; uptime | tr -s ' '
echo "== loadavg =="; cat /proc/loadavg
echo "== cpu =="
grep -m1 "model name" /proc/cpuinfo
grep -c "^processor" /proc/cpuinfo
lscpu 2>/dev/null | grep -E "^CPU\(s\)|Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)|NUMA node\(s\)|Model name" | sed "s/  */ /g"
echo "== mem =="
grep -E "MemTotal|MemAvailable|SwapTotal|SwapFree" /proc/meminfo
echo "== pve =="
(pveversion 2>/dev/null || dpkg-query -W -f='${Version}\n' pve-manager 2>/dev/null) | head -1
echo "== running_kvm =="
pgrep -cx kvm 2>/dev/null || echo 0
echo "== running_lxc =="
ls /proc/[0-9]*/comm 2>/dev/null | while read c; do cat "$c" 2>/dev/null; done | grep -cx lxc-start 2>/dev/null || echo 0
echo "== conf_counts =="
echo "qemu:$(ls /etc/pve/qemu-server/*.conf 2>/dev/null | wc -l) lxc:$(ls /etc/pve/lxc/*.conf 2>/dev/null | wc -l)"
echo "== qemu_totals =="
awk '
  function conv(sz, u) { if (u=="T") return sz*1024; if (u=="G") return sz; if (u=="M") return sz/1024; return 0 }
  FNR==1 { cores=1; sockets=1; mem=512; disk=0; got=0 }
  /^cores:/ { cores=$2 }
  /^sockets:/ { sockets=$2 }
  /^memory:/ { mem=$2 }
  match($0, /size=[0-9]+[TGM]/) {
    s=substr($0, RSTART+5, RLENGTH-5); u=substr(s, length(s), 1); n=substr(s,1,length(s)-1);
    disk += conv(n, u)
  }
  END {}
  { }
' /dev/null 2>/dev/null
tot_vcpu=0; tot_mem=0; tot_disk=0; n=0; miss_disk=0
for f in /etc/pve/qemu-server/*.conf; do
  [ -e "$f" ] || continue
  n=$((n+1))
  cores=$(grep -m1 "^cores:" "$f" | awk "{print \$2}")
  sockets=$(grep -m1 "^sockets:" "$f" | awk "{print \$2}")
  mem=$(grep -m1 "^memory:" "$f" | awk "{print \$2}")
  cores=${cores:-1}; sockets=${sockets:-1}; mem=${mem:-512}
  tot_vcpu=$((tot_vcpu + cores * sockets))
  tot_mem=$((tot_mem + mem))
  d=$(grep -o "size=[0-9]*[TGM]" "$f" | sed "s/size=//" | awk "{ u=substr(\$1,length(\$1),1); v=substr(\$1,1,length(\$1)-1)+0; if (u==\"T\") g+=v*1024; else if (u==\"G\") g+=v; else if (u==\"M\") g+=v/1024 } END { print g+0 }")
  if [ -z "$d" ] || [ "$d" = "0" ]; then miss_disk=$((miss_disk+1)); else tot_disk=$(awk -v a=$tot_disk -v b=$d "BEGIN{print a+b}"); fi
done
echo "qemu_n=$n tot_vcpu=$tot_vcpu tot_mem_mb=$tot_mem tot_disk_gb=$(printf %.0f $tot_disk) conf_without_disk=$miss_disk"
echo "== vcpu_hist =="
for f in /etc/pve/qemu-server/*.conf; do
  [ -e "$f" ] || continue
  cores=$(grep -m1 "^cores:" "$f" | awk "{print \$2}"); sockets=$(grep -m1 "^sockets:" "$f" | awk "{print \$2}")
  echo $(( ${cores:-1} * ${sockets:-1} ))
done | sort -n | uniq -c | awk "{print \$2\":\"\$1}" | tr "\n" " "; echo
echo "== mem_hist_mb =="
for f in /etc/pve/qemu-server/*.conf; do
  [ -e "$f" ] || continue
  grep -m1 "^memory:" "$f" | awk "{print \$2}"
done | sort -n | uniq -c | awk "{print \$2\":\"\$1}" | tr "\n" " "; echo
echo "== lxc_totals =="
lt=0; lv=0; lm=0
for f in /etc/pve/lxc/*.conf; do
  [ -e "$f" ] || continue
  lt=$((lt+1))
  c=$(grep -m1 "^cores:" "$f" | awk "{print \$2}"); m=$(grep -m1 "^memory:" "$f" | awk "{print \$2}")
  lv=$((lv + ${c:-1})); lm=$((lm + ${m:-512}))
done
echo "lxc_n=$lt lxc_vcpu=$lv lxc_mem_mb=$lm"
echo "== disks =="
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT 2>/dev/null | head -30
echo "== df =="
df -hT / /var/lib/vz /etc/pve 2>/dev/null
echo "== storage_cfg =="
cat /etc/pve/storage.cfg 2>/dev/null | grep -E "^(lvmthin|lvm|dir|zfspool|rbd|nfs|cifs):|^\s+(vgname|thinpool|path|content)" | head -40
