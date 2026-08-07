"""CSS for the dashboard shell, split out of `shell.py` to keep that file under the
project's 500-line limit. Design language: "Industry" -- a blueprint/schematic
system. Square corners everywhere, hairline dividers, small "+" corner
registration marks on every card, Barlow Condensed headings/numerics over Barlow
body text, a single steel-blue accent reserved for the one primary action per
screen; everything else stays outline/transparent.
"""

SHELL_CSS = r"""
:root{
  --bg:#f2f2f3; --bg-2:#e9e9ea; --panel:#e9e9ea; --panel-2:#e0e0e1;
  --border:rgba(29,31,32,.16); --text:#1d1f20; --muted:#5d5d60; --faint:#98989b;
  --gold:#5980a6; --gold-dim:#eef6ff; --gold-deep:#416180;
  --green:oklch(0.5 0.11 150); --green-dim:oklch(0.94 0.05 150);
  --red:oklch(0.52 0.15 22); --red-dim:oklch(0.94 0.05 22);
  --amber:oklch(0.6 0.14 70); --amber-dim:oklch(0.94 0.06 70);
  --blue:#416180;
  --grid:rgba(29,31,32,.12);
  --sans:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  --heading:'Barlow Condensed',var(--sans);
  --mono:var(--heading);
}
:root[data-theme="dark"]{
  --bg:#17181a; --bg-2:#1d1e20; --panel:#232427; --panel-2:#2a2b2e;
  --border:rgba(255,255,255,.14); --text:#f2f2f3; --muted:#a9a9ac; --faint:#75757a;
  --gold:#8fb4d6; --gold-dim:rgba(89,128,166,.24); --gold-deep:#d6ebff;
  --green:oklch(0.75 0.13 150); --green-dim:oklch(0.3 0.06 150);
  --red:oklch(0.72 0.16 22); --red-dim:oklch(0.3 0.07 22);
  --amber:oklch(0.78 0.14 70); --amber-dim:oklch(0.3 0.07 70);
  --blue:#d6ebff;
  --grid:rgba(255,255,255,.12);
}
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);
  font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased;overflow-x:hidden}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.app{display:grid;grid-template-columns:auto 1fr;min-height:100vh}
.sidebar{background:var(--bg-2);border-right:1px solid var(--border);width:212px;flex:none;
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh;transition:width .15s ease}
.sidebar.collapsed{width:60px}
.brand{display:flex;align-items:center;gap:10px;padding:18px 16px 16px;border-bottom:1px solid var(--border)}
.brand .mark{width:30px;height:30px;border:1px solid var(--gold);flex:none;
  display:grid;place-items:center;color:var(--gold);font-size:13px;background:var(--gold-dim)}
.brand .name{font-family:var(--heading);font-weight:700;font-size:17px;letter-spacing:.02em;text-transform:uppercase}
.brand .sub{color:var(--faint);font-size:11px;letter-spacing:.01em;margin-top:1px}
.sidebar.collapsed .brand{padding:16px 0;justify-content:center}
.sidebar.collapsed .brand-text,.sidebar.collapsed .nav a span,.sidebar.collapsed .sidefoot span{display:none}
.nav{padding:12px 8px;display:flex;flex-direction:column;gap:2px;flex:1;overflow-y:auto}
.nav a{display:flex;align-items:center;gap:11px;padding:8px 11px;color:var(--muted);
  font-size:13.5px;font-weight:500;text-decoration:none;cursor:pointer;border-left:2px solid transparent;white-space:nowrap}
.nav a:hover{background:var(--panel-2);color:var(--text)}
.nav a.active{background:var(--gold-dim);color:var(--gold-deep);border-left-color:var(--gold);font-weight:650}
.nav a .ic{width:16px;height:16px;flex:none;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round}
.nav a.active .ic{stroke:var(--gold-deep)}
.sidebar.collapsed .nav a{justify-content:center;padding:9px 0}
.sidefoot{padding:12px 14px;border-top:1px solid var(--border);color:var(--faint);font-size:11px;
  display:flex;align-items:center;justify-content:space-between;gap:6px}
.collapse-btn{background:none;border:1px solid var(--border);color:var(--muted);
  width:22px;height:22px;flex:none;cursor:pointer;font-size:11px;line-height:1}
.collapse-btn:hover{color:var(--text);border-color:var(--gold)}
.sidebar.collapsed .sidefoot{justify-content:center}
.main{display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;flex-wrap:wrap;gap:8px 10px;padding:12px 22px;
  border-bottom:1px solid var(--border);background:var(--bg-2);position:sticky;top:0;z-index:5}
.page-title{font-family:var(--heading);font-size:19px;font-weight:650;letter-spacing:.01em;text-transform:uppercase}
.spacer{flex:1}
.menu-btn{display:none;background:none;border:1px solid var(--border);color:var(--text);
  width:32px;height:32px;cursor:pointer;flex:none}
.status-chips{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;font-size:11.5px;
  font-weight:600;border:1px solid var(--border);color:var(--muted);background:transparent;white-space:nowrap}
.chip .dot{width:6px;height:6px;border-radius:50%;background:var(--faint)}
.chip.ok{color:var(--green);border-color:var(--green)}
.chip.ok .dot{background:var(--green)}
.chip.bad{color:var(--red);border-color:var(--red)}
.chip.bad .dot{background:var(--red)}
.chip.warn{color:var(--amber);border-color:var(--amber)} .chip.warn .dot{background:var(--amber)}
.clock{font-family:var(--mono);color:var(--muted);font-size:13px;min-width:88px;text-align:right}
.theme-btn{background:none;border:1px solid var(--border);color:var(--muted);width:32px;height:32px;
  cursor:pointer;font-size:13px}
.badge{display:inline-flex;align-items:center;padding:2px 9px;font-size:10.5px;
  font-weight:650;letter-spacing:.04em;text-transform:uppercase;border:1px solid transparent}
.badge.green{background:var(--green-dim);color:var(--green);border-color:var(--green)}
.badge.red{background:var(--red-dim);color:var(--red);border-color:var(--red)}
.badge.amber{background:var(--amber-dim);color:var(--amber);border-color:var(--amber)}
.badge.blue{background:var(--gold-dim);color:var(--blue);border-color:var(--blue)}
.badge.gold{background:var(--gold-dim);color:var(--gold-deep);border-color:var(--gold)}
.badge.gray{background:transparent;color:var(--muted);border-color:var(--border)}
.section-label{font-family:var(--heading);font-size:13px;color:var(--faint);font-weight:650;
  letter-spacing:.04em;text-transform:uppercase;margin:4px 0 -2px}
.content{padding:22px;display:flex;flex-direction:column;gap:14px}
.grid{display:grid;gap:12px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.cols-2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.card{background:var(--panel);border:1px solid var(--border);padding:17px;position:relative}
.card h3{margin:0 0 12px;font-family:var(--heading);font-size:13px;color:var(--faint);font-weight:650;
  letter-spacing:.04em;text-transform:uppercase}
.corner{position:absolute;width:11px;height:11px;pointer-events:none}
.corner::before,.corner::after{content:"";position:absolute;background:var(--faint)}
.corner::before{top:5px;left:0;width:11px;height:1px}
.corner::after{top:0;left:5px;width:1px;height:11px}
.corner.tl{top:-1px;left:-1px} .corner.tr{top:-1px;right:-1px}
.corner.bl{bottom:-1px;left:-1px} .corner.br{bottom:-1px;right:-1px}
.kpi .label{color:var(--faint);font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.kpi .val{font-family:var(--heading);font-size:25px;font-weight:650;margin-top:6px;font-variant-numeric:tabular-nums}
.kpi .sub{margin-top:4px;font-size:11.5px;color:var(--muted)}
.pos{color:var(--green)} .neg{color:var(--red)} .neu{color:var(--text)}
.chart{width:100%;height:250px}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{color:var(--faint);font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;font-weight:650;
  text-align:left;padding:7px 10px;border-bottom:1px solid var(--border)}
.tbl td{padding:8px 10px;border-bottom:1px solid var(--border)}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover td{background:var(--panel-2)}
.tbl td.r,.tbl th.r{text-align:right;font-variant-numeric:tabular-nums}
.kv{display:flex;flex-direction:column}
.kv .row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 2px;
  border-bottom:1px solid var(--border)}
.kv .row:last-child{border-bottom:none}
.kv .k{color:var(--muted);font-size:12.5px}
.kv .v{font-variant-numeric:tabular-nums;font-size:12.5px;font-weight:600}
.bar{height:6px;background:var(--panel-2);overflow:hidden;margin-top:6px}
.bar>span{display:block;height:100%;background:var(--gold)}
.empty{color:var(--faint);text-align:center;padding:26px;font-size:12.5px}
.alert{display:flex;gap:10px;align-items:flex-start;padding:11px 13px;
  border:1px solid var(--border);background:var(--panel-2);margin-bottom:8px}
.alert:last-child{margin-bottom:0}
.alert .sev{width:7px;height:7px;border-radius:50%;margin-top:6px;flex:none;background:var(--muted)}
.alert.critical .sev{background:var(--red)} .alert.warning .sev{background:var(--amber)}
.gates{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.gate{display:flex;align-items:center;gap:7px;padding:7px 12px;border:1px solid var(--border);
  background:var(--panel-2);font-size:12px;font-weight:500}
.gate .st{width:7px;height:7px;border-radius:50%;background:var(--faint)}
.gate.on .st{background:var(--green)} .gate.off .st{background:var(--faint)}
.input{background:var(--bg);border:1px solid var(--border);color:var(--text);
  padding:8px 12px;font-size:13px;width:100%;font-family:var(--sans)}
.input:focus{outline:none;border-color:var(--gold)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.pill{padding:6px 14px;border:1px solid var(--border);background:transparent;
  color:var(--muted);cursor:pointer;font-size:12px;font-weight:600}
.pill:hover{border-color:var(--faint);color:var(--text)}
.pill.on{color:var(--bg);border-color:var(--text);background:var(--text)}
.btn{display:inline-flex;align-items:center;justify-content:center;padding:9px 16px;border:1px solid var(--border);
  background:transparent;color:var(--text);font-family:var(--heading);font-weight:650;font-size:13px;
  letter-spacing:.03em;text-transform:uppercase;cursor:pointer}
.btn:disabled{opacity:.5;cursor:default}
.btn-primary{background:var(--gold);border-color:var(--gold);color:#fff}
.log-line{display:grid;grid-template-columns:80px 64px 1fr;gap:10px;padding:7px 10px;
  font-size:12.5px;border-bottom:1px solid var(--border)}
.log-line:last-child{border-bottom:none}
.log-line .t{color:var(--faint);font-variant-numeric:tabular-nums} .log-line .k{color:var(--faint)}
@media(max-width:820px){.sidebar{position:fixed;z-index:20;height:100vh;transform:translateX(-100%);transition:transform .2s}
 .sidebar.open{transform:none}.app{grid-template-columns:1fr}.menu-btn{display:block}}
@media(max-width:640px){.clock,#marketChip{display:none}.topbar{padding:10px 14px}}
"""
