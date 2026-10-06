"""Giao diện Liquid Glass cho dashboard: CSS thuần, không JS, không ảnh, không font ngoài.
Tương thích CSP hiện tại (default-src 'none'; style-src 'unsafe-inline')."""

CSS = r"""
:root{
  --bg0:#0b1020;--fg:#eef1ff;--muted:rgba(238,241,255,.62);
  --glass:rgba(255,255,255,.07);--sheen:rgba(255,255,255,.17);
  --edge:rgba(255,255,255,.24);--line:rgba(255,255,255,.09);
  --acc:#6d7bff;--acc2:#9a6bff;--bad:#ff5a62;--ok:#2fbf86;
  --shadow:rgba(2,6,23,.45);--r:22px
}
@media(prefers-color-scheme:light){:root{
  --bg0:#e8ecfa;--fg:#151a30;--muted:rgba(21,26,48,.6);
  --glass:rgba(255,255,255,.5);--sheen:rgba(255,255,255,.9);
  --edge:rgba(255,255,255,.95);--line:rgba(21,26,48,.08);--shadow:rgba(70,80,140,.2)
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;background:var(--bg0);color:var(--fg);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI Variable","Segoe UI",Roboto,sans-serif}
body::before{content:"";position:fixed;inset:0;z-index:-1;
  background:
   radial-gradient(40vmax 40vmax at 12% 8%,rgba(88,101,242,.62),transparent 62%),
   radial-gradient(34vmax 34vmax at 90% 16%,rgba(0,200,210,.36),transparent 62%),
   radial-gradient(38vmax 38vmax at 72% 94%,rgba(255,80,165,.34),transparent 62%),
   radial-gradient(30vmax 30vmax at 6% 88%,rgba(140,95,255,.42),transparent 62%),
   var(--bg0)}

/* ---- kính: header, thẻ, bảng, khung log, form đăng nhập ---- */
header,.card,.wrap,pre,.login,.flash{
  background:
   linear-gradient(135deg,var(--sheen) 0%,rgba(255,255,255,.03) 38%,rgba(255,255,255,.02) 62%,rgba(255,255,255,.1) 100%),
   var(--glass);
  -webkit-backdrop-filter:blur(24px) saturate(190%);backdrop-filter:blur(24px) saturate(190%);
  border:1px solid var(--line);
  box-shadow:inset 0 1px 0 var(--edge),inset 0 -1px 0 rgba(255,255,255,.05),
             inset 1px 0 0 rgba(255,255,255,.1),0 14px 40px var(--shadow)}

header{position:sticky;top:max(.6rem,env(safe-area-inset-top));z-index:5;margin:.6rem;
  display:flex;flex-wrap:wrap;gap:.4rem 1rem;align-items:center;padding:.5rem .8rem;border-radius:26px}
header strong{font-weight:650;letter-spacing:-.01em}
nav{display:flex;flex-wrap:wrap;gap:.2rem;flex:1}
nav a{padding:.35rem .85rem;border-radius:999px;color:inherit;text-decoration:none;opacity:.78;
  transition:background .15s,opacity .15s}
nav a:hover{opacity:1;background:rgba(255,255,255,.1)}
nav a.on{opacity:1;color:#fff;
  background:linear-gradient(180deg,rgba(255,255,255,.28),rgba(255,255,255,.04)),var(--acc);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.55),0 4px 14px rgba(109,123,255,.45)}

main{max-width:1000px;margin:0 auto;padding:1rem}
h1{font-size:1.6rem;font-weight:650;letter-spacing:-.02em;margin:.4rem 0 1.1rem}
h2{font-size:1.02rem;font-weight:600;margin:1.6rem 0 .6rem;color:var(--muted)}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem}
.card{border-radius:var(--r);padding:.85rem 1rem}
.card b{display:block;font-size:1.2rem;font-weight:650;letter-spacing:-.01em;overflow-wrap:anywhere}
.card span{color:var(--muted);font-size:.85rem}

.wrap{overflow-x:auto;border-radius:var(--r)}
table{border-collapse:collapse;width:100%}
th,td{padding:.6rem .85rem;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.8rem;font-weight:600;color:var(--muted)}
tr:last-child td{border-bottom:0}
tr:hover td{background:rgba(255,255,255,.04)}

input,select,button{font:inherit;padding:.5rem .8rem;border-radius:14px;color:inherit;
  border:1px solid var(--line);background:rgba(255,255,255,.08);
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
  box-shadow:inset 0 1px 2px rgba(0,0,0,.18)}
input::placeholder{color:var(--muted)}
select option{color:#151a30}
button{cursor:pointer;color:#fff;border:0;font-weight:600;
  background:linear-gradient(180deg,rgba(255,255,255,.32),rgba(255,255,255,0) 55%),linear-gradient(135deg,var(--acc),var(--acc2));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.6),0 6px 18px rgba(109,123,255,.4);
  transition:transform .12s,filter .12s}
button:hover{filter:brightness(1.1)}
button:active{transform:scale(.97)}
button.bad{background:linear-gradient(180deg,rgba(255,255,255,.3),rgba(255,255,255,0) 55%),var(--bad);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.55),0 6px 18px rgba(255,90,98,.38)}
button.ghost{color:inherit;background:rgba(255,255,255,.08);border:1px solid var(--line);
  box-shadow:inset 0 1px 0 var(--edge)}
:focus-visible{outline:2px solid #fff;outline-offset:2px;box-shadow:0 0 0 5px rgba(109,123,255,.6)}

form.inline{display:inline}
form.row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.5rem 0}

.flash{padding:.6rem .95rem;border-radius:16px;margin-bottom:1rem;
  box-shadow:inset 0 1px 0 var(--edge),inset 0 0 0 1px rgba(47,191,134,.55),0 10px 30px var(--shadow)}
.err{box-shadow:inset 0 1px 0 var(--edge),inset 0 0 0 1px rgba(255,90,98,.7),0 10px 30px var(--shadow)}

pre{border-radius:var(--r);padding:.9rem 1rem;overflow:auto;font-size:.8rem;max-height:70vh;
  background:rgba(5,8,20,.45)}
a{color:var(--acc)}
.muted{color:var(--muted)}
.login{max-width:360px;margin:14vh auto;padding:1.4rem;border-radius:30px}
.login h1{margin-top:0}

/* trình duyệt không hỗ trợ backdrop-filter hoặc người dùng tắt hiệu ứng trong suốt */
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){
  header,.card,.wrap,pre,.login,.flash{background:rgba(28,33,66,.92)}
}
@media(prefers-reduced-transparency:reduce){
  header,.card,.wrap,pre,.login,.flash{-webkit-backdrop-filter:none;backdrop-filter:none;background:var(--bg0)}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
@media(max-width:520px){main{padding:.7rem}h1{font-size:1.4rem}header{border-radius:22px}}
"""
