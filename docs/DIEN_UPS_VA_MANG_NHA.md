# Điện nhà (UPS + NUT) và tài khoản c2a trên router MikroTik

Tài liệu dựng lại TỪ ĐẦU hai thứ c2a cần ở hạ tầng nhà:

- **Phần A** — tài khoản `c2a` trên router MikroTik, để bot chặn/mở mạng từng máy, giới hạn tốc độ, bật/tắt VPN.
- **Phần B** — UPS + NUT (Network UPS Tools) trên máy Proxmox: báo mất điện, tắt bớt máy khi chạy pin, tắt máy chủ
  khi pin yếu, tự bật lại khi có điện ổn định, đúng thứ tự router → AdGuard → máy khác.

Mọi khối lệnh chép **nguyên văn** từ file đang chạy trên máy Proxmox `.100` và router (mật khẩu che). Cùng các khối
này hiện trong web: *Cài đặt → Home Assistant → 🔋 Điện (UPS)* và *🌐 Mạng nhà*
(`web/src/app/settings/components/huong-dan-dien-mang.tsx`); `test/test_huong_dan_dien_mang.py` giữ hai nơi không lệch.

Vì sao có tài liệu này: **05/10/2026 mất điện 14:28, UPS cạn ~14:48, máy chủ sập cứng, không ai được báo.** NUT có
cài trong một LXC nhưng driver không mở được USB (LXC không có udev) và `upsmon` không có dòng `MONITOR`. Có điện
lại, máy không tự bật (BIOS chưa đặt), và AdGuard mất IP vì bật trước router — cả nhà mất DNS tới khi có người
khởi động lại tay.

Bố cục nhà (đổi theo nhà bạn):

| Máy | Địa chỉ | Vai trò |
|---|---|---|
| Proxmox `pve` | 172.16.10.100 | cắm USB của UPS Prolink PRO1201SFCU; chạy NUT |
| VM 1000 Mikrotik-CHR | 172.16.10.1 | router, DHCP cho cả nhà (kể cả Proxmox) |
| LXC 100 AdGuard | 172.16.10.10 | DNS cả nhà |
| LXC 105 c2a | 172.16.10.38 | bot, đọc UPS và báo tin |
| VM 108 NVR | 172.16.10.220 | camera + GPU — máy tốn điện nhất |

---

## Phần A — Tạo tài khoản c2a trên router MikroTik

- Mở Winbox → New Terminal, dán từng khối lệnh dưới (đổi MAT_KHAU_MANH, đổi 172.16.10.38 thành IP máy chủ c2a).
- Điền ở trên: địa chỉ 172.16.10.1, cổng 8729, tài khoản c2a, mật khẩu vừa đặt → Kiểm tra kết nối → Lưu.
- Không dùng tài khoản admin: nhóm c2a không khởi động lại được router, không đổi được quyền, không đọc được mật khẩu/khoá.
- Đã có máy khác dùng API-SSL (vd Home Assistant .200) thì ở bước 4 liệt kê cả hai địa chỉ, cách nhau dấu phẩy.

("Điền ở trên" = thẻ *Cài đặt → Home Assistant → 🌐 Mạng nhà* của c2a.)

```
# 1. Nhóm quyền: đọc + ghi + API — KHÔNG reboot, policy, sensitive, winbox, ssh…
/user group add name=c2a policy=read,write,api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon,!rest-api

# 2. Tài khoản chỉ đăng nhập được từ máy chủ c2a (nhà này: 172.16.10.38)
/user add name=c2a group=c2a address=172.16.10.38/32 password="MAT_KHAU_MANH"

# 3. Chứng chỉ tự ký cho API-SSL (common-name = IP router)
/certificate add name=c2a-api common-name=172.16.10.1 days-valid=3650 key-usage=digital-signature,key-encipherment,tls-server
/certificate sign c2a-api

# 4. Bật API-SSL (8729), chỉ nhận máy chủ c2a
/ip service set api-ssl certificate=c2a-api address=172.16.10.38/32 disabled=no
/ip service set api disabled=yes          # tắt API không mã hoá (8728)

# 5. Tường lửa: cho c2a vào cổng 8729, đặt lên ĐẦU chuỗi input (trước luật drop)
/ip firewall filter add chain=input action=accept protocol=tcp dst-port=8729 src-address=172.16.10.38 comment="c2a API SSL" place-before=0
```

