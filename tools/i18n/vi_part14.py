# Vietnamese, part 14: the Email addon (2026-09-29) - its card, the Email
# page, the mailbox limit in packages and the API's errors.

PART14 = {
    # The addon card
    "Mailboxes on your domains, with a webmail your customers open from the panel without a password.":
        "Hộp thư trên tên miền của bạn, kèm webmail mà khách hàng mở thẳng từ panel, không cần mật khẩu.",
    "Installs Exim to send and receive, Dovecot for IMAP and POP3, and the BNIX webmail on port 2096.":
        "Cài Exim để gửi và nhận thư, Dovecot cho IMAP và POP3, và BNIX Webmail trên cổng 2096.",
    "Customers make mailboxes on the domains of their own websites, up to the number in their package. Administrators make them on any domain.":
        "Khách hàng tạo hộp thư trên tên miền website của chính mình, trong số lượng gói cho phép. Quản trị viên tạo được trên mọi tên miền.",
    "One click in the panel opens a mailbox in the webmail, with no password to type. Once webmail.<domain> points here, it can have its own address and certificate.":
        "Một cú nhấp trong panel mở hộp thư trên webmail, không cần gõ mật khẩu. Khi webmail.<tên miền> đã trỏ về server này, nó có thể có địa chỉ và chứng chỉ SSL riêng.",
    "Mail is kept in the customer's home directory: it counts toward their disk space and is in their account backups.":
        "Thư được lưu trong thư mục home của khách hàng: tính vào dung lượng của họ và có trong bản sao lưu tài khoản.",
    "Outgoing mail is signed with DKIM. With DNS Manager on, the DKIM, DMARC and webmail records are added to the domain's zone by themselves.":
        "Thư gửi đi được ký DKIM. Khi bật Quản lý DNS, các bản ghi DKIM, DMARC và webmail tự được thêm vào zone của tên miền.",
    "Needs the panel on a domain with a real certificate: mail clients connect to that name.":
        "Cần panel chạy trên tên miền có chứng chỉ SSL thật: ứng dụng email kết nối vào tên đó.",
    "Opens ports 25, 465, 587, 143, 993, 110, 995 and 2096. Many VPS providers block outgoing port 25 until asked; the Email page says whether this server can send.":
        "Mở các cổng 25, 465, 587, 143, 993, 110, 995 và 2096. Nhiều nhà cung cấp VPS chặn cổng 25 chiều đi cho đến khi bạn yêu cầu mở; trang Email cho biết server này có gửi được thư ra ngoài không.",
    "Refuses to install next to another mail server (Postfix, Sendmail). Once installed, websites' PHP mail() is sent through Exim as well.":
        "Không cài khi server đang chạy mail server khác (Postfix, Sendmail). Sau khi cài, hàm mail() của PHP trên các website cũng gửi qua Exim.",
    "Open Email to make the first mailbox. The webmail is on port 2096 of the panel's address.":
        "Mở trang Email để tạo hộp thư đầu tiên. Webmail ở cổng 2096 trên địa chỉ của panel.",
    "The mail, the mailboxes and the DKIM keys are kept, and work again when you install the addon again.":
        "Thư, hộp thư và khoá DKIM được giữ nguyên, và hoạt động lại khi bạn cài lại tiện ích.",

    # The Email page
    "Mailboxes on the domains of your websites. The mail is kept in your account and counts toward its disk space.":
        "Hộp thư trên tên miền các website của bạn. Thư được lưu trong tài khoản và tính vào dung lượng của tài khoản.",
    "Create a website first: mailboxes are made on the domains of your websites.":
        "Hãy tạo website trước: hộp thư được tạo trên tên miền các website của bạn.",
    "Address": "Địa chỉ",
    "Mailbox name": "Tên hộp thư",
    "At least 8 characters": "Ít nhất 8 ký tự",
    "Size (MB, 0 = no limit)": "Dung lượng (MB, 0 = không giới hạn)",
    "Create mailbox": "Tạo hộp thư",
    "Creating mailbox...": "Đang tạo hộp thư...",
    "You have used all {n} mailboxes in your package.": "Bạn đã dùng hết {n} hộp thư trong gói.",
    "{used} of {limit} mailboxes used.": "Đã dùng {used}/{limit} hộp thư.",
    "Mailbox ready": "Hộp thư đã sẵn sàng",
    "Copied.": "Đã sao chép.",
    "No mailboxes yet.": "Chưa có hộp thư nào.",
    "{used} of {size}": "{used} / {size}",
    "{used}, no limit of its own": "{used}, không giới hạn riêng",
    "Mailbox size used": "Dung lượng hộp thư đã dùng",
    "Webmail": "Webmail",
    "Leave empty to keep it": "Để trống nếu giữ nguyên",
    "Saved. The new password works from now on.": "Đã lưu. Mật khẩu mới có hiệu lực ngay.",
    "Delete {address} and all the mail in it? This cannot be undone.":
        "Xoá {address} và toàn bộ thư trong đó? Không thể hoàn tác.",
    "Opening webmail...": "Đang mở webmail...",
    "webmail.{domain} has to point to this server first. Get a certificate for it now?":
        "webmail.{domain} phải trỏ về server này trước. Cấp chứng chỉ SSL cho nó ngay bây giờ?",
    "Getting a certificate...": "Đang cấp chứng chỉ SSL...",
    "The webmail is ready at {url}": "Webmail đã sẵn sàng tại {url}",
    "Stop serving the webmail on webmail.{domain}?": "Ngừng phục vụ webmail tại webmail.{domain}?",
    "The mail server has every mailbox: {n}.": "Mail server đã nhận đủ các hộp thư: {n}.",
    "Mail domains": "Tên miền email",
    "This server serves these records itself for the domains in DNS. For a domain whose DNS is elsewhere, add them there.":
        "Với các tên miền có trong trang DNS, server này tự phục vụ các bản ghi này. Tên miền dùng DNS ở nơi khác thì hãy thêm chúng ở đó.",
    "Add these records where each domain's DNS is managed, so mail reaches this server and is not taken for spam.":
        "Hãy thêm các bản ghi này ở nơi quản lý DNS của từng tên miền, để thư về đúng server này và không bị coi là thư rác.",
    "{n} mailboxes": "{n} hộp thư",
    "Set up webmail.{domain}": "Bật webmail.{domain}",
    "DNS records for mail": "Bản ghi DNS cho email",
    "Mail app settings": "Cấu hình ứng dụng email",
    "For Outlook, Thunderbird or a phone. The user name is the full email address, and the password is the mailbox's.":
        "Dùng cho Outlook, Thunderbird hoặc điện thoại. Tên đăng nhập là địa chỉ email đầy đủ, mật khẩu là mật khẩu của hộp thư.",
    "Incoming mail (IMAP)": "Thư đến (IMAP)",
    "Incoming mail (POP3)": "Thư đến (POP3)",
    "Outgoing mail (SMTP)": "Thư đi (SMTP)",
    "or": "hoặc",
    "Mail server": "Mail server",
    "Mail server name: {name}": "Tên mail server: {name}",
    "Sync mailboxes now": "Đồng bộ hộp thư ngay",
    "{name} is running": "{name} đang chạy",
    "{name} is not running": "{name} không chạy",
    "Mail ports open": "Cổng email đang mở",
    "Mail ports closed": "Cổng email đang đóng",
    "Can send to other mail servers": "Gửi được thư ra ngoài",
    "Outgoing port 25 is blocked": "Cổng 25 chiều đi bị chặn",

    # Packages and users
    "Mailboxes": "Hộp thư",

    # The API's errors
    "The Email addon is not installed.": "Tiện ích Email chưa được cài.",
    "The mail server needs a name. Give the panel a domain first, in Settings.":
        "Mail server cần có tên. Hãy đặt tên miền cho panel trước, trong Cài đặt.",
    "The mailbox name may use letters, digits, dots, hyphens and underscores, such as info or sales.":
        "Tên hộp thư chỉ gồm chữ, số, dấu chấm, gạch ngang và gạch dưới, ví dụ info hoặc sales.",
    "The password cannot contain control characters.": "Mật khẩu không được chứa ký tự điều khiển.",
    "The password needs 8 to 128 characters.": "Mật khẩu cần từ 8 đến 128 ký tự.",
    "The mailbox size is a number of MB; 0 means no limit of its own.":
        "Dung lượng hộp thư tính bằng MB; 0 là không giới hạn riêng.",
    "Mailboxes can only be made on the domains of your own websites.":
        "Chỉ tạo được hộp thư trên tên miền các website của bạn.",
    "That domain's website has no owner.": "Website của tên miền này không có chủ sở hữu.",
    "All the mailboxes in your hosting package are in use.": "Bạn đã dùng hết số hộp thư trong gói hosting.",
    "That address already exists.": "Địa chỉ này đã tồn tại.",
    "There is no such mailbox.": "Không có hộp thư này.",
    "There is no such mail domain.": "Không có tên miền email này.",
    "Make a mailbox on this domain first.": "Hãy tạo một hộp thư trên tên miền này trước.",
    "That webmail address is already a website on this server.": "Địa chỉ webmail này đã là một website trên server.",
    "Could not set up the webmail address.": "Không thiết lập được địa chỉ webmail.",
    "The mail server did not accept the change.": "Mail server không nhận thay đổi này.",
    "The mail server gave an answer the panel could not read.": "Mail server trả về dữ liệu panel không đọc được.",
    "The webmail is not set up on this server. Reinstall the Email addon.":
        "Webmail chưa được cài trên server này. Hãy cài lại tiện ích Email.",

    # Spam filter, smarthost and the DNS template (2026-09-29, second round)
    "Rspamd filters incoming mail: clear spam is refused, likely spam goes to the Junk folder. The filtering log shows every decision and its reasons, and a sender blocked by mistake goes on the allowlist in one click.":
        "Rspamd lọc thư đến: thư rác rõ ràng bị từ chối, thư nghi rác vào thư mục Junk. Nhật ký lọc thư cho thấy mọi quyết định kèm lý do, và người gửi bị chặn nhầm được đưa vào danh sách cho phép chỉ với một cú nhấp.",
    "Outgoing mail can go through a smarthost (SMTP2GO, Mailgun, SendGrid...) when the provider blocks port 25; its SPF include is added to every domain's SPF.":
        "Thư gửi đi có thể đi qua smarthost (SMTP2GO, Mailgun, SendGrid...) khi nhà cung cấp chặn cổng 25; phần include SPF của smarthost được thêm vào SPF của mọi tên miền.",
    "Rspamd uses about 250 MB of memory while the spam filter is on, and keeps its log in the server's Redis.":
        "Rspamd dùng khoảng 250 MB RAM khi bật lọc thư rác, và lưu nhật ký trong Redis của server.",
    "Removing the addon stops Exim, Dovecot, Rspamd and the webmail and closes the ports. The mail, the mailboxes, the DKIM keys and the settings are kept.":
        "Gỡ tiện ích sẽ dừng Exim, Dovecot, Rspamd và webmail, và đóng các cổng. Thư, hộp thư, khoá DKIM và các cài đặt được giữ nguyên.",
    "This server cannot reach other mail servers on port 25, so mail to outside addresses waits in the queue and comes back after a few days. Ask the provider to open it, or send through a smarthost below.":
        "Server này không kết nối được tới mail server khác qua cổng 25, nên thư gửi ra ngoài sẽ nằm chờ trong hàng đợi rồi bị trả về sau vài ngày. Hãy nhờ nhà cung cấp mở cổng, hoặc gửi qua smarthost bên dưới.",
    "Spam filter on": "Đang lọc thư rác",
    "Spam filter off": "Tắt lọc thư rác",
    "Smarthost: {host}": "Smarthost: {host}",

    # The filtering log
    "Spam filter log": "Nhật ký lọc thư",
    "What the spam filter decided about mail from outside, newest first, and why. Look here when someone says their message never arrived.":
        "Bộ lọc đã xử lý thư từ bên ngoài ra sao, mới nhất trước, kèm lý do. Hãy xem ở đây khi có người báo thư của họ không tới.",
    "Show": "Hiển thị",
    "Sent to Junk": "Vào Junk",
    "All mail": "Tất cả thư",
    "Deferred": "Hoãn nhận",
    "Delivered": "Đã nhận",
    "The spam filter is off: mail from outside is delivered unscanned.":
        "Bộ lọc thư rác đang tắt: thư từ bên ngoài được nhận mà không quét.",
    "Nothing in the log for this view yet.": "Chưa có gì trong nhật ký ở mục này.",
    "(no subject)": "(không có tiêu đề)",
    "Score, and the score at which mail is refused": "Điểm, và mức điểm bị từ chối",
    "From": "Người gửi",
    "To": "Người nhận",
    "Sending server": "Server gửi",
    "Why": "Lý do",
    "No rule scored this message.": "Không có quy tắc nào chấm điểm thư này.",
    "This sender is on the allowlist.": "Người gửi này nằm trong danh sách cho phép.",
    "Allow {sender}": "Cho phép {sender}",
    "Allow everyone at {domain}": "Cho phép mọi địa chỉ ở {domain}",
    "Never block mail from {sender}?": "Không bao giờ chặn thư từ {sender}?",
    "{sender} is on the allowlist. Ask the sender to send the message again.":
        "{sender} đã vào danh sách cho phép. Hãy nhờ người gửi gửi lại thư.",

    # The spam filter's settings
    "Spam filter": "Lọc thư rác",
    "Rspamd scores each message from outside. Above the Junk score it goes to the Junk folder; above the reject score it is refused and the sender is told. Mail sent from mailboxes here is not scanned.":
        "Rspamd chấm điểm từng thư từ bên ngoài. Vượt ngưỡng Junk thì thư vào thư mục Junk; vượt ngưỡng từ chối thì thư bị từ chối và người gửi được báo lại. Thư gửi đi từ các hộp thư trên server không bị quét.",
    "Filter mail from outside": "Lọc thư từ bên ngoài",
    "Junk score": "Ngưỡng Junk",
    "Reject score": "Ngưỡng từ chối",
    "Allowlist": "Danh sách cho phép",
    "Save spam filter": "Lưu bộ lọc thư rác",
    "One email address or domain per line. Mail from them is never blocked or sent to Junk. Higher scores block less; Rspamd uses 6 and 15.":
        "Mỗi dòng một địa chỉ email hoặc một tên miền. Thư từ các địa chỉ này không bao giờ bị chặn hay đưa vào Junk. Ngưỡng càng cao thì chặn càng ít; mặc định của Rspamd là 6 và 15.",
    "Spam filter saved.": "Đã lưu bộ lọc thư rác.",
    "Spam filter turned off. Mail from outside is delivered unscanned.":
        "Đã tắt lọc thư rác. Thư từ bên ngoài được nhận mà không quét.",

    # The smarthost
    "Smarthost": "Smarthost",
    "Send outgoing mail through another mail service - SMTP2GO, Mailgun, SendGrid, Amazon SES... - when the provider blocks port 25 on this server, or for better delivery.":
        "Gửi thư đi qua một dịch vụ email khác (SMTP2GO, Mailgun, SendGrid, Amazon SES...) khi nhà cung cấp chặn cổng 25 trên server này, hoặc để thư tới hộp thư đến tốt hơn.",
    "Send outgoing mail through a smarthost": "Gửi thư đi qua smarthost",
    "User name": "Tên đăng nhập",
    "Saved - leave empty to keep it": "Đã lưu, để trống nếu giữ nguyên",
    "SPF of the smarthost": "SPF của smarthost",
    "Save smarthost": "Lưu smarthost",
    "The SPF record for every domain here:": "Bản ghi SPF cho mọi tên miền trên server:",
    "Zones still using the previous SPF record follow it by themselves.":
        "Các zone còn dùng bản ghi SPF cũ sẽ tự được cập nhật theo.",
    "Update it wherever each domain's DNS is managed.": "Hãy cập nhật ở nơi quản lý DNS của từng tên miền.",
    "Send a test message to": "Gửi thư thử tới",
    "Send a test message": "Gửi thư thử",
    "Sending a test message...": "Đang gửi thư thử...",
    "Exim logged nothing more about it.": "Exim không ghi thêm gì về thư này.",
    "Saved. The SPF record is now {spf}.": "Đã lưu. Bản ghi SPF bây giờ là {spf}.",
    "Saved. The SPF record is now {spf}, and {n} zones were updated to it.":
        "Đã lưu. Bản ghi SPF bây giờ là {spf}, và {n} zone đã được cập nhật theo.",

    # The DNS template
    "Records for new zones": "Bản ghi mẫu cho zone mới",
    "One record per line: name, type, then the value; an MX value starts with its priority. {ip} is the address for new zones, {domain} the zone, and {spf} the SPF record:":
        "Mỗi dòng một bản ghi: tên, loại, rồi giá trị; giá trị MX bắt đầu bằng độ ưu tiên. {ip} là địa chỉ cho zone mới, {domain} là tên zone, {spf} là bản ghi SPF:",
    "Zones that already exist are not changed.": "Các zone đã có không bị thay đổi.",
    "Line {n}: {reason}": "Dòng {n}: {reason}",

    # The API's errors
    "Each allowlist line is an email address or a domain, such as friend@example.com or example.com.":
        "Mỗi dòng trong danh sách cho phép là một địa chỉ email hoặc một tên miền, ví dụ friend@example.com hoặc example.com.",
    "The allowlist is limited to 5000 lines.": "Danh sách cho phép tối đa 5000 dòng.",
    "The Junk score must be above 0 and below the reject score, which is at most 100.":
        "Ngưỡng Junk phải lớn hơn 0 và nhỏ hơn ngưỡng từ chối; ngưỡng từ chối tối đa là 100.",
    "The SPF part is one or more mechanisms such as include:spf.smtp2go.com or ip4:192.0.2.1.":
        "Phần SPF gồm một hoặc nhiều cơ chế, ví dụ include:spf.smtp2go.com hoặc ip4:192.0.2.1.",
    "Give the smarthost by name, such as smtp.example.com: its certificate is checked against it.":
        "Hãy nhập smarthost bằng tên, ví dụ smtp.example.com: chứng chỉ SSL của nó được kiểm tra theo tên này.",
    "Choose STARTTLS or SSL for the smarthost.": "Hãy chọn STARTTLS hoặc SSL cho smarthost.",
    "The smarthost port is a number from 1 to 65535.": "Cổng smarthost là một số từ 1 đến 65535.",
    "Enter the smarthost's user name and password. Neither can start or end with a space.":
        "Hãy nhập tên đăng nhập và mật khẩu smarthost. Cả hai không được bắt đầu hoặc kết thúc bằng dấu cách.",
    "Enter the address to send the test message to.": "Hãy nhập địa chỉ nhận thư thử.",
    "The test message could not be sent.": "Không gửi được thư thử.",
    "The spam filter is not set up on this server. Reinstall the Email addon.":
        "Bộ lọc thư rác chưa được cài trên server này. Hãy cài lại tiện ích Email.",
    "The spam filter is not answering. Check that Rspamd is running.":
        "Bộ lọc thư rác không trả lời. Hãy kiểm tra Rspamd có đang chạy không.",
    "Each line is a name, a type and a value, such as www A {ip}.":
        "Mỗi dòng gồm tên, loại và giá trị, ví dụ www A {ip}.",
    "The template can hold at most 100 records.": "Mẫu chứa tối đa 100 bản ghi.",
}
