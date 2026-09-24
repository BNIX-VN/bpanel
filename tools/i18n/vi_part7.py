# Vietnamese, part 7: the count sentences.
#
# Every entry here has a {placeholder}, and that is why they arrived late. In
# the source these were two JSX fragments either side of an interpolation -
# '' and ' website(s)' - and neither is a translatable unit: Vietnamese does
# not pluralise with (s) and often puts the number elsewhere in the clause.
# Translating the fragments separately produces text that reads like a machine;
# t() now takes values, so each of these is one sentence again.
#
# "website" and "database" stay as they are: a Vietnamese host says "3 website"
# and "2 database", never "3 trang mạng". The count word (cái, con, chiếc) is
# left out for the same reason - nobody writing a control panel puts one in.

PART7 = {
    # --- counts, plain ---
    "{n} website(s)": "{n} website",
    "{n} result(s)": "{n} kết quả",
    "{n} item(s)": "{n} mục",
    "{n} line(s)": "{n} dòng",
    "{n} application(s)": "{n} ứng dụng",
    "{n} database(s)": "{n} database",
    "{n} domain(s)": "{n} tên miền",
    "{d} domain(s), {b} db(s)": "{d} tên miền, {b} database",
    "{n} failures seen": "đã thấy {n} lần thất bại",
    "{n} site(s) opted in": "{n} website đã bật",
    "{n} service(s) will run.": "{n} service sẽ chạy.",
    "serves the domain.": "phục vụ tên miền này.",
    "{n} thing(s) to fix:": "{n} thứ cần sửa:",
    "{n} thing(s) to fix before importing:": "{n} thứ cần sửa trước khi nhập:",
    "{n} MB RAM free": "còn trống {n} MB RAM",
    "nginx now: {n} MB": "nginx hiện tại: {n} MB",
    "({n} MB free)": "(còn trống {n} MB)",

    # --- users and files ---
    "Deleted user {name}": "Đã xoá tài khoản {name}",
    "Deleted user {name} and {n} website(s)":
        "Đã xoá tài khoản {name} và {n} website",
    "Suspend user {name}? This will block login, disable all {n} website(s), lock SFTP, and kill active sessions.":
        "Tạm ngưng tài khoản {name}? Việc này sẽ chặn đăng nhập, tắt toàn bộ {n} website, khoá SFTP và ngắt các phiên đang hoạt động.",
    "Permissions set to {mode} on {n} item(s).":
        "Đã đặt quyền {mode} cho {n} mục.",
    "Delete {n} selected item(s)?": "Xoá {n} mục đã chọn?",
    "World-writable: anyone with an account on the server can change these files. Use 755 unless something really needs it.":
        "Ai cũng ghi được: bất kỳ ai có tài khoản trên server đều sửa được các file này. Hãy dùng 755 trừ khi thật sự cần.",
    "World-writable: anyone with an account on the server can change what is inside these folders. Use 755 unless something really needs it.":
        "Ai cũng ghi được: bất kỳ ai có tài khoản trên server đều sửa được nội dung trong các thư mục này. Hãy dùng 755 trừ khi thật sự cần.",

    # --- packages and allowances ---
    "Using {used} of {limit} allowed.": "Đang dùng {used} trong {limit} được phép.",
    "This package allows {n} application(s). Delete one to install another.":
        "Gói này cho phép {n} ứng dụng. Hãy xoá một cái để cài cái khác.",
    "You have used all {n} SFTP accounts in your package.":
        "Anh đã dùng hết {n} tài khoản SFTP trong gói của mình.",
    "{used} of {limit} SFTP accounts used.":
        "Đã dùng {used} trong {limit} tài khoản SFTP.",

    # --- applications ---
    "Containers publish on 127.0.0.1 only, run as your own user with no capabilities, and are capped at the memory shown.":
        "Container chỉ mở cổng trên 127.0.0.1, chạy dưới chính user của anh mà không có đặc quyền nào, và bị giới hạn ở mức bộ nhớ hiển thị.",
    "Images come from {list}.": "Image được lấy từ {list}.",
    "the allowed registries": "các registry được phép",

    # --- nginx and cron ---
    "Alias serves the same app. Redirect sends visitors to {domain}.":
        "Alias phục vụ cùng một ứng dụng. Redirect chuyển khách sang {domain}.",
    "and BPanel rewrites it to": "và BPanel sẽ đổi thành",
    " — the PHP {version} CLI this website is set to":
        " — bản PHP {version} CLI mà website này đang đặt",
    ", so the job never runs on the server default version. Change the website's PHP version and its cron jobs follow.":
        ", nên lệnh sẽ không bao giờ chạy bằng phiên bản mặc định của server. Đổi phiên bản PHP của website thì các lệnh cron cũng đổi theo.",

    # --- DirectAdmin import ---
    "{user} - {n} website(s)": "{user} - {n} website",
    "unknown user": "tài khoản không rõ",
    "Select all ({n})": "Chọn tất cả ({n})",
    "Restore selected ({n})": "Khôi phục mục đã chọn ({n})",
    "Delete selected ({n})": "Xoá mục đã chọn ({n})",
    "Unassigned databases ({n})": "Database chưa gán ({n})",

    # --- PHP tuning ---
    "Auto tune will change {n} setting(s) for PHP {version}":
        "Tự động tinh chỉnh sẽ đổi {n} thiết lập của PHP {version}",
    "Disable OPcache (PHP {version})": "Tắt OPcache (PHP {version})",
    "Enable OPcache (PHP {version})": "Bật OPcache (PHP {version})",

    # --- WAF and CRS ---
    "Save and apply to all {n} website(s)": "Lưu và áp dụng cho cả {n} website",
    'Panel setting says "{panel}" but the server reports "{server}".':
        'Cài đặt trong panel là "{panel}" nhưng server báo "{server}".',
    "The WAF blocks known bad paths. OWASP CRS adds payload inspection — SQL injection, XSS, command injection — for this site, at roughly {n} MB of nginx memory.":
        "WAF chặn các đường dẫn xấu đã biết. OWASP CRS thêm phần kiểm tra nội dung request — SQL injection, XSS, command injection — cho website này, tốn khoảng {n} MB bộ nhớ nginx.",
    "This site is opted in, but CRS is switched off server-wide on the WAF page, so nothing is loaded.":
        "Website này đã bật, nhưng CRS đang tắt ở mức toàn server tại trang WAF, nên không có gì được nạp.",
    "Add SecRuleRemoveById <id> to the custom rules below to excuse this site from one CRS rule.":
        "Thêm SecRuleRemoveById <id> vào phần rule tuỳ chỉnh bên dưới để miễn cho website này một rule của CRS.",
    'Each site that loads CRS adds its own copy of the rule set, so the cost grows with the number opted in — roughly {n} MB each. "nginx now" above is measured on this server, not estimated, and it is the figure to act on; watch it and the free-RAM figure beside it as you opt sites in. Note that `ps` reports several times this, because it counts pages the nginx workers share once for each worker.':
        'Mỗi website bật CRS sẽ nạp một bản rule set riêng, nên chi phí tăng theo số website đã bật — khoảng {n} MB mỗi website. Con số "nginx hiện tại" ở trên là đo thật trên server này, không phải ước lượng, và đó mới là số để quyết định; hãy theo dõi nó cùng số RAM còn trống bên cạnh khi bật thêm website. Lưu ý `ps` báo gấp vài lần con số này, vì nó tính các trang bộ nhớ mà các worker nginx dùng chung một lần cho mỗi worker.',

    # --- malware and passkeys ---
    "Level 2 running": "Lớp 2 đang chạy",
    "Level 2 not running": "Lớp 2 không chạy",
    "You are reaching the panel by IP address ({host}). Browsers only create passkeys for domain names, so open the panel by its domain and add one there.":
        "Anh đang vào panel bằng địa chỉ IP ({host}). Trình duyệt chỉ tạo passkey cho tên miền, nên hãy mở panel bằng tên miền rồi thêm passkey ở đó.",
}

# Wrapped later than the rest: its paragraph ended on a different line from the
# tag that closed it, so the wrapper never saw it.
PART7.update({
    "Once you dismiss the token above these go back to saying YOUR_TOKEN, because the panel cannot show it to you a second time.":
        "Khi anh đóng token ở trên thì các đoạn này sẽ trở lại thành YOUR_TOKEN, vì panel không thể hiện lại token cho anh lần thứ hai.",
})