---

## Phần B — UPS + NUT

### Diễn biến khi mất điện (sau khi dựng đủ B1–B7)

| Lúc | Việc | Ai làm |
|---|---|---|
| UPS chuyển sang pin | ghi nhận | NUT `upsmon` |
| chạy pin ≥ 10 giây | báo «⚡ Mất điện…» | c2a |
| chạy pin ≥ 60 giây | tắt VM 108 NVR cho đỡ hao pin | NUT `upssched` |
| pin < 15% | báo «🪫 Pin còn …% — máy chủ đang tắt», chờ 15 giây, tắt Proxmox (khách tắt trước, router cuối), gửi UPS lệnh ngắt-rồi-cấp-lại nguồn | c2a + NUT |
| có điện lại | UPS cấp lại nguồn → BIOS bật máy → chờ điện ổn định 5 phút → router → AdGuard → máy khác | BIOS + `cho-dien-on-dinh` + hookscript |
| c2a lên lại | báo «🔌 Có điện lại — mất điện từ … (~N phút)» | c2a |
| có điện khi máy chưa tắt | sau 5 phút ổn định, bật lại VM 108 | NUT `upssched` |

Việc TẮT/BẬT do NUT trên chính máy Proxmox lo, c2a chỉ đọc và báo — c2a chết giữa chừng thì máy vẫn tắt đúng.

### B1. Cài NUT ở đâu

- Cài trên MÁY CẮM CÁP USB CỦA UPS — nhà này là máy Proxmox .100. KHÔNG cài trong LXC.
- LXC không chạy udev: sau mỗi lần mất điện cổng USB của UPS về root:root, driver không mở được UPS (lỗi thật 05/10/2026).
- Máy Proxmox phải tự đọc được UPS lúc khởi động — khi đó chưa có LXC nào chạy, cũng chưa có mạng (router là máy ảo).

### B2. Cài NUT và khai UPS

- Chạy nut-scanner để biết driver; dán khối nó in ra vào ups.conf và đặt tên [prolink].
- ignorelb + override.battery.charge.low = 15: tự báo pin yếu dưới 15%. UPS Prolink chỉ báo pin yếu ở ~8% — đo 05/10/2026 từ 23% tới cạn chỉ ~2 phút, không kịp tắt.
- offdelay + POWEROFF_WAIT: lúc tắt máy gửi lệnh ngắt-rồi-cấp-lại nguồn UPS, để máy tự bật kể cả khi điện về trước lúc UPS cạn.
- Đổi MAT_KHAU_TU_DAT ở upsd.users và upsmon.conf thành cùng một mật khẩu.

Lưu ý: % pin của dòng UPS này là NUT **đoán từ điện áp** ắc quy (20,8–26 V). Lúc đang sạc nó báo 100% ngay — đừng
dùng % pin để đoán UPS đã sạc đầy chưa.

```
apt install -y nut-server nut-client
nut-scanner -U                     # tìm driver cho UPS cắm USB
```

`/etc/nut/nut.conf`

```
MODE=standalone
# Gửi lệnh ngắt nguồn UPS xong mà 5 phút sau máy vẫn sống (UPS không ngắt, vd điện đã về)
# thì tự khởi động lại — không nằm im ở trạng thái tắt.
POWEROFF_WAIT=300
```

`/etc/nut/ups.conf`

```
maxretry = 3
pollinterval = 1

[prolink]
    driver = blazer_usb
    subdriver = cypress
    protocol = mustek
    port = auto
    desc = "Prolink PRO1201SFCU"
    vendorid = 0665
    productid = 5161
    # Prolink không tự báo % pin — NUT đoán từ điện áp. Bỏ cờ LB của UPS (bật ở ~8%, quá muộn)
    # và báo pin yếu khi dưới 15%. Đo 05/10/2026: 23% -> cạn trong ~2 phút ở tải 28%.
    ignorelb
    override.battery.charge.low = 15
    # Lệnh ngắt nguồn chạy ở bước CUỐI khi máy đã tắt hết khách: ngắt sau 60 s,
    # cấp lại khi có điện lưới -> máy tự khởi động lại kể cả khi điện về trước lúc UPS cạn.
    offdelay = 60
```

