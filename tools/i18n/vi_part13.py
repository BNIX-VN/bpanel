# Vietnamese, part 13: the Notifications addon (2026-09-27) - its page, the
# events a person can choose, the addon's description and its API errors.

PART13 = {
    # The addon card
    "Email needs an SMTP account (host, port, sender address). Mail sent straight from the server usually lands in spam.":
        "Email cần một tài khoản SMTP (máy chủ, cổng, địa chỉ gửi). Thư gửi thẳng từ server thường rơi vào spam.",

    # The events
    "A service stopped or came back": "Dịch vụ bị dừng hoặc chạy lại",
    "nginx, PHP-FPM, MariaDB, Redis or the panel itself, checked every 5 minutes.":
        "nginx, PHP-FPM, MariaDB, Redis hoặc chính panel, kiểm tra mỗi 5 phút.",
    "The disk is nearly full": "Ổ đĩa sắp đầy",
    "Once when usage passes the threshold, again only after it has dropped back.":
        "Báo một lần khi vượt ngưỡng, chỉ báo lại sau khi đã giảm xuống.",
    "The firewall is off": "Tường lửa đang tắt",
    "Switched off, or on but not filtering.": "Bị tắt, hoặc đang bật nhưng không lọc.",
    "A panel update is available": "Có bản cập nhật panel",
    "Once per new version.": "Một lần cho mỗi phiên bản mới.",
    "A scheduled backup failed": "Backup theo lịch bị lỗi",
    "Any schedule on the server, with the error.": "Bất kỳ lịch nào trên server, kèm nội dung lỗi.",
    "Malware found": "Phát hiện mã độc",
    "Any scan on the server that finds something.": "Mọi lần quét trên server tìm thấy file nghi nhiễm.",
    "Certificates about to expire": "Chứng chỉ sắp hết hạn",
    "Every website's certificate, checked once a day.": "Chứng chỉ của mọi website, kiểm tra mỗi ngày một lần.",
    "Sign-in from a new address": "Đăng nhập từ địa chỉ mới",
    "Your account signed in from an IP it has not used before.": "Tài khoản của bạn đăng nhập từ một IP chưa từng dùng.",
    "Password or two-factor changed": "Đổi mật khẩu hoặc đăng nhập hai lớp",
    "So a change you did not make does not go unnoticed.": "Để một thay đổi không phải do bạn làm không bị bỏ sót.",

    # The page
    "My notifications": "Thông báo của tôi",
    "Where the panel reaches you, and about what.": "Panel gửi thông báo cho bạn qua đâu, và về việc gì.",
    "Not set up": "Chưa cấu hình",
    "Not connected": "Chưa kết nối",
    "Sent to {email}, the address on your account.": "Gửi tới {email}, địa chỉ email của tài khoản.",
    "Email is not set up on this server yet.": "Server chưa cấu hình gửi email.",
    "Send me email": "Gửi email cho tôi",
    "Telegram is not set up on this server yet.": "Server chưa cấu hình Telegram.",
    "Send me Telegram messages": "Gửi tin Telegram cho tôi",
    "Send a test": "Gửi thử",
    "Disconnect": "Ngắt kết nối",
    "Open the bot and press Start:": "Mở bot và bấm Start:",
    "Or send the bot this message:": "Hoặc gửi cho bot tin nhắn này:",
    "Then press Check. The code works for {n} minutes.": "Sau đó bấm Kiểm tra. Mã có hiệu lực trong {n} phút.",
    "About your account": "Về tài khoản của bạn",
    "About the server": "Về server",
    "Server channels": "Kênh gửi của server",
    "What every notification on this server goes out through.": "Mọi thông báo trên server này được gửi qua đây.",
    "Email (SMTP)": "Email (máy chủ SMTP)",
    "SMTP server": "Máy chủ SMTP",
    "Encryption": "Mã hoá",
    "Saved - leave empty to keep it": "Đã lưu - để trống để giữ nguyên",
    "Sender address": "Địa chỉ gửi",
    "Sender name": "Tên người gửi",
    "Send me a test email": "Gửi email thử cho tôi",
    "Email settings saved.": "Đã lưu cấu hình email.",
    "Telegram bot": "Bot Telegram",
    "Bot token": "Token của bot",
    "Saved - paste a new one to replace it": "Đã lưu - dán token mới để thay",
    "Telegram bot saved.": "Đã lưu bot Telegram.",
    "Remove the bot": "Gỡ bot",
    "Telegram bot removed.": "Đã gỡ bot Telegram.",
    "When to warn": "Ngưỡng cảnh báo",
    "Disk usage (%)": "Ổ đĩa đã dùng (%)",
    "Certificate expiry (days)": "Chứng chỉ còn hạn (ngày)",
    "Language of the messages": "Ngôn ngữ của thông báo",
    "Saved.": "Đã lưu.",
    "Saving...": "Đang lưu...",
    "Sending...": "Đang gửi...",
    "Loading...": "Đang tải...",
    "Delivery log": "Lịch sử gửi",
    "The last 100 messages sent, and the ones that failed.": "100 thông báo gần nhất đã gửi, và những lần gửi lỗi.",
    "Nothing sent yet.": "Chưa gửi thông báo nào.",
    "Sent": "Đã gửi",
    "Telegram connected.": "Đã kết nối Telegram.",
    "Telegram disconnected.": "Đã ngắt kết nối Telegram.",
    "Test sent to {target}.": "Đã gửi thử tới {target}.",
    "The bot has not received your /start message yet. Send it, then press Check again.":
        "Bot chưa nhận được tin nhắn /start của bạn. Hãy gửi rồi bấm Kiểm tra lại.",

    # API errors a person can meet on this page
    "No Telegram bot is set up on this server yet": "Server chưa cấu hình bot Telegram",
    "Set the SMTP server and sender address first": "Hãy nhập máy chủ SMTP và địa chỉ gửi trước",
    "Your account has no email address": "Tài khoản của bạn chưa có địa chỉ email",
    "Connect your Telegram first": "Hãy kết nối Telegram trước",
    "Set the Telegram bot token first": "Hãy nhập token bot Telegram trước",
    "That does not look like a bot token from @BotFather": "Đây không giống token bot do @BotFather cấp",
    "The sender address is not an email address": "Địa chỉ gửi không phải là địa chỉ email",
    "Open Notifications to set up the SMTP server or a Telegram bot.": "Mở trang Thông báo để cấu hình máy chủ SMTP hoặc bot Telegram.",

    # Telegram: a token and a chat ID
    "Create a bot with @BotFather (/newbot) and paste its token. Then send the bot any message - or add it to a group - press Find chat ID and pick the chat.":
        "Tạo bot bằng @BotFather (/newbot) rồi dán token. Sau đó nhắn cho bot một tin bất kỳ - hoặc thêm bot vào group - bấm Tìm Chat ID và chọn chat.",
    "Find chat ID": "Tìm Chat ID",
    "No messages yet. Send the bot a message first, then press Find chat ID again.":
        "Bot chưa nhận tin nhắn nào. Hãy nhắn cho bot trước, rồi bấm Tìm Chat ID lại.",
    "Server events go to this chat once. An administrator with no chat of their own hears about their account here too.":
        "Các sự kiện của server được gửi vào chat này một lần. Quản trị viên chưa có chat riêng cũng nhận tin về tài khoản của mình tại đây.",
    "You hear in the admin chat ({chat}). Connect a chat of your own to hear there instead.":
        "Bạn đang nhận tin ở chat quản trị ({chat}). Kết nối chat riêng nếu muốn nhận ở đó.",
    "Your chat ID": "Chat ID của bạn",
    "Find my chat ID for me": "Tự tìm Chat ID giúp tôi",
    "A chat ID is a number (negative for a group) or a @channel name":
        "Chat ID là một số (số âm nếu là group) hoặc tên kênh dạng @kenh",
    "Set the bot token and the chat ID first": "Hãy nhập token bot và Chat ID trước",

    # The Settings page: everything the sidebar does not hold
    "Ports, IP rules, blocklists and Fail2ban": "Cổng, luật IP, blocklist và Fail2ban",
    "Request filtering for each website": "Lọc request cho từng website",
    "Requests and blocks": "Request và các lần chặn",
    "Password, two-factor sign-in and passkeys": "Mật khẩu, đăng nhập hai lớp và passkey",
    "Start, stop and restart": "Bật, tắt và khởi động lại",
    "Versions, limits and extensions": "Phiên bản, giới hạn và extension",
    "Hostname, branding and API tokens": "Tên miền panel, thương hiệu và API token",
    "Panel version": "Phiên bản panel",

    # WAF: the server's custom rules, now that they apply
    "Global custom rules": "Rule tuỳ chỉnh toàn cục",
    "{n} rule(s)": "{n} rule",
    "ModSecurity rules for every website with the WAF on. Rules an AI assistant added are marked # bpanel-mcp; delete a rule by deleting its lines.":
        "Rule ModSecurity áp dụng cho mọi website đang bật WAF. Rule do trợ lý AI thêm có dòng # bpanel-mcp; muốn xoá rule nào thì xoá các dòng của rule đó.",
    "Global WAF rules saved. They apply to every website with the WAF on.":
        "Đã lưu rule WAF toàn cục. Rule áp dụng cho mọi website đang bật WAF.",

    # Panel settings in four tabs
    "Panel settings sections": "Các mục cài đặt panel",
    "General": "Chung",
    "Panel name, hostname and the server's addresses.": "Tên panel, tên miền panel và địa chỉ IP của server.",
    "A new password needs the current one, and the authenticator code when two-factor sign-in is on.":
        "Đổi mật khẩu cần nhập mật khẩu hiện tại, và mã xác thực nếu đang bật đăng nhập hai lớp.",

    # Notifications: administrators only
    "Tells administrators what needs their attention on the server, by email and Telegram.":
        "Báo cho quản trị viên những việc cần lưu ý trên server, qua email và Telegram.",
    "The server: a service that stopped, a disk filling up, the firewall off, a failed backup, malware, certificates about to expire, a panel update.":
        "Về server: dịch vụ bị dừng, ổ đĩa sắp đầy, tường lửa tắt, backup lỗi, mã độc, chứng chỉ sắp hết hạn, có bản cập nhật panel.",
    "Your own account: a sign-in from a new place, a password or two-factor change.":
        "Về tài khoản của bạn: đăng nhập từ nơi mới, đổi mật khẩu hoặc đăng nhập hai lớp.",
    "Email goes through the SMTP server you set; Telegram through a bot you create with @BotFather. Each administrator picks their channels and mutes what they do not want.":
        "Email gửi qua máy chủ SMTP bạn cấu hình; Telegram qua bot bạn tạo bằng @BotFather. Mỗi quản trị viên tự chọn kênh và tắt những thông báo không muốn nhận.",
    "For administrators only: customers do not see it and are not sent anything.":
        "Chỉ dành cho quản trị viên: khách hàng không thấy tính năng này và không nhận thông báo nào.",
    "Turning the addon off stops every message and keeps the settings, each administrator's choices and the delivery log.":
        "Tắt addon sẽ dừng mọi thông báo nhưng giữ nguyên cấu hình, lựa chọn của từng quản trị viên và lịch sử gửi.",

    # Restore, DirectAdmin's four steps
    "Where the backups are, what that needs, which users - then restore. The same steps as DirectAdmin.":
        "Chọn nơi chứa backup, điền thông tin nếu cần, chọn người dùng rồi khôi phục - các bước giống DirectAdmin.",
    "This server": "Server này",
    "The panel's backup folder": "Thư mục backup của panel",
    "Another server": "Máy chủ khác",
    "SFTP, FTP or FTPS": "SFTP, FTP hoặc FTPS",
    "Used for this restore only and never saved. To keep a server, add it under Backup Destination.":
        "Chỉ dùng cho lần khôi phục này và không được lưu lại. Muốn giữ máy chủ này, hãy thêm nó ở Đích lưu backup.",
    "Server key": "Khoá của máy chủ",
    "No backups found in this source.": "Không tìm thấy backup nào ở nguồn này.",
    "Select all": "Chọn tất cả",
    "Filter by user...": "Lọc theo người dùng...",
    "{n} selected": "Đã chọn {n}",
    "The user is read from the backup when it is restored": "Tên người dùng sẽ được đọc từ backup khi khôi phục",
    "Exists on this server - will be overwritten": "Đã có trên server này - sẽ bị ghi đè",
    "New on this server": "Chưa có trên server này",
    "Overwrite": "Ghi đè",
    "New": "Mới",
    "Backup to restore": "Bản backup cần khôi phục",
    "Restore {n} user(s)": "Khôi phục {n} người dùng",
    "One user after another, in the background. A user that already exists is overwritten with its backup.":
        "Khôi phục lần lượt từng người dùng và chạy nền. Người dùng đã có sẽ bị ghi đè bằng bản backup.",
    "Restore {n} user(s)? An account that already exists on this server is overwritten with what is in its backup.":
        "Khôi phục {n} người dùng? Tài khoản đã có trên server này sẽ bị ghi đè bằng nội dung trong bản backup.",
    "Starting the restore...": "Đang bắt đầu khôi phục...",
    "Restore started. It keeps running on the server; this page shows each user as it goes.":
        "Đã bắt đầu khôi phục. Tiến trình chạy tiếp trên server; trang này hiện kết quả của từng người dùng.",
    "Restoring: {done} of {total} done": "Đang khôi phục: xong {done}/{total}",
    "Finished: {done} of {total} restored": "Hoàn tất: đã khôi phục {done}/{total}",
    "Waiting": "Đang chờ",
    "Downloading": "Đang tải về",
    "Restoring": "Đang khôi phục",
    "Restored": "Đã khôi phục",
    # what the server can answer
    "Pick a backup destination": "Hãy chọn một đích lưu backup",
    "Enter the server's host name or IP address": "Hãy nhập tên miền hoặc địa chỉ IP của máy chủ",
    "Enter the username": "Hãy nhập tên đăng nhập",
    "Enter the password": "Hãy nhập mật khẩu",
    "The username or folder contains a control character": "Tên đăng nhập hoặc thư mục chứa ký tự điều khiển",
    "The folder path contains a control character": "Đường dẫn thư mục chứa ký tự điều khiển",
    "The server refused the username or password": "Máy chủ từ chối tên đăng nhập hoặc mật khẩu",
    "The server did not open an SFTP session": "Máy chủ không mở phiên SFTP",
    "Not a backup in the panel's backup folder": "Không phải backup trong thư mục backup của panel",
    "That backup destination no longer exists": "Đích lưu backup này không còn nữa",
    "List the server first, so its key can be checked": "Hãy liệt kê máy chủ trước để kiểm tra khoá của nó",
    "Not a backup file": "Không phải file backup",
    "That file is not in the folder that was listed": "File này không nằm trong thư mục đã liệt kê",

    # A backup sent off-server is kept there only
    "With a destination, the backups are kept there only: each one is removed from this server once it has uploaded, and stays here only if the upload fails.":
        "Khi có đích lưu, backup chỉ được giữ ở đó: mỗi bản sẽ bị xoá khỏi server này ngay khi tải lên xong, và chỉ ở lại đây nếu tải lên thất bại.",

    # Restore, laid out by the operator: source, then per source upload + refresh
    "Source": "Nguồn",
    "S3 or SFTP": "S3 hoặc SFTP",
    "Backups on this server": "Backup trên server này",
    "Connection": "Kết nối",
    "Scheduled and manual backups kept on this server, and the ones uploaded here.":
        "Backup theo lịch và backup thủ công đang lưu trên server này, cùng các bản đã tải lên đây.",
    "No backup destination yet. Add one in the Backup Destination tab.":
        "Chưa có đích lưu backup nào. Hãy thêm ở tab Đích lưu backup.",
    "Accounts to restore": "Tài khoản cần khôi phục",
    "Press Refresh in step 2 to list the backups.": "Bấm Tải lại ở bước 2 để liệt kê các bản backup.",
    "Restore {n} account(s)": "Khôi phục {n} tài khoản",
    "Uploading {n} backup(s)...": "Đang tải lên {n} bản backup...",
    "Uploaded {n} backup(s).": "Đã tải lên {n} bản backup.",
    "The source is not valid": "Nguồn không hợp lệ",
    "Nothing to send: the archive is already on this server": "Không cần gửi: bản backup đã nằm trên server này",
    "This is not a full user backup": "Đây không phải bản backup đầy đủ của người dùng",

    # The Malware Scanner addon
    "Scans the websites and the server for malware with Linux Malware Detect and ClamAV.":
        "Quét mã độc cho các website và toàn server bằng Linux Malware Detect và ClamAV.",
    "Scans a website, every website or the whole server on demand, and on a weekly schedule.":
        "Quét một website, mọi website hoặc toàn server khi cần, và theo lịch hằng tuần.",
    "Optional real-time monitoring of the websites (Level 2) and a scan of each uploaded file.":
        "Tuỳ chọn giám sát thời gian thực các website (Lớp 2) và quét từng file được tải lên.",
    "Suspicious files are listed with their signature; nothing is deleted or quarantined without you.":
        "File nghi nhiễm được liệt kê kèm chữ ký; không file nào bị xoá hay cách ly khi bạn chưa đồng ý.",
    "Installing it installs LMD and the ClamAV engine if they are not there yet (1-3 minutes).":
        "Cài addon sẽ cài LMD và ClamAV nếu server chưa có (1-3 phút).",
    "A scan uses about 1.3 GB of memory while it runs and releases it afterwards; nothing stays resident unless Level 2 is on.":
        "Mỗi lần quét dùng khoảng 1,3 GB RAM và trả lại sau khi xong; không có gì chạy thường trực trừ khi bật Lớp 2.",
    "Removing it stops the schedule, the scan of uploads and the real-time monitor, which stays off until you turn Level 2 on again. LMD, ClamAV, the history and the schedule are kept.":
        "Gỡ addon sẽ dừng lịch quét, quét file tải lên và giám sát thời gian thực (Lớp 2 sẽ tắt cho đến khi bạn bật lại). LMD, ClamAV, lịch sử và lịch quét được giữ nguyên.",
    "Open Malware scanner under Settings. If LMD and ClamAV were not installed, they are installing now (1-3 minutes).":
        "Mở Quét mã độc trong Cài đặt. Nếu server chưa có LMD và ClamAV thì chúng đang được cài (1-3 phút).",
    "LMD, ClamAV, the scan history and the schedule settings are all kept.":
        "LMD, ClamAV, lịch sử quét và cấu hình lịch quét đều được giữ nguyên.",
    "Addon off": "Chưa bật addon",
    "Install it on the Addons page": "Cài ở trang Tiện ích",
    "LMD and ClamAV are installing (1-3 minutes). Press Refresh to see when they are ready.":
        "LMD và ClamAV đang được cài (1-3 phút). Bấm Tải lại để xem khi nào xong.",
    "To turn the scanner off, remove the Malware Scanner addon on the Addons page. The history and the settings are kept.":
        "Muốn tắt trình quét, hãy gỡ addon Quét mã độc ở trang Tiện ích. Lịch sử và cấu hình được giữ nguyên.",
    # Installing and removing an addon, in each addon's own words
    "Remove the {name} addon? Anything it runs is stopped; its data stays where it is, and installing it again picks up from there.":
        "Gỡ addon {name}? Những gì addon đang chạy sẽ dừng; dữ liệu vẫn giữ nguyên, cài lại là dùng tiếp được.",
    "Installing {name}...": "Đang cài {name}...",
    "Removing {name}...": "Đang gỡ {name}...",
    "{name} installed.": "Đã cài {name}.",
    "{name} removed.": "Đã gỡ {name}.",
    "The package, the jail configuration and the ban history are all kept.":
        "Gói phần mềm, cấu hình jail và lịch sử chặn đều được giữ nguyên.",
    "Application directories, volumes and panel data are all kept.":
        "Thư mục ứng dụng, volume và dữ liệu panel đều được giữ nguyên.",
    "Open the Application page to install Docker or the Node.js versions you need.":
        "Mở trang Ứng dụng để cài Docker hoặc các phiên bản Node.js bạn cần.",
    "SSH is protected now. Banned addresses are listed on the Firewall page.":
        "SSH đã được bảo vệ. Các địa chỉ bị chặn được liệt kê ở trang Tường lửa.",
    "The {name} addon is not installed on this server.": "Addon {name} chưa được cài trên server này.",
}
