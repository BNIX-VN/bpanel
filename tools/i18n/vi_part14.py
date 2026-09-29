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
    "There is no spam filter in this version.": "Phiên bản này chưa có bộ lọc thư rác.",
    "Removing the addon stops Exim, Dovecot and the webmail and closes the ports. The mail, the mailboxes and the DKIM keys are kept.":
        "Gỡ tiện ích sẽ dừng Exim, Dovecot và webmail, và đóng các cổng. Thư, hộp thư và khoá DKIM được giữ nguyên.",
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
    "This server cannot reach other mail servers on port 25, so mail to outside addresses waits in the queue and comes back after a few days. Most VPS providers open it on request.":
        "Server này không kết nối được tới mail server khác qua cổng 25, nên thư gửi ra ngoài sẽ nằm chờ trong hàng đợi rồi bị trả về sau vài ngày. Đa số nhà cung cấp VPS mở cổng này khi bạn yêu cầu.",

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
}