`/etc/nut/upsd.conf`

```
# c2a (.38) và Home Assistant đọc UPS qua mạng — chỉ đọc, không cần tài khoản.
LISTEN 0.0.0.0 3493
```

`/etc/nut/upsd.users`

```
[upsmon]
    password = MAT_KHAU_TU_DAT
    upsmon primary
```

`/etc/nut/upsmon.conf`

```
MONITOR prolink@localhost 1 upsmon MAT_KHAU_TU_DAT primary
MINSUPPLIES 1
# root: upssched cần quyền chạy qm (tắt/bật VM NVR khi mất/có điện).
RUN_AS_USER root
SHUTDOWNCMD "/sbin/shutdown -h +0"
POLLFREQ 5
POLLFREQALERT 5
HOSTSYNC 15
DEADTIME 15
POWERDOWNFLAG /etc/killpower
# Pin yếu -> chờ 15 s rồi mới tắt: c2a đọc UPS mỗi 5 s, cần kịp gửi tin trước khi router tắt.
FINALDELAY 15
NOTIFYCMD /sbin/upssched
NOTIFYFLAG ONBATT SYSLOG+WALL+EXEC
NOTIFYFLAG ONLINE SYSLOG+WALL+EXEC
NOTIFYFLAG LOWBATT SYSLOG+WALL
NOTIFYFLAG FSD SYSLOG+WALL
NOTIFYFLAG SHUTDOWN SYSLOG+WALL
NOTIFYFLAG COMMBAD SYSLOG+WALL
NOTIFYFLAG COMMOK SYSLOG+WALL
```

```
chown root:nut /etc/nut/*.conf /etc/nut/upsd.users && chmod 640 /etc/nut/*.conf /etc/nut/upsd.users
udevadm trigger --action=add --attr-match=idVendor=0665 --attr-match=idProduct=5161   # cấp quyền USB cho nhóm nut
systemctl restart nut-driver-enumerator nut-driver.target nut-server nut-monitor
upsc prolink@localhost ups.status  # phải ra OL (đang dùng điện lưới)
```

### B3. Mất điện: tắt máy khách tốn điện cho pin kéo dài

- Đo trước máy nào tốn điện: pvesh get /cluster/resources --type vm. Nhà này chỉ VM 108 NVR đáng kể (31% của 8 nhân + card đồ hoạ).
- Giữ lại router, AdGuard, Home Assistant, c2a — còn mạng thì còn báo tin.
- Mất điện quá 60 giây mới tắt (chớp điện thì thôi); có điện ổn định 5 phút mới bật lại đúng những máy đã tắt.

`/etc/nut/upssched.conf`

```
CMDSCRIPT /usr/local/sbin/ups-may-khach
PIPEFN /run/nut/upssched.pipe
LOCKFN /run/nut/upssched.lock
# Mất điện quá 60 s mới tắt NVR (bỏ qua chớp điện); có điện ổn định 5 phút mới bật lại.
AT ONBATT * START-TIMER tat-nvr 60
AT ONBATT * CANCEL-TIMER bat-lai
AT ONLINE * CANCEL-TIMER tat-nvr
AT ONLINE * START-TIMER bat-lai 300
```

`/usr/local/sbin/ups-may-khach`

```
#!/bin/sh
# Gọi bởi upssched. Mất điện: tắt máy khách tốn điện (VM 108 NVR — 31% CPU + GPU, đo 05/10/2026)
# cho pin kéo dài. Có điện ổn định: bật lại đúng những máy đã tắt.
TON_DIEN="108"
SO=/var/lib/nut/da-tat
case "$1" in
  tat-nvr)
    for id in $TON_DIEN; do
      if qm status "$id" 2>/dev/null | grep -q running; then
        echo "$id" >> "$SO"
        logger -t ups-may-khach "mất điện — tắt VM $id"
        qm shutdown "$id" --timeout 120 --forceStop 1 &
      fi
    done ;;
  bat-lai)
    [ -f "$SO" ] || exit 0
    for id in $(sort -u "$SO"); do
      logger -t ups-may-khach "có điện ổn định — bật lại VM $id"
      qm start "$id"
    done
    rm -f "$SO" ;;
esac
```

