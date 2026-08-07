"""CSS for the dashboard shell, split out of `shell.py` to keep that file under the
project's 500-line limit. Design language: "quiet terminal" — near-black surfaces,
hairline borders, a single warm gold identity accent, green/red reserved for P&L.
"""

SHELL_CSS = r"""
:root{
  --bg:#0a0b0e; --bg-2:#0e1014; --panel:#12141a; --panel-2:#171a21;
  --border:#22262f; --text:#e9ebef; --muted:#9099a6; --faint:#5d6570;
  --gold:#d9a441; --gold-dim:rgba(217,164,65,.13);
  --green:#43b86a; --red:#e05252; --amber:#e0862c; --blue:#5b8def;
  --grid:rgba(255,255,255,.06);
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  --mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
}
:root[data-theme="light"]{
  --bg:#f6f6f4; --bg-2:#f0efec; --panel:#ffffff; --panel-2:#faf9f7;
  --border:#e3e2dd; --text:#191b1f; --muted:#6b7280; --faint:#9aa0a8;
  --gold:#a97e22; --gold-dim:rgba(169,126,34,.10);
  --green:#1e8f4d; --red:#c93b3b; --amber:#b26a15; --blue:#3b66c4;
  --grid:rgba(0,0,0,.07);
}
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);
  font-size:13.5px;line-height:1.5;-webkit-font-smoothing:antialiased;overflow-x:hidden}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.app{display:grid;grid-template-columns:auto 1fr;min-height:100vh}
.sidebar{background:var(--bg-2);border-right:1px solid var(--border);width:212px;flex:none;
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh;transition:width .15s ease}
.sidebar.collapsed{width:60px}
.brand{display:flex;align-items:center;gap:10px;padding:16px 14px 14px;border-bottom:1px solid var(--border)}
.brand .mark{width:28px;height:28px;border:1px solid var(--gold);border-radius:6px;flex:none;
  display:grid;place-items:center;color:var(--gold);font-size:12px}
.brand .name{font-weight:650;letter-spacing:.14em;font-size:13px;text-transform:uppercase}
.brand .sub{color:var(--faint);font-size:10.5px;letter-spacing:.02em}
.sidebar.collapsed .brand{padding:16px 0;justify-content:center}
.sidebar.collapsed .brand-text,.sidebar.collapsed .nav a span,.sidebar.collapsed .sidefoot span{display:none}
.nav{padding:10px 8px;display:flex;flex-direction:column;gap:1px;flex:1;overflow-y:auto}
.nav a{display:flex;align-items:center;gap:11px;padding:8px 11px;border-radius:7px;color:var(--muted);
  font-size:13px;text-decoration:none;cursor:pointer;border-left:2px solid transparent;white-space:nowrap}
.nav a:hover{background:var(--panel);color:var(--text)}
.nav a.active{background:var(--gold-dim);color:var(--text);border-left-color:var(--gold)}
.nav a .ic{width:16px;height:16px;flex:none;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round}
.nav a.active .ic{stroke:var(--gold)}
.sidebar.collapsed .nav a{justify-content:center;padding:9px 0}
.sidefoot{padding:10px 14px;border-top:1px solid var(--border);color:var(--faint);font-size:11px;
  display:flex;align-items:center;justify-content:space-between;gap:6px}
.collapse-btn{background:none;border:1px solid var(--border);color:var(--muted);border-radius:6px;
  width:22px;height:22px;flex:none;cursor:pointer;font-size:11px;line-height:1}
.collapse-btn:hover{color:var(--text);border-color:var(--gold)}
.sidebar.collapsed .sidefoot{justify-content:center}
.main{display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;flex-wrap:wrap;gap:8px 10px;padding:10px 20px;
  border-bottom:1px solid var(--border);background:var(--bg-2);position:sticky;top:0;z-index:5}
.page-title{font-size:15px;font-weight:600}
.spacer{flex:1}
.menu-btn{display:none;background:none;border:1px solid var(--border);color:var(--text);border-radius:7px;
  width:32px;height:32px;cursor:pointer;flex:none}
.status-chips{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:6px;font-size:11.5px;
  font-weight:550;border:1px solid var(--border);color:var(--muted);background:var(--panel);white-space:nowrap}
.chip .dot{width:6px;height:6px;border-radius:50%;background:var(--faint)}
.chip.ok{color:var(--green);border-color:color-mix(in srgb,var(--green) 35%,var(--border))}
.chip.ok .dot{background:var(--green)}
.chip.bad{color:var(--red);border-color:color-mix(in srgb,var(--red) 35%,var(--border))}
.chip.bad .dot{background:var(--red)}
.chip.warn{color:var(--amber)} .chip.warn .dot{background:var(--amber)}
.clock{font-family:var(--mono);color:var(--muted);font-size:12px;min-width:88px;text-align:right}
.theme-btn{background:none;border:1px solid var(--border);color:var(--muted);width:32px;height:32px;
  border-radius:7px;cursor:pointer;font-size:13px}
.badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:5px;font-size:10.5px;
  font-weight:650;letter-spacing:.06em;text-transform:uppercase}
.badge.green{background:color-mix(in srgb,var(--green) 14%,transparent);color:var(--green)}
.badge.red{background:color-mix(in srgb,var(--red) 14%,transparent);color:var(--red)}
.badge.amber{background:color-mix(in srgb,var(--amber) 14%,transparent);color:var(--amber)}
.badge.blue{background:color-mix(in srgb,var(--blue) 14%,transparent);color:var(--blue)}
.badge.gold{background:var(--gold-dim);color:var(--gold)}
.badge.gray{background:var(--panel-2);color:var(--muted)}
.content{padding:20px;display:flex;flex-direction:column;gap:14px}
.grid{display:grid;gap:12px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.cols-2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.card{background:var(--panel);border:1px solid var(--border);border-radius:9px;padding:16px}
.card h3{margin:0 0 12px;font-size:11px;color:var(--faint);font-weight:650;letter-spacing:.09em;text-transform:uppercase}
.kpi .label{color:var(--faint);font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase}
.kpi .val{font-size:22px;font-weight:600;margin-top:6px;font-family:var(--mono);font-variant-numeric:tabular-nums}
.kpi .sub{margin-top:4px;font-size:11.5px;color:var(--muted)}
.pos{color:var(--green)} .neg{color:var(--red)} .neu{color:var(--text)}
.chart{width:100%;height:250px}
.tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.tbl th{color:var(--faint);font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;font-weight:600;
  text-align:left;padding:6px 10px;border-bottom:1px solid var(--border)}
.tbl td{padding:7px 10px;border-bottom:1px solid var(--border)}
.tbl tr:last-child td{border-bottom:none}
.tbl td.r,.tbl th.r{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}
.kv{display:flex;flex-direction:column}
.kv .row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:7px 2px;
  border-bottom:1px solid var(--border)}
.kv .row:last-child{border-bottom:none}
.kv .k{color:var(--muted);font-size:12.5px}
.kv .v{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:12.5px}
.bar{height:5px;background:var(--panel-2);border-radius:99px;overflow:hidden;margin-top:6px}
.bar>span{display:block;height:100%;background:var(--gold);border-radius:99px}
.empty{color:var(--faint);text-align:center;padding:22px;font-size:12.5px}
.alert{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border-radius:7px;
  border:1px solid var(--border);background:var(--panel-2);margin-bottom:8px}
.alert:last-child{margin-bottom:0}
.alert .sev{width:7px;height:7px;border-radius:50%;margin-top:6px;flex:none;background:var(--muted)}
.alert.critical .sev{background:var(--red)} .alert.warning .sev{background:var(--amber)}
.gates{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.gate{display:flex;align-items:center;gap:7px;padding:7px 11px;border-radius:7px;border:1px solid var(--border);
  background:var(--panel-2);font-size:12px}
.gate .st{width:7px;height:7px;border-radius:50%;background:var(--faint)}
.gate.on .st{background:var(--green)} .gate.off .st{background:var(--faint)}
.input{background:var(--panel-2);border:1px solid var(--border);border-radius:7px;color:var(--text);
  padding:8px 11px;font-size:12.5px;width:100%;font-family:var(--sans)}
.input:focus{outline:none;border-color:var(--gold)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.pill{padding:5px 11px;border-radius:6px;border:1px solid var(--border);background:var(--panel);
  color:var(--muted);cursor:pointer;font-size:11.5px;font-weight:600}
.pill.on{color:var(--gold);border-color:var(--gold);background:var(--gold-dim)}
.log-line{display:grid;grid-template-columns:80px 64px 1fr;gap:10px;padding:6px 10px;
  font-family:var(--mono);font-size:12px;border-bottom:1px solid var(--border)}
.log-line:last-child{border-bottom:none}
.log-line .t{color:var(--faint)} .log-line .k{color:var(--faint)}
@media(max-width:820px){.sidebar{position:fixed;z-index:20;height:100vh;transform:translateX(-100%);transition:transform .2s}
 .sidebar.open{transform:none}.app{grid-template-columns:1fr}.menu-btn{display:block}}
@media(max-width:640px){.clock,#marketChip{display:none}.topbar{padding:10px 14px}}
"""
