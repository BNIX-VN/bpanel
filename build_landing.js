const fs = require('fs');
const s = [];

function html(strings) { return strings.join(''); }

// ── HEAD ──
s.push(html`<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BPanel — Hosting Panel for Ubuntu 24.04</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Be+Vietnam+Pro:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
:root{
  --blue:#0b5fbd;--blue-h:#08498f;--blue-glow:rgba(11,95,189,0.15);
  --yellow:#f6c431;--yellow-dim:rgba(246,196,49,0.12);
  --bg:#030d1a;--surface:#071428;--surface2:#0a1f38;
  --border:#1a3560;--border-b:#243d6a;
  --text:#e8eef8;--muted:#6b8cba;--mono:#a8c4e8;
  --green:#4ade80;--radius:14px;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth;scrollbar-width:thin;scrollbar-color:var(--blue) var(--bg)}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--blue);border-radius:3px}
body{font-family:"Be Vietnam Pro","DM Mono",sans-serif;background:var(--bg);color:var(--text);line-height:1.7;overflow-x:hidden;font-size:16px}
h1,h2,h3,h4{font-family:"Syne","Be Vietnam Pro",sans-serif;line-height:1.1}
a{color:inherit;text-decoration:none}
img,svg{display:block;max-width:100%}
.container{width:min(1240px,92vw);margin:0 auto;padding:0 1.5rem}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}

/* ── NAV ── */
nav{position:fixed;top:0;left:0;right:0;z-index:100;padding:.9rem 0;
  backdrop-filter:blur(20px) saturate(180%);
  background:rgba(3,13,26,.82);
  border-bottom:1px solid rgba(26,53,96,.4);
  transition:border-color .3s}
nav.scrolled{border-bottom-color:rgba(11,95,189,.3)}
.nav-inner{display:flex;align-items:center;justify-content:space-between;gap:1.5rem}
.logo{display:flex;align-items:center;gap:.75rem;flex-shrink:0}
.logo-mark{width:36px;height:36px;background:var(--blue);border-radius:8px;position:relative;overflow:hidden;flex-shrink:0}
.logo-mark::after{content:"";position:absolute;bottom:0;left:0;right:0;height:9px;background:var(--yellow);border-radius:0 0 8px 8px}
.logo-mark::before{content:"B";position:relative;z-index:1;display:grid;place-items:center;height:27px;font-family:"Syne",sans-serif;font-weight:800;font-size:1.05rem;color:#fff}
.logo-name{font-family:"Syne",sans-serif;font-weight:700;font-size:1.25rem;color:var(--text);letter-spacing:-.02em}
.nav-links{display:flex;align-items:center;gap:2.25rem;list-style:none}
.nav-links a{color:var(--muted);font-size:.82rem;letter-spacing:.04em;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{display:flex;align-items:center;gap:.75rem}
.btn{display:inline-flex;align-items:center;gap:.5rem;padding:.65rem 1.4rem;border-radius:9px;
  font-family:"JetBrains Mono","DM Mono",monospace;font-size:.82rem;font-weight:500;
  transition:all .2s;cursor:pointer;border:none;text-decoration:none;white-space:nowrap}
.btn-primary{background:var(--blue);color:#fff}
.btn-primary:hover{background:var(--blue-h);transform:translateY(-1px);box-shadow:0 10px 30px rgba(11,95,189,.35)}
.btn-ghost{border:1px solid var(--border-b);color:var(--text);background:transparent}
.btn-ghost:hover{border-color:var(--blue);color:var(--blue);background:var(--blue-glow)}
.btn-sm{padding:.5rem 1rem;font-size:.78rem}

/* ── HERO ── */
.hero{min-height:100vh;display:flex;align-items:center;position:relative;padding:7rem 0 5rem;overflow:hidden}
.hero-bg{position:absolute;inset:0;pointer-events:none}
.hero-grid{position:absolute;inset:0;
  background-image:linear-gradient(rgba(11,95,189,.06) 1px,transparent 1px),
                    linear-gradient(90deg,rgba(11,95,189,.06) 1px,transparent 1px);
  background-size:60px 60px;
  mask-image:radial-gradient(ellipse 90% 80% at 50% 30%,#000 30%,transparent 100%)}
.hero-orb{position:absolute;top:-300px;left:50%;transform:translateX(-50%);
  width:1000px;height:700px;
  background:radial-gradient(ellipse at center,rgba(11,95,189,.18) 0%,rgba(11,95,189,.05) 40%,transparent 70%);
  pointer-events:none;animation:orbPulse 8s ease-in-out infinite}
.hero-orb2{position:absolute;bottom:-100px;right:-100px;
  width:500px;height:500px;
  background:radial-gradient(ellipse at center,rgba(246,196,49,.06) 0%,transparent 70%);
  pointer-events:none;animation:orbPulse 12s ease-in-out infinite reverse}
.hero-content{position:relative;z-index:1}
.hero-badge{display:inline-flex;align-items:center;gap:.6rem;
  padding:.35rem 1.1rem;border:1px solid var(--border-b);
  border-radius:100px;background:rgba(11,95,189,.08);
  color:var(--yellow);font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;
  margin-bottom:2rem;animation:fadeUp .6s ease both}
.pulse-dot{width:7px;height:7px;background:var(--yellow);border-radius:50%;animation:pulse 2s ease-in-out infinite}
.hero-title{font-size:clamp(2.8rem,7vw,5.2rem);font-weight:800;
  letter-spacing:-.03em;margin-bottom:1.5rem;line-height:1.06;animation:fadeUp .6s .1s ease both}
.hero-title .blue{color:var(--blue)}
.hero-title .yellow{color:var(--yellow)}
.hero-sub{max-width:560px;font-size:1.05rem;color:var(--muted);margin-bottom:2.5rem;line-height:1.85;animation:fadeUp .6s .2s ease both}
.hero-actions{display:flex;gap:.9rem;flex-wrap:wrap;animation:fadeUp .6s .3s ease both}
.hero-terminal{margin-top:2.75rem;background:var(--surface);border:1px solid var(--border);border-radius:12px;
  overflow:hidden;max-width:530px;animation:fadeUp .6s .4s ease both}
.t-header{display:flex;align-items:center;gap:.5rem;padding:.8rem 1.1rem;background:var(--surface2);border-bottom:1px solid var(--border)}
.dot{width:12px;height:12px;border-radius:50%}
.dot-r{background:#ff5f57}
.dot-y{background:#febc2e}
.dot-g{background:#28c840}
.t-title{flex:1;text-align:center;font-size:.68rem;color:var(--muted);letter-spacing:.06em}
.t-body{padding:1.3rem 1.6rem;font-size:.84rem;line-height:2}
.prompt{color:var(--yellow);user-select:none}
.cmd{color:var(--mono)}
.comment{color:var(--muted);font-style:italic}
.output{color:var(--green)}
.cursor{animation:blink 1s step-end infinite}
.hero-stats{display:flex;gap:3rem;margin-top:3rem;flex-wrap:wrap;animation:fadeUp .6s .5s ease both}
.stat{}
.stat-n{font-family:"Syne",sans-serif;font-size:2rem;font-weight:800;color:var(--blue);line-height:1}
.stat-l{font-size:.72rem;color:var(--muted);margin-top:.25rem;letter-spacing:.07em;text-transform:uppercase}

/* ── SECTION ── */
.section{padding:6rem 0}
.section-label{font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--yellow);
  margin-bottom:.75rem;display:flex;align-items:center;gap:.5rem}
.section-label::before{content:"";display:block;width:24px;height:1px;background:var(--yellow)}
.section-title{font-size:clamp(1.75rem,4vw,2.6rem);font-weight:700;letter-spacing:-.02em;margin-bottom:1rem}
.section-sub{color:var(--muted);max-width:520px;font-size:.93rem;line-height:1.85;margin-bottom:3rem}

/* ── FEATURES ── */
.features-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1.1rem}
.feature-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:1.6rem;transition:all .25s;position:relative;overflow:hidden}
.feature-card::before{content:"";position:absolute;inset:0;
  background:linear-gradient(135deg,rgba(11,95,189,.05) 0%,transparent 55%);opacity:0;transition:opacity .25s}
.feature-card:hover{border-color:var(--blue);transform:translateY(-3px);box-shadow:0 16px 48px rgba(11,95,189,.14)}
.feature-card:hover::before{opacity:1}
.feat-icon{width:44px;height:44px;background:rgba(11,95,189,.1);border-radius:10px;
  display:grid;place-items:center;margin-bottom:1.2rem;font-size:1.3rem;transition:background .25s}
.feature-card:hover .feat-icon{background:rgba(11,95,189,.18)}
.feat-name{font-family:"Syne",sans-serif;font-size:.98rem;font-weight:700;margin-bottom:.45rem;color:var(--text)}
.feat-desc{font-size:.8rem;color:var(--muted);line-height:1.72}

/* ── WHY ── */
.why{background:var(--surface);border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.why-grid{display:grid;grid-template-columns:1fr 1fr;gap:5rem;align-items:center;padding:5rem 0}
.why-list{list-style:none;display:flex;flex-direction:column;gap:1rem}
.why-item{display:flex;align-items:flex-start;gap:1rem;
  padding:1.1rem 1.3rem;background:var(--bg);border:1px solid var(--border);
  border-radius:11px;transition:all .2s}
.why-item:hover{border-color:var(--blue);background:rgba(11,95,189,.04)}
.why-check{width:24px;height:24px;background:rgba(11,95,189,.12);border-radius:50%;
  display:grid;place-items:center;flex-shrink:0;color:var(--blue);font-size:.65rem;font-weight:700;margin-top:1px}
.why-title{font-family:"Syne",sans-serif;font-weight:700;font-size:.95rem;margin-bottom:.2rem}
.why-desc{font-size:.78rem;color:var(--muted);line-height:1.7}

/* ── STATS BAR ── */
.stats-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);
  border:1px solid var(--border);border-radius:12px;overflow:hidden;margin:0 0 0}
.stat-box{background:var(--surface);padding:2rem 1.5rem;text-align:center}
.stat-box .n{font-family:"Syne",sans-serif;font-size:2rem;font-weight:800;color:var(--blue);line-height:1}
.stat-box .l{font-size:.7rem;color:var(--muted);margin-top:.5rem;text-transform:uppercase;letter-spacing:.08em}

/* ── INSTALL ── */
.install{text-align:center}
.install .section-sub{margin:0 auto 2.5rem;text-align:center}
.install-code{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:2rem 2.5rem;margin:0 auto;max-width:600px;text-align:left;font-size:.85rem;line-height:2.1}
.install-code .comment{color:var(--muted)}
.install-note{font-size:.78rem;color:var(--muted);margin-top:1.25rem;text-align:center}

/* ── CTA BANNER ── */
.cta-banner{background:linear-gradient(135deg,var(--blue) 0%,#08498f 100%);
  border-radius:20px;padding:4rem;text-align:center;margin:0;position:relative;overflow:hidden}
.cta-banner::before{content:"";position:absolute;inset:0;
  background:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.04'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
  opacity:.5}
.cta-title{font-size:clamp(1.6rem,3.5vw,2.4rem);font-weight:800;margin-bottom:.75rem;position:relative}
.cta-sub{color:rgba(255,255,255,.7);font-size:.95rem;margin-bottom:2rem;position:relative}
.btn-white{background:#fff;color:var(--blue);font-weight:700}
.btn-white:hover{background:rgba(255,255,255,.9);transform:translateY(-2px);box-shadow:0 16px 40px rgba(0,0,0,.25)}

/* ── FOOTER ── */
footer{background:var(--surface);border-top:1px solid var(--border);padding:3rem 0 2rem;margin-top:2rem}
.footer-inner{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1.5rem}
.footer-brand{display:flex;align-items:center;gap:.75rem}
.footer-name{font-family:"Syne",sans-serif;font-weight:700;font-size:1rem}
.footer-copy{font-size:.75rem;color:var(--muted)}
.footer-links{display:flex;gap:1.5rem;list-style:none}
.footer-links a{color:var(--muted);font-size:.75rem;transition:color .2s}
.footer-links a:hover{color:var(--yellow)}

/* ── ANIMATIONS ── */
@keyframes fadeUp{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:translateY(0)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
@keyframes orbPulse{0%,100%{opacity:.8;transform:translateX(-50%) scale(1)}50%{opacity:1;transform:translateX(-50%) scale(1.05)}}

/* ── SCROLL ANIMATIONS ── */
.reveal{opacity:0;transform:translateY(32px);transition:opacity .6s ease,transform .6s ease}
.reveal.visible{opacity:1;transform:translateY(0)}

/* ── RESPONSIVE ── */
@media(max-width:900px){
  .nav-links{display:none}
  .why-grid{grid-template-columns:1fr;gap:2.5rem}
  .stats-bar{grid-template-columns:repeat(2,1fr)}
  .features-grid{grid-template-columns:1fr}
}
@media(max-width:600px){
  .hero-stats{gap:1.75rem}
  .stats-bar{grid-template-columns:1fr 1fr}
  .hero-title{font-size:clamp(2.2rem,12vw,3rem)}
  .install-code{padding:1.5rem 1.2rem}
  .cta-banner{padding:2.5rem 1.5rem}
}
</style>
</head>
<body>

<!-- NAV -->
<nav id="navbar">
<div class="container">
<div class="nav-inner">
<a href="#" class="logo">
<div class="logo-mark"></div>
<span class="logo-name">BPanel</span>
</a>
<ul class="nav-links">
<li><a href="#features">Tính năng</a></li>
<li><a href="#why">Tại sao BPanel</a></li>
<li><a href="#install">Cài đặt</a></li>
<li><a href="https://github.com/BNIX-VN/bpanel" target="_blank">GitHub</a></li>
</ul>
<div class="nav-cta">
<a href="#install" class="btn btn-primary btn-sm">Cài đặt</a>
</div>
</div>
</div>
</nav>

<!-- HERO -->
<section class="hero">
<div class="hero-bg">
<div class="hero-grid"></div>
<div class="hero-orb"></div>
<div class="hero-orb2"></div>
</div>
<div class="container">
<div class="hero-content">
<div class="hero-badge">
<span class="pulse-dot"></span>
v1.0.4 — Ubuntu 24.04 LTS Ready
</div>
<h1 class="hero-title">
Quản lý hosting,<br>
<span class="yellow">toàn quyền kiểm soát.</span>
</h1>
<p class="hero-sub">
BPanel là control panel nhẹ cho Ubuntu 24.04. Deploy WordPress,
quản lý database, SSL, firewall, backup — tất cả từ một giao diện
web sạch sẽ, không phức tạp.
</p>
<div class="hero-actions">
<a href="#install" class="btn btn-primary">Bắt đầu cài đặt</a>
<a href="https://github.com/BNIX-VN/bpanel" target="_blank" class="btn btn-ghost">Xem trên GitHub</a>
</div>

<div class="hero-terminal">
<div class="t-header">
<div class="dot dot-r"></div>
<div class="dot dot-y"></div>
<div class="dot dot-g"></div>
<span class="t-title">SSH — bpanel installer</span>
</div>
<div class="t-body">
<div><span class="prompt">root@server:~# </span><span class="cmd">BPANEL_VERSION=v1.0.4</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">apt-get update && apt-get install -y curl unzip</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">curl -fL "https://github.com/BNIX-VN/bpanel/archive/refs/tags/\${BPANEL_VERSION}.zip" -o /tmp/bpanel-release.zip</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">unzip -q /tmp/bpanel-release.zip -d /tmp/bpanel-release && mv /tmp/bpanel-release/bpanel-* /opt/bpanel-source</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">bash /opt/bpanel-source/installer/install.sh</span></div>
<div class="output">Fetching installer... OK</div>
<div class="output">Installing BPanel v1.0.4...</div>
<div class="output">Panel ready at: https://your-server-ip:2087</div>
<div><span class="prompt">root@server:~# </span><span class="cursor">▋</span></div>
</div>
</div>

<div class="hero-stats">
<div class="stat"><div class="stat-n">v1.0.4</div><div class="stat-l">Phiên bản hiện tại</div></div>
<div class="stat"><div class="stat-n">~3 phút</div><div class="stat-l">Cài đặt nhanh</div></div>
<div class="stat"><div class="stat-n">1 GB RAM</div><div class="stat-l">Yêu cầu tối thiểu</div></div>
<div class="stat"><div class="stat-n">100%</div><div class="stat-l">Open Source</div></div>
</div>
</div>
</div>
</section>

<!-- FEATURES -->
<section class="section" id="features">
<div class="container">
<div class="section-label reveal">Tính năng</div>
<h2 class="section-title reveal">Tất cả những gì bạn cần,<br>không gì thừa.</h2>
<p class="section-sub reveal">
BPanel đóng gói những công cụ mạnh mẽ nhất cho WordPress hosting
vào một giao diện trực quan, để bạn tập trung vào website thay vì server.
</p>
<div class="features-grid">
<div class="feature-card reveal">
<div class="feat-icon">W</div>
<div class="feat-name">WordPress One-Click</div>
<div class="feat-desc">Deploy WordPress site trong vài giây. PHP 8.3 & 8.4, tích hợp WP-CLI sẵn sàng, quản lý plugin và theme dễ dàng.</div>
</div>
<div class="feature-card reveal">
<div class="feat-icon">S</div>
<div class="feat-name">SSL tự động</div>
<div class="feat-desc">Let's Encrypt certificate tự động qua Certbot. Renew không cần can thiệp thủ công. Hỗ trợ Wildcard.</div>
</div>
<div class="feature-card reveal">
<div class="feat-icon">D</div>
<div class="feat-name">Database Management</div>
<div class="feat-desc">Tạo và quản lý MariaDB database. Truy cập phpMyAdmin với SSO token 60 giây — an toàn và tiện lợi.</div>
</div>
<div class="feature-card reveal">
<div class="feat-icon">F</div>
<div class="feat-name">File Manager</div>
<div class="feat-desc">Upload, chỉnh sửa, nén và giải nén file trực tiếp trên trình duyệt. Không cần SFTP client.</div>
</div>
<div class="feature-card reveal">
<div class="feat-icon">B</div>
<div class="feat-name">Backup & Restore</div>
<div class="feat-desc">Archive site files + SQL, scheduled backup, upload/download. Tích hợp SFTP backup target cho off-site storage.</div>
</div>
<div class="feature-card reveal">
<div class="feat-icon">W</div>
<div class="feat-name">WAF & Firewall</div>
<div class="feat-desc">Nginx ModSecurity/WAF cài sẵn. UFW firewall với protected defaults cho panel, web, mail. HTTP Flood limit per-site.</div>
</div>
<div class="feature-card reveal">
<div class="feat-icon">U</div>
<div class="feat-name">User Management</div>
<div class="feat-desc">Panel user map trực tiếp tới Linux/SFTP user. Phân quyền Admin / End User rõ ràng. Quick-login as user.</div>
</div>
<div class="feature-card reveal">
<div class="feat-icon">M</div>
<div class="feat-name">Resource Monitor</div>
<div class="feat-desc">Theo dõi CPU, RAM, disk, network throughput theo thời gian thực. Dashboard trực quan, cập nhật liên tục.</div>
</div>
<div class="feature-card reveal">
<div class="feat-icon">P</div>
<div class="feat-name">PHP-FPM Config</div>
<div class="feat-desc">Chỉnh sửa PHP-FPM configuration riêng cho từng PHP version. Hỗ trợ PHP 8.3 và 8.4, tunable per-site.</div>
</div>
</div>
</div>
</section>

<!-- WHY -->
<section class="section why" id="why">
<div class="container">
<div class="why-grid">
<div>
<div class="section-label reveal">Tại sao BPanel</div>
<h2 class="section-title reveal">Đơn giản,<br>nhẹ, mạnh mẽ.</h2>
<p class="section-sub reveal">
Không cần hàng chục GB RAM. Không cần cấu hình phức tạp.
BPanel chạy trên chính server của bạn, với những gì bạn thực sự cần.
</p>
<a href="#install" class="btn btn-primary reveal">Cài đặt ngay</a>
</div>
<ul class="why-list">
<li class="why-item reveal">
<div class="why-check">✓</div>
<div>
<div class="why-title">Nhẹ — chỉ cần 1GB RAM</div>
<div class="why-desc">Có thể chạy trên VPS 1 vCPU / 1GB RAM. Không ngốn tài nguyên như cPanel hay Plesk.</div>
</div>
</li>
<li class="why-item reveal">
<div class="why-check">✓</div>
<div>
<div class="why-title">Mã nguồn mở hoàn toàn</div>
<div class="why-desc">Tự do sửa đổi, kiểm tra code, contribute. Không phụ thuộc vào nhà cung cấp độc quyền.</div>
</div>
</li>
<li class="why-item reveal">
<div class="why-check">✓</div>
<div>
<div class="why-title">Cài đặt trong 3 phút</div>
<div class="why-desc">Chạy một command duy nhất. Không cần Docker, không cần compile từ source. Không có magic.</div>
</div>
</li>
<li class="why-item reveal">
<div class="why-check">✓</div>
<div>
<div class="why-title">WordPress-first design</div>
<div class="why-desc">Được thiết kế cho WordPress/PHP workloads từ đầu. Không phải adapter cho những thứ khác.</div>
</div>
</li>
<li class="why-item reveal">
<div class="why-check">✓</div>
<div>
<div class="why-title">Bảo mật tích hợp</div>
<div class="why-desc">2FA, ModSecurity WAF, UFW firewall, cron job whitelist — bảo mật đa lớp mà không cần cấu hình thủ công.</div>
</div>
</li>
</ul>
</div>
</div>
</section>

<!-- STATS -->
<section class="section">
<div class="container">
<div class="stats-bar reveal">
<div class="stat-box"><div class="n">1GB</div><div class="l">RAM tối thiểu</div></div>
<div class="stat-box"><div class="n">Ubuntu 24.04</div><div class="l">OS Support</div></div>
<div class="stat-box"><div class="n">~3 phút</div><div class="l">Install time</div></div>
<div class="stat-box"><div class="n">MIT</div><div class="l">Open Source</div></div>
</div>
</div>
</section>

<!-- CTA -->
<section class="section">
<div class="container">
<div class="cta-banner reveal">
<h2 class="cta-title">Sẵn sàng để bắt đầu?</h2>
<p class="cta-sub">Cài đặt BPanel trên Ubuntu 24.04 LTS trong vòng 3 phút.</p>
<a href="#install" class="btn btn-white">Cài đặt ngay →</a>
</div>
</div>
</section>

<!-- INSTALL -->
<section class="section install" id="install">
<div class="container">
<div class="section-label reveal" style="justify-content:center">Cài đặt</div>
<h2 class="section-title reveal">Sẵn sàng trong 3 phút.</h2>
<p class="section-sub reveal">Chạy command bên dưới trên Ubuntu 24.04 LTS (clean install khuyến nghị).</p>
<div class="install-code reveal">
<div><span class="comment"># SSH vào server với quyền root</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">BPANEL_VERSION=v1.0.4</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">apt-get update && apt-get install -y curl unzip</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">curl -fL "https://github.com/BNIX-VN/bpanel/archive/refs/tags/\${BPANEL_VERSION}.zip" -o /tmp/bpanel-release.zip</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">unzip -q /tmp/bpanel-release.zip -d /tmp/bpanel-release && mv /tmp/bpanel-release/bpanel-* /opt/bpanel-source</span></div>
<div><span class="prompt">root@server:~# </span><span class="cmd">bash /opt/bpanel-source/installer/install.sh</span></div>
<div>&nbsp;</div>
<div><span class="comment"># Sau khi cài xong, truy cập panel tại:</span></div>
<div class="output">https://your-server-ip:2087</div>
<div>&nbsp;</div>
<div><span class="comment"># Yêu cầu hệ thống:</span></div>
<div><span class="comment">#   • Ubuntu 24.04 LTS (clean install)</span></div>
<div><span class="comment">#   • 1 vCPU / 1 GB RAM (min) — 2 vCPU / 2 GB RAM (khuyến nghị)</span></div>
<div><span class="comment">#   • Root SSH access</span></div>
<div><span class="comment">#   • Domain trỏ về IP public (tùy chọn — cho SSL trên domain)</span></div>
</div>
<p class="install-note reveal">Cài đặt không ảnh hưởng đến các service hiện có trên server.</p>
<div style="margin-top:2rem;display:flex;gap:.9rem;justify-content:center;flex-wrap:wrap" class="reveal">
<a href="https://github.com/BNIX-VN/bpanel" target="_blank" class="btn btn-ghost">Tài liệu đầy đủ</a>
<a href="https://github.com/BNIX-VN/bpanel/releases" target="_blank" class="btn btn-ghost">Xem Release</a>
</div>
</div>
</section>

<!-- FOOTER -->
<footer>
<div class="container">
<div class="footer-inner">
<div class="footer-brand">
<div class="logo-mark" style="width:28px;height:28px;border-radius:6px;position:relative;overflow:hidden">
<div style="position:absolute;bottom:0;left:0;right:0;height:6px;background:var(--yellow);border-radius:0 0 6px 6px"></div>
</div>
<span class="footer-name">BPanel</span>
</div>
<p class="footer-copy">© 2026 BPanel. Mã nguồn mở theo MIT License.</p>
<ul class="footer-links">
<li><a href="https://github.com/BNIX-VN/bpanel" target="_blank">GitHub</a></li>
<li><a href="#features">Tính năng</a></li>
<li><a href="#install">Cài đặt</a></li>
</ul>
</div>
</div>
</footer>

<script>
(function(){
  // Navbar scroll effect
  var nav = document.getElementById('navbar');
  window.addEventListener('scroll', function(){
    nav.classList.toggle('scrolled', window.scrollY > 20);
  }, {passive:true});

  // Scroll reveal
  var reveals = document.querySelectorAll('.reveal');
  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(e.isIntersecting){
        e.target.classList.add('visible');
        io.unobserve(e.target);
      }
    });
  }, {threshold:0.1, rootMargin:'0px 0px -40px 0px'});
  reveals.forEach(function(el){ io.observe(el); });
})();
</script>

</body>
</html>
`);

fs.writeFileSync('e:/2026/bpanel/bpanel/landing.html', s.join(''), 'utf8');
console.log('Done! Total chars:', s.join('').length);
