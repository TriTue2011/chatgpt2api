"use client";

/**
 * Hướng dẫn dựng ĐIỆN NHÀ (UPS + NUT trên Proxmox) và tài khoản c2a trên router MikroTik — đủ lệnh cho từng phần.
 *
 * Chủ máy 05/10/2026: "hướng dẫn mới phải đầy đủ cho các phần. Readme nữa". Mọi khối lệnh chép NGUYÊN VĂN từ
 * file đang chạy trên Proxmox .100 / router (mật khẩu che). Bản đọc trong repo: docs/DIEN_UPS_VA_MANG_NHA.md —
 * test/test_huong_dan_dien_mang.py giữ hai nơi KHÔNG lệch: mỗi khối ở đây phải có nguyên văn trong file đó.
 *
 * Bẫy template literal: chuỗi «$ {» trong script shell phải viết «\${» (xem memory chen-css-vao-template-literal).
 */

export type Khoi = { tep?: string; ma: string };
export type Phan = { id: string; tieuDe: string; buoc: string[]; khoi: Khoi[] };

export const PHAN_MIKROTIK: Phan = {
  id: "mikrotik",
  tieuDe: "Tạo tài khoản c2a trên router MikroTik",
  buoc: [
    "Mở Winbox → New Terminal, dán từng khối lệnh dưới (đổi MAT_KHAU_MANH, đổi 172.16.10.38 thành IP máy chủ c2a).",
    "Điền ở trên: địa chỉ 172.16.10.1, cổng 8729, tài khoản c2a, mật khẩu vừa đặt → Kiểm tra kết nối → Lưu.",
    "Không dùng tài khoản admin: nhóm c2a không khởi động lại được router, không đổi được quyền, không đọc được mật khẩu/khoá.",
    "Đã có máy khác dùng API-SSL (vd Home Assistant .200) thì ở bước 4 liệt kê cả hai địa chỉ, cách nhau dấu phẩy.",
  ],
  khoi: [{
    ma: `# 1. Nhóm quyền: đọc + ghi + API — KHÔNG reboot, policy, sensitive, winbox, ssh…
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
/ip firewall filter add chain=input action=accept protocol=tcp dst-port=8729 src-address=172.16.10.38 comment="c2a API SSL" place-before=0`,
  }],
};