```
chmod 755 /usr/local/sbin/ups-may-khach
systemctl restart nut-monitor
```

### B4. Có điện: tự bật lại, chờ điện ổn định

- BIOS (vào tại máy): Restore on AC Power Loss = Power On. Thiếu bước này máy KHÔNG tự bật — kiểm: dmidecode -t 1 | grep Wake-up phải ra «AC Power Restored» sau lần có điện tới.
- Có điện lại, máy Proxmox lên nhưng CHƯA bật máy khách nào cho tới khi điện lưới ổn định 5 phút liền; chập chờn thì đếm lại.
- NUT hỏng (không đọc được UPS 10 phút) hoặc chờ quá 30 phút thì vẫn bật — không để cả nhà tắt vì bộ chờ.

Ngày 05/10/2026 máy `.100` ghi `Wake-up Type: Power Switch` — tức lần đó có người bấm nút, BIOS **chưa** đặt tự bật.

`/usr/local/sbin/cho-dien-on-dinh`

```
#!/bin/sh
# Chạy TRƯỚC pve-guests: có điện lại thì chưa bật máy khách nào cho tới khi điện lưới ổn định
# ON_DINH giây liền (chủ máy 05/10/2026: nguồn có thể chập chờn). Điện mất giữa chừng thì đếm lại.
ON_DINH=${ON_DINH:-300}
KHONG_DOC=${KHONG_DOC:-600}   # không đọc được UPS lâu ngần này thì vẫn bật — NUT hỏng không được giữ cả nhà tắt
TRAN=${TRAN:-1800}            # chặn trên: trạng thái kẹt cũng không giữ cả nhà tắt quá 30 phút
bd=$(date +%s); tu=""
while :; do
  now=$(date +%s)
  st=$(upsc prolink@localhost ups.status 2>/dev/null)
  case "$st" in
    OL*) [ -n "$tu" ] || { tu=$now; echo "có điện lưới — chờ ổn định $ON_DINH s"; }
         [ $((now - tu)) -ge "$ON_DINH" ] && { echo "điện ổn định $ON_DINH s — bật máy khách"; exit 0; } ;;
    "")  tu=""
         [ $((now - bd)) -ge "$KHONG_DOC" ] && { echo "không đọc được UPS sau $KHONG_DOC s — vẫn bật máy khách"; exit 0; } ;;
    *)   [ -n "$tu" ] && echo "điện chập chờn ($st) — đếm lại"; tu="" ;;
  esac
  [ $((now - bd)) -ge "$TRAN" ] && { echo "đã chờ $TRAN s (UPS: $st) — vẫn bật máy khách"; exit 0; }
  sleep 5
done
```

`/etc/systemd/system/cho-dien-on-dinh.service`

```
[Unit]
Description=Chờ điện lưới ổn định trước khi bật máy khách Proxmox
After=nut-server.service nut-driver.target
Wants=nut-server.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/cho-dien-on-dinh
TimeoutStartSec=infinity
```

`/etc/systemd/system/pve-guests.service.d/cho-dien.conf`

```
[Unit]
Wants=cho-dien-on-dinh.service
After=cho-dien-on-dinh.service
```

```
chmod 755 /usr/local/sbin/cho-dien-on-dinh
systemctl daemon-reload
ON_DINH=10 /usr/local/sbin/cho-dien-on-dinh   # thử nhanh: ~10 s sau phải in «điện ổn định 10 s»
```

### B5. Thứ tự khởi động: router → AdGuard → máy khác

- Router MikroTik (VM 1000) cấp DHCP cho cả nhà và cho chính máy Proxmox. Bật sau thì các máy khác chờ DHCP rồi bỏ cuộc — 05/10/2026 AdGuard mất IP, cả nhà mất DNS.
- Hookscript chờ router / AdGuard TRẢ LỜI THẬT rồi mới cho máy kế tiếp bật (pve-guests chờ hookscript chạy xong).
- ĐỪNG đặt IP tĩnh cho máy Proxmox hay AdGuard: router để arp=reply-only + DHCP add-arp, máy không có lease là mất mạng (đã thử, phải lùi). Muốn IP cố định thì đặt lease tĩnh trên router.
- Tắt máy theo chiều ngược lại: máy khác trước, AdGuard, router cuối cùng.

