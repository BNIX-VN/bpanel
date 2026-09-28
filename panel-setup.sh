#!/usr/bin/env bash
# Trình cài trung gian: chọn web server, rồi chạy trình cài chính thức tương ứng.
#
#   Nginx          -> BPanel  https://github.com/BNIX-VN/bpanel
#   OpenLiteSpeed  -> OPanel  https://github.com/bnixvn/opanel
#
# Script chỉ chọn và gọi đúng trình cài; mọi câu hỏi khác (tên miền, cổng, SSL)
# là của trình cài đó, và các biến môi trường của nó (PANEL_URL, ENABLE_SSL,
# SSL_EMAIL...) vẫn dùng được như khi chạy trực tiếp.
#
# Cách dùng (bằng root, trên Ubuntu 24.04 mới):
#   bash <(curl -fsSL https://raw.githubusercontent.com/BNIX-VN/bpanel/refs/heads/main/panel-setup.sh)
#       hỏi chọn web server
#   bash <(curl -fsSL https://raw.githubusercontent.com/BNIX-VN/bpanel/refs/heads/main/panel-setup.sh) nginx
#       cài BPanel, không hỏi
#   bash <(curl -fsSL https://raw.githubusercontent.com/BNIX-VN/bpanel/refs/heads/main/panel-setup.sh) openlitespeed
#       cài OPanel, không hỏi
set -euo pipefail

BPANEL_INSTALLER="https://raw.githubusercontent.com/BNIX-VN/bpanel/refs/heads/main/install.sh"
OPANEL_INSTALLER="https://raw.githubusercontent.com/bnixvn/opanel/main/installer/install.sh"

if [[ $EUID -ne 0 ]]; then
  echo "Hãy chạy script này bằng root." >&2
  exit 1
fi

# Có terminal để hỏi không? Chạy qua "curl | bash" thì stdin là chính script
# này, nên câu hỏi phải đọc từ /dev/tty chứ không phải từ stdin.
has_tty() { { : </dev/tty; } 2>/dev/null; }

choice="${1:-}"
if [[ -z "$choice" ]]; then
  if ! has_tty; then
    echo "Không có terminal để hỏi. Chạy lại kèm lựa chọn: nginx hoặc openlitespeed." >&2
    exit 1
  fi
  echo "Bạn muốn cài web server nào?"
  echo "  1) Nginx          -> BPanel"
  echo "  2) OpenLiteSpeed  -> OPanel"
  while true; do
    printf "Chọn 1 hoặc 2: "
    read -r choice </dev/tty || exit 1
    case "$choice" in 1|2) break ;; esac
    echo "Chỉ nhập 1 hoặc 2."
  done
fi

case "${choice,,}" in
  1|nginx|bpanel)                 name="BPanel (Nginx)";         url="$BPANEL_INSTALLER" ;;
  2|openlitespeed|ols|opanel)     name="OPanel (OpenLiteSpeed)"; url="$OPANEL_INSTALLER" ;;
  *)
    echo "Lựa chọn không hợp lệ: ${choice} (dùng nginx hoặc openlitespeed)." >&2
    exit 1
    ;;
esac

echo "==> Cài ${name}"
echo "==> Trình cài: ${url}"
installer="$(mktemp)"
trap 'rm -f "$installer"' EXIT
curl -fsSL "$url" -o "$installer"

# Trình cài sẽ hỏi tên miền, cổng, SSL: cho nó đọc từ terminal khi có.
if has_tty; then
  bash "$installer" </dev/tty
else
  bash "$installer"
fi