export const PHAN_DIEN: Phan[] = [
  {
    id: "vi-sao",
    tieuDe: "1. Cài NUT ở đâu",
    buoc: [
      "Cài trên MÁY CẮM CÁP USB CỦA UPS — nhà này là máy Proxmox .100. KHÔNG cài trong LXC.",
      "LXC không chạy udev: sau mỗi lần mất điện cổng USB của UPS về root:root, driver không mở được UPS (lỗi thật 05/10/2026).",
      "Máy Proxmox phải tự đọc được UPS lúc khởi động — khi đó chưa có LXC nào chạy, cũng chưa có mạng (router là máy ảo).",
    ],
    khoi: [],
  },
  {
    id: "cai-nut",
    tieuDe: "2. Cài NUT và khai UPS",
    buoc: [
      "Chạy nut-scanner để biết driver; dán khối nó in ra vào ups.conf và đặt tên [prolink].",
      "ignorelb + override.battery.charge.low = 15: tự báo pin yếu dưới 15%. UPS Prolink chỉ báo pin yếu ở ~8% — đo 05/10/2026 từ 23% tới cạn chỉ ~2 phút, không kịp tắt.",
      "offdelay + POWEROFF_WAIT: lúc tắt máy gửi lệnh ngắt-rồi-cấp-lại nguồn UPS, để máy tự bật kể cả khi điện về trước lúc UPS cạn.",
      "Đổi MAT_KHAU_TU_DAT ở upsd.users và upsmon.conf thành cùng một mật khẩu.",
    ],
    khoi: [
      { ma: `apt install -y nut-server nut-client
nut-scanner -U                     # tìm driver cho UPS cắm USB` },
      { tep: "/etc/nut/nut.conf", ma: `MODE=standalone
# Gửi lệnh ngắt nguồn UPS xong mà 5 phút sau máy vẫn sống (UPS không ngắt, vd điện đã về)
# thì tự khởi động lại — không nằm im ở trạng thái tắt.
POWEROFF_WAIT=300` },
      { tep: "/etc/nut/ups.conf", ma: `maxretry = 3
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
    offdelay = 60` },
      { tep: "/etc/nut/upsd.conf", ma: `# c2a (.38) và Home Assistant đọc UPS qua mạng — chỉ đọc, không cần tài khoản.
LISTEN 0.0.0.0 3493` },
      { tep: "/etc/nut/upsd.users", ma: `[upsmon]
    password = MAT_KHAU_TU_DAT
    upsmon primary` },
      { tep: "/etc/nut/upsmon.conf", ma: `MONITOR prolink@localhost 1 upsmon MAT_KHAU_TU_DAT primary
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
NOTIFYFLAG COMMOK SYSLOG+WALL` },
      { ma: `chown root:nut /etc/nut/*.conf /etc/nut/upsd.users && chmod 640 /etc/nut/*.conf /etc/nut/upsd.users
udevadm trigger --action=add --attr-match=idVendor=0665 --attr-match=idProduct=5161   # cấp quyền USB cho nhóm nut
systemctl restart nut-driver-enumerator nut-driver.target nut-server nut-monitor
upsc prolink@localhost ups.status  # phải ra OL (đang dùng điện lưới)` },
    ],
  },
  {
    id: "tat-khach",
    tieuDe: "3. Mất điện: tắt máy khách tốn điện cho pin kéo dài",
    buoc: [
      "Đo trước máy nào tốn điện: pvesh get /cluster/resources --type vm. Nhà này chỉ VM 108 NVR đáng kể (31% của 8 nhân + card đồ hoạ).",
      "Giữ lại router, AdGuard, Home Assistant, c2a — còn mạng thì còn báo tin.",
      "Mất điện quá 60 giây mới tắt (chớp điện thì thôi); có điện ổn định 5 phút mới bật lại đúng những máy đã tắt.",
    ],
    khoi: [
      { tep: "/etc/nut/upssched.conf", ma: `CMDSCRIPT /usr/local/sbin/ups-may-khach
PIPEFN /run/nut/upssched.pipe
LOCKFN /run/nut/upssched.lock
# Mất điện quá 60 s mới tắt NVR (bỏ qua chớp điện); có điện ổn định 5 phút mới bật lại.
AT ONBATT * START-TIMER tat-nvr 60
AT ONBATT * CANCEL-TIMER bat-lai
AT ONLINE * CANCEL-TIMER tat-nvr
AT ONLINE * START-TIMER bat-lai 300` },
      { tep: "/usr/local/sbin/ups-may-khach", ma: `#!/bin/sh
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
esac` },
      { ma: `chmod 755 /usr/local/sbin/ups-may-khach
systemctl restart nut-monitor` },
    ],
  },
  {
    id: "co-dien",
    tieuDe: "4. Có điện: tự bật lại, chờ điện ổn định",
    buoc: [
      "BIOS (vào tại máy): Restore on AC Power Loss = Power On. Thiếu bước này máy KHÔNG tự bật — kiểm: dmidecode -t 1 | grep Wake-up phải ra «AC Power Restored» sau lần có điện tới.",
      "Có điện lại, máy Proxmox lên nhưng CHƯA bật máy khách nào cho tới khi điện lưới ổn định 5 phút liền; chập chờn thì đếm lại.",
      "NUT hỏng (không đọc được UPS 10 phút) hoặc chờ quá 30 phút thì vẫn bật — không để cả nhà tắt vì bộ chờ.",
    ],
    khoi: [
      { tep: "/usr/local/sbin/cho-dien-on-dinh", ma: `#!/bin/sh
# Chạy TRƯỚC pve-guests: có điện lại thì chưa bật máy khách nào cho tới khi điện lưới ổn định
# ON_DINH giây liền (chủ máy 05/10/2026: nguồn có thể chập chờn). Điện mất giữa chừng thì đếm lại.
ON_DINH=\${ON_DINH:-300}
KHONG_DOC=\${KHONG_DOC:-600}   # không đọc được UPS lâu ngần này thì vẫn bật — NUT hỏng không được giữ cả nhà tắt
TRAN=\${TRAN:-1800}            # chặn trên: trạng thái kẹt cũng không giữ cả nhà tắt quá 30 phút
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
done` },
      { tep: "/etc/systemd/system/cho-dien-on-dinh.service", ma: `[Unit]
Description=Chờ điện lưới ổn định trước khi bật máy khách Proxmox
After=nut-server.service nut-driver.target
Wants=nut-server.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/cho-dien-on-dinh
TimeoutStartSec=infinity` },
      { tep: "/etc/systemd/system/pve-guests.service.d/cho-dien.conf", ma: `[Unit]
Wants=cho-dien-on-dinh.service
After=cho-dien-on-dinh.service` },
      { ma: `chmod 755 /usr/local/sbin/cho-dien-on-dinh
systemctl daemon-reload
ON_DINH=10 /usr/local/sbin/cho-dien-on-dinh   # thử nhanh: ~10 s sau phải in «điện ổn định 10 s»` },
    ],
  },
  {
    id: "thu-tu",
    tieuDe: "5. Thứ tự khởi động: router → AdGuard → máy khác",
    buoc: [
      "Router MikroTik (VM 1000) cấp DHCP cho cả nhà và cho chính máy Proxmox. Bật sau thì các máy khác chờ DHCP rồi bỏ cuộc — 05/10/2026 AdGuard mất IP, cả nhà mất DNS.",
      "Hookscript chờ router / AdGuard TRẢ LỜI THẬT rồi mới cho máy kế tiếp bật (pve-guests chờ hookscript chạy xong).",
      "ĐỪNG đặt IP tĩnh cho máy Proxmox hay AdGuard: router để arp=reply-only + DHCP add-arp, máy không có lease là mất mạng (đã thử, phải lùi). Muốn IP cố định thì đặt lease tĩnh trên router.",
      "Tắt máy theo chiều ngược lại: máy khác trước, AdGuard, router cuối cùng.",
    ],
    khoi: [
      { tep: "/var/lib/vz/snippets/cho-san-sang.sh", ma: `#!/bin/sh
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
exit 0` },
      { ma: `pvesm set local --content backup,iso,vztmpl,snippets     # cho phép lưu hookscript
chmod 755 /var/lib/vz/snippets/cho-san-sang.sh
qm set 1000 --startup order=1 --hookscript local:snippets/cho-san-sang.sh   # router MikroTik
pct set 100 --startup order=2 --hookscript local:snippets/cho-san-sang.sh   # AdGuard
/var/lib/vz/snippets/cho-san-sang.sh 1000 post-start; journalctl -t cho-san-sang -n 2   # thử: «router MikroTik đã trả lời»` },
    ],
  },
  {
    id: "c2a",
    tieuDe: "6. Nối c2a",
    buoc: [
      "Cài đặt → Home Assistant → 🔋 Điện (UPS): điền prolink@172.16.10.100 → Kiểm tra kết nối → Lưu.",
      "Cài đặt → Thông báo: bật dòng «Mất điện / có điện» và chọn kênh nhận (Zalo, Telegram…).",
      "c2a đọc UPS 5 giây một lần và báo: mất điện (chạy pin quá 10 giây), pin yếu sắp tắt máy chủ, có điện lại kèm số phút đã mất.",
      "Tin không gửi được lúc mất mạng thì giữ lại, có mạng gửi bù (tối đa 6 giờ). Không đọc được UPS quá 3 phút thì báo vào «Lỗi & cảnh báo hệ thống».",
    ],
    khoi: [],
  },
  {
    id: "home-assistant",
    tieuDe: "7. Nối Home Assistant (cảm biến UPS)",
    buoc: [
      "Thêm tài khoản chỉ đọc cho HA trên máy Proxmox (không có quyền SET/FSD/lệnh nào).",
      "HA → Cài đặt → Thiết bị & Dịch vụ → Network UPS Tools → ⋮ → Cấu hình lại: máy 172.16.10.100, cổng 3493, tài khoản homeassistant. Để trống tài khoản sẽ lỗi «USERNAME: ERR INVALID-ARGUMENT».",
    ],
    khoi: [
      { ma: `cat >> /etc/nut/upsd.users <<'EOF'

# Home Assistant: chỉ đọc, không có quyền SET/FSD/lệnh nào
[homeassistant]
    password = MAT_KHAU_HA
EOF
systemctl reload nut-server` },
    ],
  },
  {
    id: "kiem-tra",
    tieuDe: "8. Kiểm tra sau khi dựng",
    buoc: [
      "Không rút điện để thử: hết pin thật là tắt cả nhà. Các lệnh dưới kiểm từng mảnh mà không tắt gì.",
    ],
    khoi: [
      { ma: `systemctl is-active nut-driver@prolink nut-server nut-monitor   # cả ba: active
upsc prolink@localhost | grep -E "ups.status|battery.charge|delay|ignorelb"
journalctl -u nut-monitor -n 5         # có dòng «logged into UPS [prolink]»
systemctl show pve-guests -p After | grep -c cho-dien-on-dinh       # 1
grep -E "^(startup|hookscript)" /etc/pve/qemu-server/1000.conf /etc/pve/lxc/100.conf
dmidecode -t 1 | grep Wake-up          # sau lần có điện tới: AC Power Restored` },
    ],
  },
];

export function HuongDan({ phan }: { phan: Phan[] }) {
  return (
    <div className="space-y-2">
      {phan.map((p) => (
        <details key={p.id} className="rounded-md border p-3 text-sm">
          <summary className="cursor-pointer font-medium">{p.tieuDe}</summary>
          <div className="mt-3 space-y-3">
            <ul className="list-disc space-y-1 pl-5 text-xs">
              {p.buoc.map((b) => <li key={b}>{b}</li>)}
            </ul>
            {p.khoi.map((k, i) => (
              <div key={i} className="space-y-1">
                {k.tep ? <p className="font-mono text-xs text-muted-foreground">{k.tep}</p> : null}
                <pre className="overflow-x-auto rounded bg-muted p-3 text-[11px] leading-relaxed">{k.ma}</pre>
              </div>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}