Vì sao chắc `pve-guests` chờ hookscript: `PVE/API2/Nodes.pm` (startall) chờ tiến trình khởi động từng máy kết thúc
(`while check_process_running … sleep(1)`), và hookscript `post-start` chạy ngay trong tiến trình đó
(`exec_hookscript($conf, $vmid, 'post-start')` ở `QemuServer.pm` / `LXC.pm`). Máy không đặt `order` bật sau mọi
máy có `order`.

`/var/lib/vz/snippets/cho-san-sang.sh`

```
#!/bin/sh
# Hookscript Proxmox: $1 = vmid, $2 = phase. pve-guests chờ bước post-start xong mới bật máy kế tiếp.
# Router MikroTik (1000) cấp DHCP cho cả nhà và cho chính máy chủ; router chỉ cho đi qua máy CÓ lease.
# Đo 05/10/2026: AdGuard bật trước router, dhclient bỏ cuộc sau 80 s -> cả nhà mất DNS tới khi khởi động lại tay.
[ "$2" = post-start ] || exit 0
ghi() { logger -t cho-san-sang "$*"; }

# $1 = số giây tối đa, phần còn lại = lệnh kiểm. Trả 0 khi lệnh kiểm đạt.
cho() {
  het=$(( $(date +%s) + $1 )); shift
  while [ "$(date +%s)" -lt "$het" ]; do
    "$@" >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

lan_xin=0
router_tra_loi() {
  # Máy chủ chưa có IP: dhclient bỏ cuộc rồi ngủ ~7 phút (đo 05/10) -> xin lại, 30 s một lần.
  if ! ip -4 addr show vmbr0 | grep -q "inet " && [ "$(date +%s)" -ge "$lan_xin" ]; then
    lan_xin=$(( $(date +%s) + 30 )); ghi "máy chủ chưa có IP — xin lại DHCP"; ifreload -a
  fi
  ping -c1 -W1 172.16.10.1
}

case "$1" in
  1000)
    if cho 300 router_tra_loi; then ghi "router MikroTik đã trả lời"; sleep 10
    else ghi "router chưa trả lời sau 300 s — vẫn bật tiếp"; fi ;;
  100)
    if cho 180 dig +time=1 +tries=1 @172.16.10.10 . NS; then ghi "AdGuard đã trả lời DNS"
    else ghi "AdGuard chưa trả lời DNS sau 180 s — vẫn bật tiếp"; fi ;;
esac
exit 0
```

```
pvesm set local --content backup,iso,vztmpl,snippets     # cho phép lưu hookscript
chmod 755 /var/lib/vz/snippets/cho-san-sang.sh
qm set 1000 --startup order=1 --hookscript local:snippets/cho-san-sang.sh   # router MikroTik
pct set 100 --startup order=2 --hookscript local:snippets/cho-san-sang.sh   # AdGuard
/var/lib/vz/snippets/cho-san-sang.sh 1000 post-start; journalctl -t cho-san-sang -n 2   # thử: «router MikroTik đã trả lời»
```

### B6. Nối c2a

- Cài đặt → Home Assistant → 🔋 Điện (UPS): điền prolink@172.16.10.100 → Kiểm tra kết nối → Lưu.
- Cài đặt → Thông báo: bật dòng «Mất điện / có điện» và chọn kênh nhận (Zalo, Telegram…).
- c2a đọc UPS 5 giây một lần và báo: mất điện (chạy pin quá 10 giây), pin yếu sắp tắt máy chủ, có điện lại kèm số phút đã mất.
- Tin không gửi được lúc mất mạng thì giữ lại, có mạng gửi bù (tối đa 6 giờ). Không đọc được UPS quá 3 phút thì báo vào «Lỗi & cảnh báo hệ thống».

Mã: `services/dien_nha.py` (đọc `upsd` bằng `LIST VAR`, khoá cấu hình `dien_nha.nut`), sổ trạng thái
`data/agent/dien_nha.json` — giữ qua lần máy chủ khởi động lại, nên tin «có điện lại» tính đúng cả thời gian máy tắt.
Đọc thẳng `upsd` chứ không qua cảm biến HA vì HA chỉ hỏi 60 giây một lần, mà từ 15% tới lúc tắt chỉ chừng một phút.

### B7. Nối Home Assistant (cảm biến UPS)

- Thêm tài khoản chỉ đọc cho HA trên máy Proxmox (không có quyền SET/FSD/lệnh nào).
- HA → Cài đặt → Thiết bị & Dịch vụ → Network UPS Tools → ⋮ → Cấu hình lại: máy 172.16.10.100, cổng 3493, tài khoản homeassistant. Để trống tài khoản sẽ lỗi «USERNAME: ERR INVALID-ARGUMENT».

```
cat >> /etc/nut/upsd.users <<'EOF'

# Home Assistant: chỉ đọc, không có quyền SET/FSD/lệnh nào
[homeassistant]
    password = MAT_KHAU_HA
EOF
systemctl reload nut-server
```

### B8. Kiểm tra sau khi dựng

- Không rút điện để thử: hết pin thật là tắt cả nhà. Các lệnh dưới kiểm từng mảnh mà không tắt gì.

```
systemctl is-active nut-driver@prolink nut-server nut-monitor   # cả ba: active
upsc prolink@localhost | grep -E "ups.status|battery.charge|delay|ignorelb"
journalctl -u nut-monitor -n 5         # có dòng «logged into UPS [prolink]»
systemctl show pve-guests -p After | grep -c cho-dien-on-dinh       # 1
grep -E "^(startup|hookscript)" /etc/pve/qemu-server/1000.conf /etc/pve/lxc/100.conf
dmidecode -t 1 | grep Wake-up          # sau lần có điện tới: AC Power Restored
```

---

## Sự cố thường gặp

| Hiện tượng | Nguyên nhân | Cách chữa |
|---|---|---|
| `blazer_usb: No supported devices found` dù `lsusb` thấy `0665:5161` | file thiết bị USB thuộc `root:root` (thường gặp khi NUT chạy trong LXC — không có udev) | chạy NUT trên máy cắm USB; trên máy thật: `udevadm trigger --action=add --attr-match=idVendor=0665` |
| `upsmon: Fatal error: insufficient power configured!` | `upsmon.conf` thiếu dòng `MONITOR` | thêm dòng `MONITOR` như B2 |
| HA «cannot_connect: USERNAME: ERR INVALID-ARGUMENT» | để trống tài khoản | dùng tài khoản `homeassistant` (B7) |
| Sau khi có điện, cả nhà mất DNS | AdGuard bật trước router, DHCP bỏ cuộc | B5; chữa tạm: `pct reboot 100` |
| Đặt IP tĩnh xong máy mất mạng (ping router không được dù ARP thấy) | router `arp=reply-only` + DHCP `add-arp` — máy không có lease bị chặn | lùi về DHCP, dùng lease tĩnh trên router |
| Có điện mà máy Proxmox nằm im | BIOS chưa đặt Restore on AC Power Loss = Power On | vào BIOS tại máy (B4) |
| c2a báo «Không đọc được UPS» | `nut-server` trên Proxmox dừng, hoặc tường lửa chặn cổng 3493 | `systemctl status nut-server`; thử lại ở tab 🔋 Điện → Kiểm tra kết nối |

## Số đo thật (05/10/2026)

- Tải ~28%: UPS chạy ~20 phút từ lúc mất điện tới cạn.
- % pin tụt dốc ở cuối: 31% → 23% → 8% → 0% trong khoảng 3 phút.
- Proxmox tắt sạch (dừng hết máy khách rồi tắt máy): ~45 giây.
- Không đặt thứ tự khởi động: mỗi LXC mất ~45 giây chờ DHCP, router lên cuối cùng sau ~5 phút.
- `dhclient` của Proxmox khi không thấy router: bỏ cuộc sau ~70 giây rồi ngủ ~7 phút mới thử lại.
