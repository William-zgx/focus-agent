from __future__ import annotations


BRANCH_TREE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Focus Agent Console</title>
  <style>
    [hidden] {
      display:none !important;
    }
    :root {
      color-scheme: dark;
      --bg-base:#0D0D12;
      --bg-primary:#14141C;
      --bg-secondary:#1C1C26;
      --bg-elevated:#252530;
      --bg-hover:#2A2A38;
      --accent-primary:#6366F1;
      --accent-primary-light:#818CF8;
      --accent-primary-glow:rgba(99,102,241,.4);
      --accent-violet:#8B5CF6;
      --accent-cyan:#06B6D4;
      --accent-emerald:#10B981;
      --accent-amber:#F59E0B;
      --accent-rose:#F43F5E;
      --text-primary:#F8FAFC;
      --text-secondary:#94A3B8;
      --text-tertiary:#64748B;
      --text-inverse:#0D0D12;
      --border-subtle:rgba(255,255,255,.06);
      --border-default:rgba(255,255,255,.1);
      --border-hover:rgba(255,255,255,.2);
      --radius-sm:6px;
      --radius-md:10px;
      --radius-lg:14px;
      --radius-xl:20px;
      --radius-2xl:28px;
      --radius-full:9999px;
      --duration-fast:150ms;
      --duration-normal:250ms;
      --duration-slow:400ms;
      --ease-default:cubic-bezier(0.4, 0, 0.2, 1);
      --ease-out:cubic-bezier(0, 0, 0.2, 1);
      --ease-bounce:cubic-bezier(0.34, 1.56, 0.64, 1);
      --gradient-brand:linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);
      --gradient-glow:radial-gradient(ellipse at center, rgba(99,102,241,.3) 0%, transparent 70%);
      --gradient-card-hover:linear-gradient(180deg, rgba(99,102,241,.1) 0%, transparent 100%);
      --bg:var(--bg-base);
      --panel:var(--bg-primary);
      --panel-2:var(--bg-secondary);
      --panel-3:var(--bg-elevated);
      --muted:var(--text-secondary);
      --text:var(--text-primary);
      --accent:var(--accent-primary);
      --accent-soft:var(--accent-primary-light);
      --border:var(--border-default);
      --success:var(--accent-emerald);
      --warn:var(--accent-amber);
      --danger:var(--accent-rose);
      --user-bubble:#6366F1;
      --user-bubble-top:#818CF8;
      --user-bubble-mid:#7367F5;
      --user-bubble-bottom:#8B5CF6;
      --user-bubble-border:rgba(159,160,255,.34);
      --user-bubble-glow:rgba(99,102,241,.3);
      --assistant-bubble:#1C1C26;
      --system-bubble-bg:color-mix(in srgb, var(--danger) 18%, var(--panel-2) 82%);
      --system-bubble-border:color-mix(in srgb, var(--danger) 42%, var(--border) 58%);
      --system-bubble-text:#FFD9E1;
      --system-code-header-text:#FFC1CF;
      --system-success-bubble-bg:color-mix(in srgb, var(--success) 16%, var(--panel-2) 84%);
      --system-success-bubble-border:color-mix(in srgb, var(--success) 40%, var(--border) 60%);
      --system-success-bubble-text:#CCFBEA;
      --system-success-code-header-text:#98F1CB;
      --input-bg:var(--bg-primary);
      --history-grad-a:rgba(99,102,241,.12);
      --history-grad-b:rgba(20,20,28,.96);
      --history-grad-c:rgba(13,13,18,.98);
      --shell-bg:
        radial-gradient(circle at top left, rgba(99,102,241,.2), transparent 32%),
        radial-gradient(circle at top right, rgba(6,182,212,.14), transparent 28%),
        linear-gradient(180deg, #161621 0%, #0D0D12 58%, #0A0A0F 100%);
      --shadow:0 8px 32px rgba(0,0,0,.5);
      --message-shadow:0 4px 16px rgba(0,0,0,.4);
      --sidebar-width:300px;
      --resizer-width:12px;
      --toolbar-shell-bg:linear-gradient(180deg, rgba(37,37,48,.94), rgba(28,28,38,.9));
      --toolbar-shell-border:color-mix(in srgb, var(--accent) 20%, var(--border) 80%);
      --toolbar-shell-shadow:0 8px 24px rgba(0,0,0,.34);
      --toolbar-button-text:var(--text);
      --toolbar-button-bg:linear-gradient(180deg, rgba(44,44,58,.98), rgba(28,28,38,.95));
      --toolbar-button-hover-bg:linear-gradient(180deg, rgba(56,56,74,.98), rgba(37,37,48,.98));
      --toolbar-button-border:color-mix(in srgb, var(--accent) 22%, var(--border) 78%);
      --toolbar-icon-bg:linear-gradient(180deg, rgba(129,140,248,.24), rgba(99,102,241,.14));
      --toolbar-icon-border:color-mix(in srgb, var(--accent) 24%, transparent);
      --toolbar-label-contrast:#F8FAFC;
    }
    :root[data-theme="light"] {
      color-scheme: light;
      --bg-base:#F3F4FB;
      --bg-primary:#FFFFFF;
      --bg-secondary:#F7F7FC;
      --bg-elevated:#EEF0FA;
      --bg-hover:#E7EAF8;
      --text-primary:#171A2B;
      --text-secondary:#5E6785;
      --text-tertiary:#7A84A3;
      --text-inverse:#F8FAFC;
      --border-subtle:rgba(76,88,125,.08);
      --border-default:rgba(76,88,125,.14);
      --border-hover:rgba(76,88,125,.22);
      --bg:var(--bg-base);
      --panel:var(--bg-primary);
      --panel-2:var(--bg-secondary);
      --panel-3:var(--bg-elevated);
      --muted:var(--text-secondary);
      --text:var(--text-primary);
      --accent:var(--accent-primary);
      --accent-soft:var(--accent-primary-light);
      --border:var(--border-default);
      --success:#0F9F6E;
      --warn:#D48500;
      --danger:#D63863;
      --user-bubble:#6366F1;
      --user-bubble-top:#8B5CF6;
      --user-bubble-mid:#7367F5;
      --user-bubble-bottom:#6366F1;
      --user-bubble-border:rgba(129,140,248,.3);
      --user-bubble-glow:rgba(99,102,241,.18);
      --assistant-bubble:#ffffff;
      --system-bubble-bg:color-mix(in srgb, var(--danger) 10%, var(--panel-2) 90%);
      --system-bubble-border:color-mix(in srgb, var(--danger) 42%, var(--border) 58%);
      --system-bubble-text:#8E2344;
      --system-code-header-text:#A73358;
      --system-success-bubble-bg:color-mix(in srgb, var(--success) 10%, var(--panel-2) 90%);
      --system-success-bubble-border:color-mix(in srgb, var(--success) 42%, var(--border) 58%);
      --system-success-bubble-text:#17684B;
      --system-success-code-header-text:#1A7A59;
      --input-bg:#ffffff;
      --history-grad-a:rgba(99,102,241,.09);
      --history-grad-b:rgba(255,255,255,.96);
      --history-grad-c:rgba(243,244,251,.98);
      --shell-bg:
        radial-gradient(circle at top left, rgba(99,102,241,.12), transparent 30%),
        radial-gradient(circle at top right, rgba(6,182,212,.08), transparent 24%),
        linear-gradient(180deg, #FBFBFF 0%, #F3F4FB 100%);
      --shadow:0 10px 30px rgba(55,68,106,.14);
      --message-shadow:0 4px 16px rgba(55,68,106,.12);
      --toolbar-shell-bg:linear-gradient(180deg, rgba(255,255,255,.98), rgba(238,240,250,.96));
      --toolbar-shell-shadow:0 10px 24px rgba(55,68,106,.1);
      --toolbar-button-text:var(--text);
      --toolbar-button-bg:linear-gradient(180deg, rgba(255,255,255,.98), rgba(238,240,250,.96));
      --toolbar-button-hover-bg:linear-gradient(180deg, rgba(255,255,255,1), rgba(231,234,248,1));
      --toolbar-icon-bg:linear-gradient(180deg, rgba(129,140,248,.18), rgba(99,102,241,.08));
      --toolbar-label-contrast:#171A2B;
    }
    :root[data-accent="blue"] {
      --accent:#6366F1;
      --accent-soft:#9AA3FF;
      --user-bubble:#6366F1;
      --user-bubble-top:#8B7DFF;
      --user-bubble-mid:#6F67F6;
      --user-bubble-bottom:#4F46E5;
      --user-bubble-border:rgba(129,140,248,.34);
      --user-bubble-glow:rgba(99,102,241,.28);
      --history-grad-a:rgba(99,102,241,.16);
    }
    :root[data-theme="dark"][data-accent="blue"] {
      --accent:#6366F1;
      --accent-soft:#AAB2FF;
      --user-bubble:#6366F1;
      --user-bubble-top:#9B8BFF;
      --user-bubble-mid:#7C6CFF;
      --user-bubble-bottom:#5E54F1;
      --user-bubble-border:rgba(146,154,255,.4);
      --user-bubble-glow:rgba(99,102,241,.34);
      --history-grad-a:rgba(99,102,241,.2);
    }
    :root[data-accent="white"] {
      --accent:#E5E7EB;
      --accent-soft:#F9FAFB;
      --user-bubble:#E5E7EB;
      --user-bubble-top:#FFFFFF;
      --user-bubble-mid:#F3F4F6;
      --user-bubble-bottom:#D1D5DB;
      --user-bubble-border:rgba(255,255,255,.44);
      --user-bubble-glow:rgba(255,255,255,.28);
      --history-grad-a:rgba(255,255,255,.18);
    }
    :root[data-theme="dark"][data-accent="white"] {
      --accent:#F3F4F6;
      --accent-soft:#FFFFFF;
      --user-bubble:#E5E7EB;
      --user-bubble-top:#FFFFFF;
      --user-bubble-mid:#F3F4F6;
      --user-bubble-bottom:#D1D5DB;
      --user-bubble-border:rgba(255,255,255,.5);
      --user-bubble-glow:rgba(255,255,255,.34);
      --history-grad-a:rgba(255,255,255,.2);
    }
    :root[data-accent="mint"] {
      --accent:#22D3EE;
      --accent-soft:#99F6E4;
      --user-bubble:#14B8A6;
      --user-bubble-top:#5EEAD4;
      --user-bubble-mid:#2DD4BF;
      --user-bubble-bottom:#0D9488;
      --user-bubble-border:rgba(153,246,228,.4);
      --user-bubble-glow:rgba(34,211,238,.24);
      --history-grad-a:rgba(45,212,191,.16);
    }
    :root[data-accent="sunset"] {
      --accent:#FB7185;
      --accent-soft:#FDBA74;
      --user-bubble:#F97316;
      --user-bubble-top:#FDA4AF;
      --user-bubble-mid:#FB7185;
      --user-bubble-bottom:#EA580C;
      --user-bubble-border:rgba(253,164,175,.4);
      --user-bubble-glow:rgba(251,113,133,.26);
      --history-grad-a:rgba(251,113,133,.16);
    }
    :root[data-accent="graphite"] {
      --accent:#94A3B8;
      --accent-soft:#CBD5E1;
      --user-bubble:#64748B;
      --user-bubble-top:#94A3B8;
      --user-bubble-mid:#64748B;
      --user-bubble-bottom:#475569;
      --user-bubble-border:rgba(203,213,225,.34);
      --user-bubble-glow:rgba(148,163,184,.22);
      --history-grad-a:rgba(148,163,184,.14);
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      font-family:Inter,ui-sans-serif,system-ui,sans-serif;
      background:var(--shell-bg);
      background-attachment:fixed;
      color:var(--text);
      transition:background var(--duration-normal) var(--ease-default), color var(--duration-fast) var(--ease-default);
    }
    body.is-resizing {
      cursor:col-resize;
      user-select:none;
    }
    .shell { display:grid; grid-template-columns: var(--sidebar-width) var(--resizer-width) minmax(0,1fr); min-height:100vh; height:100vh; }
    .shell.is-sidebar-collapsed {
      grid-template-columns:minmax(0,1fr);
    }
    .shell.is-sidebar-collapsed .sidebar-panel,
    .shell.is-sidebar-collapsed .panel-resizer {
      display:none;
    }
    .panel { padding:20px; min-height:0; border-right:1px solid color-mix(in srgb, var(--border) 82%, transparent); background:color-mix(in srgb, var(--panel) 90%, transparent); transition:background var(--duration-normal) var(--ease-default), border-color var(--duration-fast) var(--ease-default); }
    .panel:last-child { border-right:none; }
    h1,h2,h3 { margin:0 0 12px; }
    h1 { font-size:20px; }
    h2 { font-size:16px; }
    h3 { font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
    .stack { display:grid; gap:16px; }
    .card {
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 96%, transparent), color-mix(in srgb, var(--panel) 92%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--accent) 10%, transparent), transparent 52%);
      border:1px solid color-mix(in srgb, var(--border-subtle) 100%, transparent);
      border-radius:var(--radius-lg);
      padding:20px;
      display:grid;
      gap:10px;
      box-shadow:var(--shadow);
      transition:background var(--duration-normal) var(--ease-default), border-color var(--duration-fast) var(--ease-default), box-shadow var(--duration-normal) var(--ease-default), transform var(--duration-fast) var(--ease-default);
    }
    .card:hover {
      border-color:color-mix(in srgb, var(--accent) 32%, var(--border) 68%);
      background:
        var(--gradient-card-hover),
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 98%, transparent), color-mix(in srgb, var(--panel) 92%, transparent));
      box-shadow:var(--shadow), 0 0 30px color-mix(in srgb, var(--accent-primary-glow) 38%, transparent);
      transform:translateY(-2px);
    }
    label { display:grid; gap:6px; font-size:12px; color:var(--muted); }
    input, textarea, button, select {
      font:inherit; color:var(--text); background:var(--input-bg); border:1px solid var(--border); border-radius:var(--radius-md); padding:10px 12px; transition:background var(--duration-fast) var(--ease-default), border-color var(--duration-fast) var(--ease-default), color var(--duration-fast) var(--ease-default), box-shadow var(--duration-fast) var(--ease-default), transform var(--duration-fast) var(--ease-default);
    }
    textarea {
      height:72px;
      min-height:72px;
      max-height:72px;
      resize:none;
      overflow-y:auto;
      line-height:1.45;
    }
    textarea::placeholder {
      color:color-mix(in srgb, var(--muted) 82%, transparent);
    }
    button { cursor:pointer; background:var(--toolbar-button-bg); transition:background var(--duration-fast) var(--ease-default), transform var(--duration-fast) var(--ease-bounce), border-color var(--duration-fast) var(--ease-default), box-shadow var(--duration-fast) var(--ease-default), color var(--duration-fast) var(--ease-default); }
    button:hover { background:var(--toolbar-button-hover-bg); transform:translateY(-1px); box-shadow:0 0 20px color-mix(in srgb, var(--accent-primary-glow) 34%, transparent); }
    button:disabled { opacity:.58; cursor:not-allowed; transform:none; }
    button:disabled:hover { background:color-mix(in srgb, var(--panel-3) 82%, var(--accent) 18%); transform:none; }
    .button-row { display:flex; gap:8px; flex-wrap:wrap; }
    .pill { display:inline-flex; align-items:center; border-radius:999px; padding:3px 8px; font-size:12px; background:color-mix(in srgb, var(--panel-3) 84%, transparent); color:var(--muted); border:1px solid color-mix(in srgb, var(--border) 70%, transparent); }
    .pill.success { color:#c8ffd2; border:1px solid rgba(63,185,80,.45); }
    .pill.warn { color:#ffe7b3; border:1px solid rgba(210,153,34,.45); }
    .pill.danger { color:#ffd0cb; border:1px solid rgba(248,81,73,.45); }
    .muted { color:var(--muted); }
    .status-line { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    .panel-resizer {
      position:relative;
      cursor:col-resize;
      background:linear-gradient(180deg, transparent, color-mix(in srgb, var(--border) 68%, var(--accent) 18%), transparent);
      transition:background .18s ease;
    }
    .panel-resizer::before {
      content:"";
      position:absolute;
      top:50%;
      left:50%;
      width:4px;
      height:56px;
      transform:translate(-50%, -50%);
      border-radius:999px;
      background:color-mix(in srgb, var(--panel-3) 76%, var(--accent) 24%);
      box-shadow:0 0 0 1px color-mix(in srgb, var(--border) 72%, transparent);
    }
    .panel-resizer:hover,
    body.is-resizing .panel-resizer {
      background:linear-gradient(180deg, transparent, color-mix(in srgb, var(--accent) 42%, var(--border) 48%), transparent);
    }
    .chat-panel {
      display:grid;
      grid-template-rows:auto minmax(0,1fr) auto;
      min-height:0;
      gap:16px;
      background:color-mix(in srgb, var(--bg) 55%, transparent);
    }
    .chat-header {
      display:grid;
      gap:0;
    }
    .chat-header-top {
      display:grid;
      grid-template-columns:auto minmax(0, 1fr);
      align-items:center;
      gap:16px;
    }
    .chat-header-copy {
      display:flex;
      align-items:center;
      min-width:auto;
      flex:0 0 auto;
      max-width:none;
    }
    .chat-brand-lockup {
      gap:0;
      white-space:nowrap;
    }
    .chat-logo-toggle {
      padding:0;
      border:none;
      background:transparent;
      box-shadow:none;
      cursor:pointer;
    }
    .chat-logo-toggle:hover {
      background:transparent;
      transform:none;
    }
    .chat-logo-toggle:focus-visible {
      outline:none;
    }
    .chat-logo-toggle .brand-mark {
      transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease;
    }
    .chat-logo-toggle:hover .brand-mark,
    .chat-logo-toggle:focus-visible .brand-mark {
      transform:translateY(-1px);
      border-color:color-mix(in srgb, var(--accent) 34%, var(--border) 66%);
      box-shadow:0 14px 28px rgba(4,10,22,.16);
    }
    .chat-logo-toggle.is-sidebar-collapsed .brand-mark {
      background:color-mix(in srgb, var(--panel-3) 70%, var(--accent) 16%);
      border-color:color-mix(in srgb, var(--accent) 32%, var(--border) 68%);
    }
    .chat-brand-lockup .brand-mark {
      width:40px;
      height:40px;
      border-radius:12px;
      box-shadow:0 10px 22px rgba(4,10,22,.12);
    }
    .chat-brand-lockup .brand-mark svg {
      width:28px;
      height:28px;
    }
    .chat-header-actions {
      display:grid;
      grid-auto-flow:column;
      grid-auto-columns:max-content;
      align-items:center;
      justify-content:flex-end;
      gap:16px;
      margin-left:auto;
      min-width:0;
      width:100%;
      overflow-x:auto;
      overflow-y:hidden;
      scrollbar-width:thin;
      scrollbar-color:color-mix(in srgb, var(--accent) 24%, var(--border) 76%) transparent;
      padding-bottom:2px;
    }
    .chat-header-actions::-webkit-scrollbar {
      height:6px;
    }
    .chat-header-actions::-webkit-scrollbar-thumb {
      border-radius:999px;
      background:color-mix(in srgb, var(--accent) 24%, var(--border) 76%);
    }
    .chat-header-primary-actions,
    .chat-header-nav,
    .chat-header-settings {
      display:flex;
      align-items:center;
      justify-content:flex-end;
      gap:10px;
      flex-wrap:nowrap;
      min-width:max-content;
    }
    .chat-toolbar {
      display:flex;
      align-items:center;
      justify-content:flex-end;
      gap:8px;
      flex-wrap:nowrap;
    }
    .chat-toolbar-pill {
      width:auto;
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:8px 12px;
      border-radius:14px;
      border:1px solid color-mix(in srgb, var(--border) 74%, transparent);
      background:linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 92%, transparent), color-mix(in srgb, var(--panel) 92%, transparent));
      color:var(--text);
      box-shadow:none;
      font-weight:600;
      font-size:13px;
      white-space:nowrap;
      flex:0 0 auto;
      min-width:0;
    }
    .toolbar-tooltip-host {
      position:relative;
    }
    .toolbar-tooltip-overlay {
      position:fixed;
      top:0;
      left:0;
      max-width:min(240px, calc(100vw - 24px));
      padding:8px 12px;
      border-radius:12px;
      background:color-mix(in srgb, var(--panel) 92%, var(--bg) 8%);
      border:1px solid color-mix(in srgb, var(--border) 78%, transparent);
      box-shadow:0 16px 30px rgba(4,10,22,.18);
      color:var(--text);
      font-size:12px;
      font-weight:600;
      line-height:1.35;
      white-space:nowrap;
      pointer-events:none;
      opacity:0;
      z-index:260;
      transition:opacity .14s ease, transform .14s ease;
      transform:translateY(6px);
    }
    .toolbar-tooltip-overlay.is-visible {
      opacity:1;
      transform:translateY(0);
    }
    .toolbar-text {
      min-width:0;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .chat-toolbar-pill:hover {
      background:linear-gradient(180deg, color-mix(in srgb, var(--panel-3) 82%, var(--accent) 18%), color-mix(in srgb, var(--panel) 96%, transparent));
    }
    .chat-toolbar-button {
      width:auto;
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:8px 12px;
      border-radius:14px;
      border:1px solid color-mix(in srgb, var(--border) 68%, transparent);
      background:var(--toolbar-button-bg);
      color:var(--text);
      box-shadow:0 2px 8px rgba(0,0,0,.14);
      font-weight:600;
      font-size:13px;
      white-space:nowrap;
      flex:0 0 auto;
    }
    .chat-toolbar-button:hover {
      background:var(--toolbar-button-hover-bg);
      border-color:color-mix(in srgb, var(--accent) 24%, var(--border) 76%);
    }
    .chat-toolbar-button.primary {
      border-color:color-mix(in srgb, var(--accent) 34%, var(--border) 66%);
      background:var(--gradient-brand);
      box-shadow:0 0 20px color-mix(in srgb, var(--accent-primary-glow) 60%, transparent);
      color:white;
    }
    .chat-toolbar-button.primary:hover {
      background:linear-gradient(135deg, #7377F8 0%, #9567F8 100%);
      box-shadow:0 0 30px color-mix(in srgb, var(--accent-primary-glow) 72%, transparent);
    }
    .chat-header-actions.is-compact [data-compact-button="true"] {
      width:42px;
      min-width:42px;
      height:42px;
      padding:0;
      gap:0;
      justify-content:center;
      border-radius:14px;
    }
    .chat-header-actions.is-compact [data-compact-button="true"] .toolbar-text {
      display:none;
    }
    .chat-header-actions.is-compact #focus-branch-tree #active-thread-pill {
      display:none;
    }
    .chat-header-actions.is-compact .chat-toolbar-pill[data-compact-button="true"] {
      box-shadow:0 10px 22px rgba(4,10,22,.1);
    }
    .toolbar-icon {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:18px;
      height:18px;
      color:color-mix(in srgb, var(--text) 74%, var(--muted) 26%);
      line-height:1;
      flex-shrink:0;
    }
    .toolbar-icon svg {
      display:block;
      width:18px;
      height:18px;
      overflow:visible;
    }
    .chat-header-actions.is-compact [data-compact-button="true"] .toolbar-icon {
      color:color-mix(in srgb, var(--text) 82%, var(--muted) 18%);
    }
    #focus-branch-tree .toolbar-icon,
    #composer-create-branch .toolbar-icon,
    #back-to-main .toolbar-icon,
    #back-to-parent .toolbar-icon,
    #prepare-merge .toolbar-icon {
      width:20px;
      height:20px;
    }
    #focus-branch-tree .toolbar-icon svg,
    #composer-create-branch .toolbar-icon svg {
      width:20px;
      height:20px;
    }
    .chat-transcript {
      min-height:0;
      height:100%;
      padding:0;
      overflow:hidden;
      display:flex;
    }
    .chat-history {
      min-height:0;
      flex:1 1 auto;
      overflow:auto;
      padding:20px;
      display:flex;
      flex-direction:column;
      gap:14px;
      justify-content:flex-start;
      background:
        radial-gradient(circle at top right, var(--history-grad-a), transparent 30%),
        linear-gradient(180deg, var(--history-grad-b), var(--history-grad-c));
    }
    .chat-empty {
      margin:auto;
      max-width:520px;
      text-align:center;
      color:var(--muted);
      border:1px dashed var(--border);
      border-radius:18px;
      padding:26px 20px;
      line-height:1.6;
      background:color-mix(in srgb, var(--panel) 45%, transparent);
    }
    .message-row {
      display:grid;
      gap:8px;
    }
    .message-row.user {
      justify-items:end;
    }
    .message-row.assistant,
    .message-row.system,
    .message-row.activity {
      justify-items:start;
    }
    .message-meta {
      font-size:11px;
      color:var(--muted);
      text-transform:uppercase;
      letter-spacing:.08em;
    }
    .message-bubble {
      max-width:min(720px, 88%);
      padding:14px 16px;
      border-radius:20px;
      line-height:1.55;
      word-break:break-word;
      border:1px solid var(--border);
      box-shadow:var(--message-shadow);
    }
    .message-bubble > :first-child {
      margin-top:0;
    }
    .message-bubble > :last-child {
      margin-bottom:0;
    }
    .message-bubble p {
      margin:0 0 12px;
      white-space:pre-wrap;
    }
    .message-bubble h1,
    .message-bubble h2,
    .message-bubble h3,
    .message-bubble h4,
    .message-bubble h5,
    .message-bubble h6 {
      margin:0 0 12px;
      line-height:1.3;
      letter-spacing:-.02em;
    }
    .message-bubble h1 {
      font-size:1.5rem;
    }
    .message-bubble h2 {
      font-size:1.32rem;
    }
    .message-bubble h3 {
      font-size:1.16rem;
    }
    .message-bubble h4,
    .message-bubble h5,
    .message-bubble h6 {
      font-size:1rem;
    }
    .message-bubble ul,
    .message-bubble ol {
      margin:0 0 12px 1.35em;
      padding:0;
    }
    .message-bubble li + li {
      margin-top:6px;
    }
    .message-bubble blockquote {
      margin:0 0 12px;
      padding:0 0 0 14px;
      border-left:3px solid color-mix(in srgb, var(--accent) 34%, var(--border) 66%);
      color:color-mix(in srgb, var(--text) 84%, var(--muted) 16%);
    }
    .message-bubble hr {
      margin:14px 0;
      border:none;
      border-top:1px solid color-mix(in srgb, var(--border) 82%, transparent);
    }
    .message-bubble a {
      color:var(--accent);
      text-decoration:underline;
      text-decoration-color:color-mix(in srgb, var(--accent) 58%, transparent);
      text-underline-offset:2px;
    }
    .message-bubble a:hover {
      text-decoration-color:currentColor;
    }
    .agent-run-bubble {
      max-width:min(560px, 80%);
      display:grid;
      gap:12px;
      background:linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 92%, transparent), color-mix(in srgb, var(--panel) 88%, transparent));
      border-bottom-left-radius:8px;
    }
    .agent-run-bubble.warn {
      border-color:color-mix(in srgb, var(--warn) 28%, var(--border) 72%);
    }
    .agent-run-bubble.success {
      border-color:color-mix(in srgb, var(--success) 28%, var(--border) 72%);
    }
    .agent-run-bubble.danger {
      border-color:color-mix(in srgb, var(--danger) 34%, var(--border) 66%);
    }
    .agent-run-head {
      display:flex;
      align-items:flex-start;
      gap:10px;
    }
    .agent-run-pulse {
      width:12px;
      height:12px;
      margin-top:5px;
      border-radius:999px;
      background:var(--warn);
      box-shadow:0 0 0 7px color-mix(in srgb, var(--warn) 14%, transparent);
      animation:pulse 1.8s ease-in-out infinite;
      flex-shrink:0;
    }
    .agent-run-bubble.success .agent-run-pulse {
      background:var(--success);
      box-shadow:0 0 0 7px color-mix(in srgb, var(--success) 14%, transparent);
    }
    .agent-run-bubble.danger .agent-run-pulse {
      background:var(--danger);
      box-shadow:0 0 0 7px color-mix(in srgb, var(--danger) 14%, transparent);
    }
    .agent-run-copy {
      min-width:0;
      display:grid;
      gap:3px;
    }
    .agent-run-title {
      font-size:15px;
      font-weight:700;
      color:var(--text);
    }
    .agent-run-detail {
      font-size:12px;
      line-height:1.5;
      color:var(--muted);
    }
    .agent-run-steps {
      display:grid;
      gap:8px;
    }
    .agent-run-step {
      display:flex;
      align-items:center;
      gap:8px;
      padding:8px 10px;
      border-radius:12px;
      border:1px solid color-mix(in srgb, var(--border) 70%, transparent);
      background:color-mix(in srgb, var(--panel-3) 34%, transparent);
      font-size:13px;
      color:var(--text);
    }
    .agent-run-step-dot {
      width:8px;
      height:8px;
      border-radius:999px;
      background:color-mix(in srgb, var(--muted) 74%, transparent);
      flex-shrink:0;
    }
    .agent-run-step.success .agent-run-step-dot {
      background:var(--success);
    }
    .agent-run-step.warn .agent-run-step-dot {
      background:var(--warn);
    }
    .agent-run-step.danger .agent-run-step-dot {
      background:var(--danger);
    }
    .message-inline-code {
      display:inline-block;
      padding:1px 6px;
      border-radius:8px;
      font-family:"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, Monaco, Consolas, monospace;
      font-size:.92em;
      background:color-mix(in srgb, var(--panel-3) 58%, transparent);
      border:1px solid color-mix(in srgb, var(--border) 78%, transparent);
    }
    .message-code-block {
      margin:0 0 12px;
      border-radius:16px;
      overflow:hidden;
      border:1px solid color-mix(in srgb, var(--border) 78%, transparent);
      background:color-mix(in srgb, var(--panel-3) 56%, transparent);
    }
    .message-code-header {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      padding:8px 12px;
      font-size:11px;
      letter-spacing:.08em;
      text-transform:uppercase;
      color:var(--muted);
      border-bottom:1px solid color-mix(in srgb, var(--border) 72%, transparent);
      background:color-mix(in srgb, var(--panel) 50%, transparent);
    }
    .message-code-label {
      min-width:0;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .code-copy-button {
      padding:5px 10px;
      border-radius:999px;
      border:1px solid color-mix(in srgb, var(--border) 78%, transparent);
      background:color-mix(in srgb, var(--panel-2) 82%, transparent);
      color:var(--muted);
      box-shadow:none;
      font-size:11px;
      font-weight:700;
      letter-spacing:.04em;
      text-transform:uppercase;
      flex-shrink:0;
    }
    .code-copy-button:hover {
      background:color-mix(in srgb, var(--panel-3) 72%, transparent);
      border-color:color-mix(in srgb, var(--accent) 28%, var(--border) 72%);
      transform:none;
    }
    .code-copy-button.is-copied {
      color:var(--success);
      border-color:color-mix(in srgb, var(--success) 40%, var(--border) 60%);
    }
    .message-code-block pre {
      margin:0;
      padding:14px 16px;
      overflow:auto;
      font-family:"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, Monaco, Consolas, monospace;
      font-size:13px;
      line-height:1.65;
      white-space:pre;
      color:var(--text);
    }
    .message-code-block code {
      font:inherit;
      color:inherit;
    }
    .message-row.user .message-bubble {
      position:relative;
      color:#f8fbff;
      background:
        radial-gradient(circle at top left, rgba(255,255,255,.28), transparent 34%),
        linear-gradient(135deg, var(--user-bubble-top) 0%, var(--user-bubble-mid) 56%, var(--user-bubble-bottom) 100%);
      border-color:var(--user-bubble-border);
      border-radius:22px 22px 8px 22px;
      box-shadow:
        0 12px 24px color-mix(in srgb, var(--user-bubble-glow) 82%, transparent),
        inset 0 1px 0 rgba(255,255,255,.18),
        inset 0 -1px 0 rgba(11,22,52,.12);
    }
    .message-row.user .message-bubble::before {
      content:"";
      position:absolute;
      inset:0;
      border-radius:inherit;
      background:linear-gradient(180deg, rgba(255,255,255,.06), transparent 42%);
      pointer-events:none;
    }
    .message-row.user .message-meta {
      color:color-mix(in srgb, var(--accent) 28%, var(--muted) 72%);
      letter-spacing:.11em;
    }
    .message-row.assistant .message-bubble {
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--assistant-bubble) 98%, transparent), color-mix(in srgb, var(--panel) 94%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--accent-cyan) 8%, transparent), transparent 44%);
      border-color:color-mix(in srgb, var(--border-subtle) 100%, transparent);
      border-bottom-left-radius:8px;
    }
    :root[data-theme="light"] .message-row.assistant .message-bubble {
      color:var(--text);
    }
    .message-row.system .message-bubble {
      background:var(--system-bubble-bg);
      border-color:var(--system-bubble-border);
      color:var(--system-bubble-text);
      box-shadow:0 10px 24px color-mix(in srgb, var(--danger) 12%, transparent);
    }
    .message-row.system .message-inline-code,
    .message-row.system .message-code-block {
      background:color-mix(in srgb, var(--panel) 78%, var(--danger) 10%);
      border-color:color-mix(in srgb, var(--danger) 26%, var(--border) 74%);
    }
    .message-row.system .message-code-header {
      color:var(--system-code-header-text);
      border-bottom-color:color-mix(in srgb, var(--danger) 22%, var(--border) 78%);
      background:color-mix(in srgb, var(--panel) 76%, var(--danger) 8%);
    }
    .message-row.system.success .message-bubble {
      background:var(--system-success-bubble-bg);
      border-color:var(--system-success-bubble-border);
      color:var(--system-success-bubble-text);
      box-shadow:0 10px 24px color-mix(in srgb, var(--success) 14%, transparent);
    }
    .message-row.system.success .message-inline-code,
    .message-row.system.success .message-code-block {
      background:color-mix(in srgb, var(--panel) 78%, var(--success) 10%);
      border-color:color-mix(in srgb, var(--success) 24%, var(--border) 76%);
    }
    .message-row.system.success .message-code-header {
      color:var(--system-success-code-header-text);
      border-bottom-color:color-mix(in srgb, var(--success) 20%, var(--border) 80%);
      background:color-mix(in srgb, var(--panel) 76%, var(--success) 8%);
    }
    .message-row.user .message-inline-code,
    .message-row.user .message-code-block {
      background:rgba(9, 20, 43, .28);
      border-color:rgba(255,255,255,.18);
    }
    .message-row.user .message-code-header {
      color:rgba(255,255,255,.78);
      border-bottom-color:rgba(255,255,255,.12);
      background:rgba(9, 20, 43, .22);
    }
    .message-row.user .code-copy-button {
      color:rgba(255,255,255,.86);
      border-color:rgba(255,255,255,.16);
      background:rgba(255,255,255,.08);
    }
    .message-row.user .code-copy-button:hover {
      background:rgba(255,255,255,.14);
      border-color:rgba(255,255,255,.24);
    }
    .message-row.user .code-copy-button.is-copied {
      color:#c8ffd2;
      border-color:rgba(200,255,210,.34);
    }
    .message-row.user .message-code-block pre,
    .message-row.user .message-inline-code {
      color:#f8fbff;
    }
    :root[data-accent="white"] .message-row.user .message-bubble {
      color:#0F172A;
      border-color:rgba(148,163,184,.38);
      box-shadow:
        0 12px 24px rgba(148,163,184,.22),
        inset 0 1px 0 rgba(255,255,255,.36),
        inset 0 -1px 0 rgba(148,163,184,.16);
    }
    :root[data-accent="white"] .message-row.user .message-inline-code,
    :root[data-accent="white"] .message-row.user .message-code-block {
      background:rgba(148,163,184,.16);
      border-color:rgba(148,163,184,.36);
      color:#0F172A;
    }
    :root[data-accent="white"] .message-row.user .message-code-header {
      color:#334155;
      border-bottom-color:rgba(148,163,184,.36);
      background:rgba(248,250,252,.72);
    }
    :root[data-accent="white"] .message-row.user .code-copy-button {
      color:#334155;
      border-color:rgba(148,163,184,.38);
      background:rgba(255,255,255,.78);
    }
    :root[data-accent="white"] .message-row.user .message-code-block pre,
    :root[data-accent="white"] .message-row.user .message-inline-code {
      color:#0F172A;
    }
    .composer {
      display:grid;
      gap:6px;
      padding:10px;
      border-radius:24px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 98%, transparent), color-mix(in srgb, var(--panel) 96%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--accent-violet) 14%, transparent), transparent 44%);
      border-color:color-mix(in srgb, var(--accent) 18%, var(--border) 82%);
      box-shadow:var(--shadow), inset 0 1px 0 rgba(255,255,255,.04);
    }
    .composer-input-shell {
      display:grid;
      grid-template-columns:minmax(0, 1fr) clamp(178px, 19vw, 192px);
      align-items:stretch;
      gap:8px;
      padding:10px 12px;
      border-radius:18px;
      border:1px solid color-mix(in srgb, var(--accent) 18%, var(--border) 82%);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel) 86%, transparent), color-mix(in srgb, var(--panel-2) 96%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--accent) 12%, transparent), transparent 56%);
      box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
      transition:border-color var(--duration-fast) var(--ease-default), box-shadow var(--duration-fast) var(--ease-default), background var(--duration-fast) var(--ease-default);
    }
    .composer-input-shell:focus-within {
      border-color:color-mix(in srgb, var(--accent) 54%, var(--border) 46%);
      box-shadow:0 0 0 3px color-mix(in srgb, var(--accent-primary-glow) 36%, transparent), 0 0 20px color-mix(in srgb, var(--accent-primary-glow) 65%, transparent), inset 0 1px 0 rgba(255,255,255,.05);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel) 82%, transparent), color-mix(in srgb, var(--panel-2) 98%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--accent) 18%, transparent), transparent 54%);
    }
    .composer-input-row {
      display:flex;
      align-items:stretch;
      min-height:34px;
    }
    .composer-footer-row {
      display:flex;
      align-items:center;
      justify-content:flex-end;
      gap:6px;
      min-height:34px;
      width:100%;
    }
    .composer-actions-row {
      display:flex;
      align-items:center;
      justify-content:flex-end;
      gap:6px;
      order:2;
    }
    .composer-model-row {
      display:flex;
      align-items:stretch;
      justify-content:flex-end;
      gap:6px;
      min-width:0;
      flex:1 1 auto;
      order:1;
    }
    .composer-model-trigger {
      min-height:34px;
      width:100%;
      max-width:none;
      padding:0 10px 0 8px;
      border-radius:999px;
      border:1px solid color-mix(in srgb, var(--accent) 18%, var(--border) 82%);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 96%, var(--accent) 4%), color-mix(in srgb, var(--panel) 94%, var(--accent) 6%));
      box-shadow:0 6px 16px rgba(0,0,0,.2);
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:8px;
      text-align:left;
    }
    .composer-model-trigger-copy {
      display:flex;
      min-width:0;
      flex:1 1 auto;
      align-items:center;
      gap:5px;
    }
    .composer-model-trigger-label {
      min-width:0;
      flex:1 1 auto;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
      font-size:10px;
      color:var(--text);
    }
    .composer-model-trigger-provider {
      display:none;
    }
    .composer-model-trigger-icon {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:16px;
      height:16px;
      color:var(--muted);
      flex:0 0 auto;
      transition:transform .18s ease;
    }
    .composer-model-trigger[aria-expanded="true"] .composer-model-trigger-icon {
      transform:rotate(180deg);
    }
    .composer-model-anchor {
      position:relative;
      flex:1 1 auto;
      width:100%;
      max-width:none;
      margin-left:0;
    }
    .composer-model-panel {
      position:absolute;
      right:0;
      bottom:calc(100% + 10px);
      width:min(360px, calc(100vw - 48px));
      max-height:360px;
      overflow:hidden;
      border-radius:20px;
      border:1px solid color-mix(in srgb, var(--accent) 16%, var(--border) 84%);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 96%, var(--accent) 4%), color-mix(in srgb, var(--panel) 98%, transparent));
      box-shadow:0 26px 56px rgba(4,10,22,.28);
      backdrop-filter:blur(14px);
      z-index:25;
    }
    .composer-model-panel-head {
      padding:10px;
      border-bottom:1px solid color-mix(in srgb, var(--border) 86%, transparent);
      display:grid;
      gap:8px;
    }
    .composer-model-panel-title {
      display:flex;
      align-items:center;
      gap:8px;
      min-width:0;
      font-size:12px;
      font-weight:600;
      color:var(--text);
    }
    .composer-model-panel-title small {
      font-size:10px;
      font-weight:500;
      color:var(--muted);
    }
    .composer-model-search-shell {
      display:flex;
      align-items:center;
      gap:8px;
      width:100%;
      min-height:34px;
      border-radius:12px;
      border:1px solid color-mix(in srgb, var(--accent) 10%, var(--border) 90%);
      background:color-mix(in srgb, var(--panel) 72%, transparent);
      box-shadow:none;
      padding:0 10px;
    }
    .composer-model-search-icon {
      flex:0 0 auto;
      width:14px;
      height:14px;
      color:var(--muted);
    }
    .composer-model-search {
      width:100%;
      min-height:34px;
      padding:0;
      border:none;
      background:transparent;
      box-shadow:none;
      border-radius:0;
    }
    .composer-model-list {
      max-height:282px;
      overflow:auto;
      padding:6px;
      display:grid;
      gap:8px;
    }
    .composer-model-group {
      display:grid;
      gap:4px;
    }
    .composer-model-group-label {
      padding:2px 8px 4px;
      font-size:10px;
      letter-spacing:.08em;
      text-transform:uppercase;
      color:var(--muted);
    }
    .composer-model-option {
      width:100%;
      display:flex;
      align-items:center;
      gap:12px;
      justify-content:space-between;
      padding:8px 10px;
      border-radius:12px;
      border:1px solid transparent;
      background:transparent;
      box-shadow:none;
      text-align:left;
    }
    .composer-model-option:hover {
      background:color-mix(in srgb, var(--panel-3) 78%, var(--accent) 22%);
      border-color:color-mix(in srgb, var(--accent) 16%, transparent);
      transform:none;
    }
    .composer-model-option.is-selected {
      background:color-mix(in srgb, var(--accent) 14%, var(--panel-3) 86%);
      border-color:color-mix(in srgb, var(--accent) 28%, transparent);
    }
    .composer-model-option-copy {
      min-width:0;
      display:flex;
      flex:1 1 auto;
      flex-direction:column;
      gap:2px;
    }
    .composer-model-option-leading {
      min-width:0;
      display:flex;
      align-items:center;
      gap:10px;
      flex:1 1 auto;
    }
    .composer-model-option-label {
      min-width:0;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
      font-size:11px;
      color:var(--text);
    }
    .composer-model-option-meta {
      min-width:0;
      font-size:10px;
      color:var(--muted);
      line-height:1.35;
    }
    .composer-model-check {
      flex:0 0 auto;
      width:16px;
      text-align:center;
      color:var(--accent);
      font-size:12px;
      visibility:hidden;
    }
    .composer-model-option.is-selected .composer-model-check {
      visibility:visible;
    }
    .composer-model-empty {
      padding:12px 10px;
      font-size:11px;
      color:var(--muted);
    }
    .composer-model-logo-shell {
      position:relative;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:16px;
      height:16px;
      border-radius:999px;
      background:color-mix(in srgb, var(--panel-3) 82%, var(--accent) 18%);
      border:1px solid color-mix(in srgb, var(--accent) 18%, transparent);
      overflow:hidden;
      flex:0 0 auto;
    }
    .composer-model-logo {
      width:11px;
      height:11px;
      object-fit:contain;
      display:block;
    }
    .composer-model-logo-fallback {
      position:absolute;
      inset:0;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:8px;
      font-weight:700;
      color:var(--text);
    }
    .composer-input-shell textarea {
      min-height:34px;
      max-height:136px;
      height:34px;
      display:block;
      width:100%;
      padding:6px 0;
      border:none;
      border-radius:0;
      background:transparent;
      box-shadow:none;
      overflow-y:hidden;
      resize:none;
      line-height:1.4;
      font-size:12px;
    }
    .composer-input-shell textarea:focus {
      outline:none;
    }
    .composer-input-shell textarea::placeholder {
      color:color-mix(in srgb, var(--muted) 72%, transparent);
    }
    .composer-inline-actions {
      display:grid;
      grid-template-columns:34px 34px;
      align-items:center;
      gap:6px;
      width:auto;
      flex:0 0 auto;
      justify-content:end;
    }
    .composer-model-option-trailing {
      display:flex;
      align-items:center;
      gap:8px;
      flex:0 0 auto;
    }
    .composer-model-thinking-toggle {
      display:flex;
      align-items:center;
      gap:4px;
    }
    .composer-thinking-button {
      min-height:26px;
      padding:0 9px;
      border-radius:999px;
      border:1px solid transparent;
      background:transparent;
      color:var(--muted);
      box-shadow:none;
      font-size:10px;
      font-weight:600;
    }
    .composer-thinking-button:hover {
      transform:none;
      background:color-mix(in srgb, var(--panel-3) 72%, transparent);
    }
    .composer-thinking-button.is-active {
      background:linear-gradient(180deg, color-mix(in srgb, var(--accent) 22%, white 4%), color-mix(in srgb, var(--accent) 16%, var(--panel-3) 84%));
      border-color:color-mix(in srgb, var(--accent) 32%, transparent);
      color:var(--text);
    }
    .composer-thinking-button:disabled,
    .composer-thinking-button:disabled:hover {
      background:transparent;
      color:color-mix(in srgb, var(--muted) 88%, transparent);
      transform:none;
    }
    .composer-action-button {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      gap:8px;
      flex:0 0 auto;
      box-shadow:none;
    }
    .composer-action-icon {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      width:18px;
      height:18px;
      flex:0 0 auto;
      color:currentColor;
    }
    .composer-action-icon svg {
      display:block;
      width:18px;
      height:18px;
      overflow:visible;
    }
    #open-stream {
      width:34px;
      height:34px;
      min-height:34px;
      padding:0;
      border-radius:999px;
      background:var(--gradient-brand);
      border-color:color-mix(in srgb, var(--accent) 52%, var(--border) 48%);
      color:white;
      box-shadow:0 0 20px color-mix(in srgb, var(--accent-primary-glow) 60%, transparent);
    }
    #open-stream .composer-action-icon {
      width:16px;
      height:16px;
      color:white;
    }
    #open-stream .composer-action-icon svg {
      width:16px;
      height:16px;
    }
    #open-stream:hover {
      background:linear-gradient(135deg, #7377F8 0%, #9567F8 100%);
      border-color:color-mix(in srgb, var(--accent) 60%, var(--border) 40%);
      box-shadow:0 0 30px color-mix(in srgb, var(--accent-primary-glow) 72%, transparent);
    }
    #clear-stream {
      min-height:34px;
      height:34px;
      width:34px;
      padding:0;
      border-radius:999px;
      background:color-mix(in srgb, var(--panel-3) 34%, transparent);
      border-color:color-mix(in srgb, var(--border) 68%, transparent);
      color:color-mix(in srgb, var(--muted) 88%, var(--text) 12%);
      box-shadow:none;
    }
    #clear-stream .composer-action-icon {
      color:color-mix(in srgb, var(--text) 72%, var(--muted) 28%);
    }
    #clear-stream:hover {
      background:color-mix(in srgb, var(--panel-3) 42%, transparent);
      border-color:color-mix(in srgb, var(--border) 64%, transparent);
      color:var(--text);
    }
    #clear-stream:hover .composer-action-icon {
      color:var(--text);
    }
    .thread-nav {
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      align-items:center;
      padding:0;
    }
    .thread-nav[hidden] { display:none; }
    .thread-nav-button { padding:10px 14px; }
    .header-picker {
      display:inline-flex;
      align-items:center;
      gap:8px;
      flex-wrap:nowrap;
      color:var(--muted);
      font-size:12px;
      white-space:nowrap;
      flex:0 0 auto;
    }
    .header-picker-text {
      white-space:nowrap;
      flex:0 0 auto;
    }
    .header-picker select {
      min-width:132px;
      padding:8px 12px;
      border-radius:999px;
      white-space:nowrap;
      flex:0 0 auto;
    }
    #active-thread-pill {
      display:inline-block;
      min-width:0;
      max-width:min(34vw, 420px);
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
      vertical-align:bottom;
    }
    .branch-tree-panel.flash-focus {
      animation:branchPanelFlash .7s ease;
    }
    @keyframes branchPanelFlash {
      0% {
        box-shadow:0 0 0 0 color-mix(in srgb, var(--accent) 0%, transparent), var(--shadow);
      }
      40% {
        box-shadow:0 0 0 4px color-mix(in srgb, var(--accent) 22%, transparent), var(--shadow);
      }
      100% {
        box-shadow:var(--shadow);
      }
    }
    .sidebar-panel {
      display:grid;
      grid-template-rows:auto auto minmax(0,1fr);
      gap:16px;
      min-height:100vh;
      height:100vh;
      overflow:hidden;
      align-content:start;
    }
    .sidebar-copy {
      display:grid;
      gap:14px;
      align-content:start;
      justify-items:start;
    }
    .sidebar-brand-stack {
      display:grid;
      gap:12px;
      justify-items:start;
      width:100%;
    }
    .brand-lockup {
      display:flex;
      align-items:center;
      gap:12px;
      width:100%;
      max-width:100%;
      min-width:0;
    }
    .sidebar-brand-stack .brand-lockup {
      width:100%;
      display:flex;
      align-items:center;
      gap:12px;
    }
    .brand-mark {
      width:46px;
      height:46px;
      flex-shrink:0;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      border-radius:14px;
      background:color-mix(in srgb, var(--panel-2) 82%, transparent);
      border:1px solid color-mix(in srgb, var(--border) 74%, transparent);
      box-shadow:0 12px 24px rgba(4,10,22,.14);
    }
    .brand-mark svg {
      width:32px;
      height:32px;
      overflow:visible;
    }
    .brand-wordmark {
      font-size:18px;
      font-weight:700;
      letter-spacing:-.02em;
      color:var(--text);
      line-height:1.05;
      white-space:nowrap;
    }
    .brand-copy {
      min-width:0;
      display:flex;
      align-items:center;
      gap:12px;
      flex:1 1 auto;
      min-height:46px;
    }
    .brand-meta {
      display:flex;
      align-items:center;
      gap:10px;
      flex-wrap:nowrap;
      min-width:0;
      flex:1 1 auto;
    }
    .sidebar-settings {
      display:flex;
      align-items:center;
      gap:8px;
      width:100%;
      min-width:0;
      flex-wrap:nowrap;
      overflow-x:auto;
      overflow-y:hidden;
      scrollbar-width:none;
    }
    .sidebar-settings::-webkit-scrollbar {
      display:none;
    }
    .sidebar-settings-toggle {
      align-self:center;
      flex:0 0 auto;
      width:40px;
      min-width:40px;
      min-height:40px;
    }
    .sidebar-settings-tree-pill {
      align-self:center;
      flex:0 0 auto;
      height:40px;
      min-height:40px;
      padding:0 10px 0 12px;
    }
    .sidebar-preferences-row {
      display:flex;
      align-items:center;
      gap:8px;
      width:auto;
      min-width:max-content;
      flex:0 0 auto;
      padding:4px;
      border-radius:999px;
      background:var(--toolbar-shell-bg);
      border:1px solid var(--toolbar-shell-border);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,.04),
        var(--toolbar-shell-shadow);
    }
    .sidebar-preference-toggle {
      width:auto;
      min-width:96px;
      min-height:40px;
      padding:0 14px 0 10px;
      border-radius:999px;
      border:1px solid color-mix(in srgb, var(--preference-accent) 18%, var(--border) 82%);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 94%, white 6%), color-mix(in srgb, var(--panel) 94%, white 2%)),
        radial-gradient(circle at top left, color-mix(in srgb, var(--preference-accent, var(--accent)) 14%, transparent), transparent 52%);
      display:inline-flex;
      align-items:center;
      justify-content:center;
      gap:10px;
      text-align:center;
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,.06),
        0 8px 16px rgba(0,0,0,.18);
      --preference-accent:var(--accent);
      --preference-accent-soft:var(--accent-soft);
      transition:
        border-color .18s ease,
        background .18s ease,
        box-shadow .18s ease,
        color .18s ease;
    }
    .sidebar-preference-toggle:hover {
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 90%, white 4%), color-mix(in srgb, var(--panel-3) 90%, var(--preference-accent) 10%)),
        radial-gradient(circle at top left, color-mix(in srgb, var(--preference-accent) 20%, transparent), transparent 52%);
      border-color:color-mix(in srgb, var(--preference-accent) 24%, var(--border) 76%);
      box-shadow:0 12px 26px color-mix(in srgb, var(--preference-accent) 16%, transparent);
    }
    .sidebar-preference-toggle:focus-visible {
      outline:none;
      border-color:color-mix(in srgb, var(--preference-accent) 34%, var(--border) 66%);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--preference-accent) 16%, transparent), 0 12px 26px rgba(4,10,22,.12);
    }
    .sidebar-preference-icon {
      width:28px;
      height:28px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      color:color-mix(in srgb, var(--toolbar-label-contrast) 92%, var(--preference-accent) 8%);
      border-radius:999px;
      background:linear-gradient(180deg, color-mix(in srgb, white 74%, var(--preference-accent) 26%), color-mix(in srgb, var(--panel-2) 88%, var(--preference-accent) 12%));
      border:1px solid color-mix(in srgb, var(--preference-accent) 28%, var(--border) 72%);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,.18),
        0 2px 6px color-mix(in srgb, var(--preference-accent) 12%, transparent);
      flex:0 0 auto;
      transition:color .18s ease, transform .18s ease;
    }
    .sidebar-preference-icon svg {
      width:20px;
      height:20px;
      display:block;
      overflow:visible;
    }
    .sidebar-preference-toggle:hover .sidebar-preference-icon,
    .sidebar-preference-toggle:focus-visible .sidebar-preference-icon {
      color:var(--toolbar-label-contrast);
      transform:scale(1.05);
    }
    .sidebar-picker-text {
      position:absolute;
      width:1px;
      height:1px;
      margin:-1px;
      padding:0;
      border:0;
      overflow:hidden;
      clip:rect(0 0 0 0);
      clip-path:inset(50%);
      white-space:nowrap;
      pointer-events:none;
    }
    .sidebar-preference-value {
      display:block;
      min-width:0;
      line-height:1.2;
      font-size:13px;
      font-weight:800;
      color:var(--toolbar-label-contrast);
      text-shadow:0 1px 0 rgba(255,255,255,.08);
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
    }
    .sidebar-preference-input {
      position:absolute;
      width:1px;
      height:1px;
      margin:-1px;
      padding:0;
      border:0;
      overflow:hidden;
      clip:rect(0 0 0 0);
      clip-path:inset(50%);
      white-space:nowrap;
      pointer-events:none;
    }
    .sidebar-preference-toggle[data-preference-group="language"] {
      --preference-accent:#6c8dff;
      --preference-accent-soft:#b4c6ff;
    }
    .sidebar-preference-toggle[data-preference-group="language"][data-preference-value="zh"] {
      --preference-accent:#3b82f6;
      --preference-accent-soft:#8dc2ff;
    }
    .sidebar-preference-toggle[data-preference-group="theme"][data-preference-value="system"] {
      --preference-accent:#7c8cf8;
      --preference-accent-soft:#c0c7ff;
    }
    .sidebar-preference-toggle[data-preference-group="theme"][data-preference-value="light"] {
      --preference-accent:#6366F1;
      --preference-accent-soft:#B9BFFF;
    }
    .sidebar-preference-toggle[data-preference-group="theme"][data-preference-value="dark"] {
      --preference-accent:#818CF8;
      --preference-accent-soft:#C7CEFF;
    }
    .sidebar-preference-toggle[data-preference-group="color"][data-preference-value="blue"] {
      --preference-accent:#6366F1;
      --preference-accent-soft:#A7AEFF;
    }
    .sidebar-preference-toggle[data-preference-group="color"][data-preference-value="white"] {
      --preference-accent:#E5E7EB;
      --preference-accent-soft:#FFFFFF;
    }
    .sidebar-preference-toggle[data-preference-group="color"][data-preference-value="mint"] {
      --preference-accent:#22D3EE;
      --preference-accent-soft:#99F6E4;
    }
    .sidebar-preference-toggle[data-preference-group="color"][data-preference-value="sunset"] {
      --preference-accent:#FB7185;
      --preference-accent-soft:#FDBA74;
    }
    .sidebar-preference-toggle[data-preference-group="color"][data-preference-value="graphite"] {
      --preference-accent:#64748B;
      --preference-accent-soft:#CBD5E1;
    }
    .sidebar-scroll {
      min-height:0;
      overflow:auto;
      display:grid;
      gap:16px;
      align-content:start;
      padding-right:6px;
      scrollbar-gutter:stable;
    }
    .sidebar-scroll::-webkit-scrollbar {
      width:10px;
    }
    .sidebar-scroll::-webkit-scrollbar-track {
      background:transparent;
    }
    .sidebar-scroll::-webkit-scrollbar-thumb {
      background:color-mix(in srgb, var(--panel-3) 58%, var(--accent) 22%);
      border-radius:999px;
      border:2px solid transparent;
      background-clip:padding-box;
    }
    .sidebar-card {
      align-content:start;
    }
    .tree-toolbar {
      display:flex;
      gap:8px;
      align-items:flex-start;
      justify-content:flex-start;
      flex-wrap:wrap;
      position:relative;
    }
    .tree-heading {
      display:grid;
      gap:2px;
      min-width:0;
      align-content:start;
    }
    .tree-toolbar > .tree-heading {
      margin-left:auto;
      justify-items:end;
      text-align:right;
      align-self:flex-start;
    }
    .tree-title-row {
      display:inline-flex;
      align-items:center;
      gap:8px;
      height:36px;
      min-height:36px;
      padding:2px 8px 2px 12px;
      border-radius:999px;
      border:1px solid var(--toolbar-shell-border);
      background:var(--toolbar-shell-bg);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,.04),
        var(--toolbar-shell-shadow);
      width:fit-content;
      align-self:flex-start;
    }
    .tree-title-row h3 {
      margin:0;
      line-height:1;
      font-size:13px;
      font-weight:700;
      letter-spacing:.01em;
      color:var(--toolbar-label-contrast);
      text-shadow:0 1px 0 rgba(255,255,255,.08);
    }
    .tree-help {
      display:inline-flex;
      align-items:center;
      position:relative;
      flex-shrink:0;
      padding-left:8px;
      margin-left:2px;
      border-left:1px solid color-mix(in srgb, var(--toolbar-shell-border) 72%, transparent);
    }
    .info-trigger {
      width:22px;
      height:22px;
      padding:0;
      border-radius:999px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      font-size:11px;
      font-weight:700;
      color:var(--toolbar-label-contrast);
      border:1px solid var(--toolbar-button-border);
      background:linear-gradient(180deg, color-mix(in srgb, white 78%, var(--accent) 22%), color-mix(in srgb, var(--panel-2) 88%, var(--accent) 12%));
      box-shadow:none;
    }
    .info-trigger:hover,
    .info-trigger:focus-visible {
      transform:none;
      box-shadow:0 8px 18px rgba(4,10,22,.18);
    }
    .hover-tip {
      position:absolute;
      top:calc(100% + 8px);
      left:50%;
      width:min(250px, 70vw);
      padding:12px 14px;
      border-radius:16px;
      background:color-mix(in srgb, var(--panel) 92%, transparent);
      border:1px solid rgba(94,194,255,.22);
      color:#d7e7ff;
      font-size:12px;
      line-height:1.55;
      box-shadow:var(--shadow);
      opacity:0;
      pointer-events:none;
      transform:translate(-50%, -4px);
      transition:opacity .16s ease, transform .16s ease;
      z-index:10;
    }
    .tree-help:hover .hover-tip,
    .tree-help:focus-within .hover-tip {
      opacity:1;
      transform:translate(-50%, 0);
    }
    :root[data-theme="light"] .hover-tip {
      color:#1d3557;
      border-color:rgba(15,98,254,.2);
    }
    .tree-actions {
      display:flex;
      gap:10px;
      align-items:center;
      flex-wrap:wrap;
    }
    .tree-count-summary {
      display:inline-flex;
      align-items:center;
      min-height:38px;
      padding:0 14px;
      border-radius:999px;
      border:1px solid color-mix(in srgb, var(--accent) 18%, var(--border) 82%);
      background:linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 95%, transparent), color-mix(in srgb, var(--panel) 92%, transparent));
      color:color-mix(in srgb, var(--text) 74%, var(--muted) 26%);
      box-shadow:0 8px 18px rgba(4,10,22,.06);
      font-size:12px;
      font-weight:700;
      letter-spacing:.01em;
      white-space:nowrap;
    }
    .tree-toggle-button {
      width:38px;
      height:38px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      padding:0;
      border-radius:14px;
      border:1px solid color-mix(in srgb, var(--border) 70%, transparent);
      background:var(--toolbar-button-bg);
      color:color-mix(in srgb, var(--text) 74%, var(--muted) 26%);
      box-shadow:0 6px 16px rgba(0,0,0,.18);
    }
    .sidebar-settings-toggle.tree-toggle-button {
      width:40px;
      height:40px;
      border-radius:13px;
    }
    .sidebar-settings .tree-title-row {
      height:40px;
      min-height:40px;
      align-self:center;
    }
    .sidebar-settings .sidebar-preference-toggle {
      min-height:0;
    }
    .tree-toggle-button:hover {
      color:var(--text);
      background:var(--toolbar-button-hover-bg);
      border-color:color-mix(in srgb, var(--accent) 24%, var(--border) 76%);
    }
    .tree-toggle-button svg {
      display:block;
      width:18px;
      height:18px;
      overflow:visible;
    }
    .tree-action-button {
      min-height:38px;
      padding:0 18px;
      border-radius:14px;
      border:1px solid color-mix(in srgb, var(--border) 70%, transparent);
      background:var(--toolbar-button-bg);
      color:var(--text);
      box-shadow:0 6px 16px rgba(0,0,0,.18);
      font-size:13px;
      font-weight:600;
      letter-spacing:.01em;
    }
    .tree-action-button:hover {
      transform:translateY(-1px);
      border-color:color-mix(in srgb, var(--accent) 24%, var(--border) 76%);
      background:var(--toolbar-button-hover-bg);
    }
    .tree-action-button.primary {
      border-color:color-mix(in srgb, var(--accent) 34%, var(--border) 66%);
      background:var(--gradient-brand);
      color:white;
      box-shadow:0 0 20px color-mix(in srgb, var(--accent-primary-glow) 60%, transparent);
    }
    .tree-action-button.primary:hover {
      border-color:color-mix(in srgb, var(--accent) 40%, var(--border) 60%);
      background:linear-gradient(135deg, #7377F8 0%, #9567F8 100%);
      box-shadow:0 0 30px color-mix(in srgb, var(--accent-primary-glow) 72%, transparent);
    }
    .tree-action-button.secondary {
      color:color-mix(in srgb, var(--text) 80%, var(--muted) 20%);
    }
    .tree-action-button.secondary:hover {
      color:var(--text);
    }
    .sr-only {
      position:absolute;
      width:1px;
      height:1px;
      padding:0;
      margin:-1px;
      overflow:hidden;
      clip:rect(0, 0, 0, 0);
      white-space:nowrap;
      border:0;
    }
    .tree-panel-body {
      display:grid;
      gap:12px;
    }
    .tree-summary {
      font-size:12px;
      color:var(--muted);
    }
    @media (max-width: 720px) {
      .tree-toolbar > .tree-heading {
        margin-left:0;
        justify-items:start;
        text-align:left;
      }
    }
    .tree {
      position:relative;
      min-height:220px;
      border-radius:20px;
      border:1px solid color-mix(in srgb, var(--border) 82%, var(--accent) 8%);
      background:
        radial-gradient(circle at top left, color-mix(in srgb, var(--accent) 12%, transparent), transparent 38%),
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 94%, transparent), color-mix(in srgb, var(--panel) 92%, transparent));
      box-shadow:inset 0 1px 0 color-mix(in srgb, white 5%, transparent), 0 12px 28px rgba(4,10,22,.1);
      overflow:auto;
      padding:12px;
      scrollbar-gutter:stable both-edges;
    }
    .tree::-webkit-scrollbar {
      width:10px;
      height:10px;
    }
    .tree::-webkit-scrollbar-thumb {
      background:color-mix(in srgb, var(--panel-3) 58%, var(--accent) 18%);
      border-radius:999px;
    }
    .tree-graph-summary {
      font-size:11px;
      line-height:1.5;
      color:var(--muted);
      padding:0 2px;
    }
    .tree-graph-legend {
      display:flex;
      flex-wrap:wrap;
      gap:8px;
    }
    .tree-graph-legend-item {
      --legend-color: var(--accent);
      display:inline-flex;
      align-items:center;
      gap:7px;
      padding:5px 10px;
      border-radius:999px;
      border:1px solid color-mix(in srgb, var(--legend-color) 28%, var(--border) 72%);
      background:color-mix(in srgb, var(--legend-color) 11%, var(--panel-2) 89%);
      color:var(--text);
      font-size:11px;
      font-weight:600;
      line-height:1;
    }
    .tree-graph-legend-item::before {
      content:"";
      width:9px;
      height:9px;
      border-radius:999px;
      background:var(--legend-color);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--legend-color) 16%, transparent);
      flex-shrink:0;
    }
    .branch-graph {
      position:relative;
      min-width:100%;
      min-height:180px;
    }
    .branch-graph-root-label {
      --lane-color: var(--accent);
      position:absolute;
      top:8px;
      left:0;
      padding:4px 8px;
      border-radius:999px;
      border:1px solid color-mix(in srgb, var(--lane-color) 26%, var(--border) 74%);
      background:color-mix(in srgb, var(--lane-color) 12%, var(--panel-2) 88%);
      color:var(--text);
      font-size:10px;
      font-weight:700;
      letter-spacing:.04em;
      white-space:nowrap;
      box-shadow:0 8px 20px rgba(4,10,22,.1);
    }
    .branch-graph-lines {
      position:absolute;
      inset:0;
      overflow:visible;
      pointer-events:none;
    }
    .branch-graph-edge {
      fill:none;
      stroke:color-mix(in srgb, var(--accent) 26%, var(--border) 74%);
      stroke-width:2;
      stroke-linecap:round;
      stroke-linejoin:round;
      opacity:.14;
      transition:opacity .18s ease, stroke-width .18s ease, filter .18s ease;
    }
    .branch-graph-edge.is-context {
      opacity:.4;
    }
    .branch-graph-edge.is-focused {
      opacity:.78;
      stroke-width:2.35;
    }
    .branch-graph-node-shell {
      position:absolute;
      width:0;
      height:0;
      transform:translate(-50%, -50%);
      z-index:1;
      transition:opacity .18s ease, filter .18s ease;
    }
    .branch-graph-node-shell.active-card,
    .branch-graph-node-shell:hover {
      z-index:4;
    }
    .branch-graph.has-active-selection .branch-graph-node-shell {
      opacity:.52;
      filter:saturate(.72);
    }
    .branch-graph.has-active-selection .branch-graph-node-shell.active-card,
    .branch-graph.has-active-selection .branch-graph-node-shell:hover,
    .branch-graph.has-active-selection .branch-graph-node-shell:focus-within {
      opacity:1;
      filter:none;
    }
    .branch-graph-node {
      --branch-role-color: var(--accent);
      width:24px;
      height:24px;
      padding:0;
      border-radius:999px;
      border:2px solid color-mix(in srgb, var(--branch-role-color) 58%, var(--border) 42%);
      background:
        radial-gradient(circle at 35% 35%, color-mix(in srgb, white 16%, transparent), transparent 32%),
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 82%, var(--branch-role-color) 18%), color-mix(in srgb, var(--panel-3) 88%, transparent));
      box-shadow:0 8px 18px rgba(4,10,22,.16);
      position:relative;
      display:grid;
      place-items:center;
      transform:none;
      transition:border-color .18s ease, box-shadow .18s ease, background .18s ease, transform .18s ease;
    }
    .branch-graph-node::before {
      content:"";
      position:absolute;
      inset:-8px;
      border-radius:999px;
      border:1px solid transparent;
      background:transparent;
      transition:opacity .18s ease, border-color .18s ease, background .18s ease, transform .18s ease;
      opacity:0;
    }
    .branch-graph-node::after {
      content:"";
      width:8px;
      height:8px;
      border-radius:999px;
      background:var(--branch-role-color);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--branch-role-color) 16%, transparent);
    }
    .branch-graph-node:hover {
      transform:scale(1.03);
      border-color:color-mix(in srgb, var(--branch-role-color) 72%, var(--border) 28%);
      background:
        radial-gradient(circle at 35% 35%, color-mix(in srgb, white 18%, transparent), transparent 32%),
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 78%, var(--branch-role-color) 22%), color-mix(in srgb, var(--panel-3) 84%, transparent));
    }
    .branch-graph-node:focus-visible {
      outline:none;
      border-color:color-mix(in srgb, var(--branch-role-color) 84%, white 10%);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--branch-role-color) 22%, transparent), 0 8px 18px rgba(4,10,22,.18);
    }
    .branch-graph-node.is-root {
      width:28px;
      height:28px;
      border-color:color-mix(in srgb, var(--branch-role-color) 56%, var(--border) 44%);
      background:
        radial-gradient(circle at 35% 35%, color-mix(in srgb, white 18%, transparent), transparent 32%),
        linear-gradient(180deg, color-mix(in srgb, var(--panel-3) 68%, var(--branch-role-color) 24%), color-mix(in srgb, var(--panel-2) 88%, transparent));
    }
    .branch-graph-node.is-root::after {
      width:10px;
      height:10px;
    }
    .branch-graph-node.is-active {
      border-color:color-mix(in srgb, var(--branch-role-color) 88%, white 8%);
      box-shadow:0 0 0 6px color-mix(in srgb, var(--branch-role-color) 18%, transparent), 0 14px 30px rgba(4,10,22,.24);
      transform:scale(1.08);
    }
    .branch-graph-node.is-active::before {
      opacity:1;
      border-color:color-mix(in srgb, var(--branch-role-color) 34%, transparent);
      background:radial-gradient(circle, color-mix(in srgb, var(--branch-role-color) 12%, transparent), transparent 70%);
      transform:scale(1.02);
    }
    .branch-graph-node.is-active::after {
      width:10px;
      height:10px;
      background:color-mix(in srgb, var(--branch-role-color) 78%, white 22%);
    }
    .branch-graph-node.is-pending {
      border-style:dashed;
      opacity:.9;
    }
    .branch-graph-node.is-pending::after {
      background:color-mix(in srgb, var(--accent) 68%, var(--muted) 32%);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--accent) 10%, transparent);
    }
    .branch-graph-node.is-paused::after {
      background:var(--warn);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--warn) 16%, transparent);
    }
    .branch-graph-node.is-ready::after {
      background:var(--success);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--success) 16%, transparent);
    }
    .branch-graph-node.is-merged::after {
      background:var(--danger);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--danger) 16%, transparent);
    }
    .branch-detail-overlay {
      position:fixed;
      top:0;
      left:0;
      width:min(220px, calc(100vw - 32px));
      z-index:240;
      pointer-events:none;
      opacity:0;
      transition:opacity .14s ease;
    }
    .branch-detail-overlay.is-visible {
      pointer-events:auto;
      opacity:1;
    }
    .branch-node-detail {
      --branch-role-color: var(--accent);
      width:100%;
      display:grid;
      gap:10px;
      padding:12px;
      border-radius:18px;
      border:1px solid color-mix(in srgb, var(--branch-role-color) 18%, var(--border) 82%);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 95%, transparent), color-mix(in srgb, var(--panel) 94%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--branch-role-color) 16%, transparent), transparent 44%);
      box-shadow:0 18px 36px rgba(4,10,22,.18);
      backdrop-filter:blur(12px);
      -webkit-backdrop-filter:blur(12px);
    }
    .branch-node-detail-head {
      display:grid;
      gap:6px;
    }
    .branch-node-title {
      font-size:13px;
      line-height:1.4;
      font-weight:700;
      color:var(--text);
      word-break:break-word;
    }
    .branch-detail-overlay.active-card .branch-node-title {
      color:color-mix(in srgb, var(--branch-role-color) 74%, var(--text) 26%);
    }
    .branch-node-subtitle {
      font-size:11px;
      line-height:1.45;
      color:var(--muted);
      word-break:break-all;
    }
    .branch-node-badges {
      display:flex;
      flex-wrap:wrap;
      gap:6px;
    }
    .branch-node-badge {
      display:inline-flex;
      align-items:center;
      padding:4px 8px;
      border-radius:999px;
      font-size:10px;
      font-weight:700;
      letter-spacing:.04em;
      white-space:nowrap;
      border:1px solid color-mix(in srgb, var(--border) 78%, transparent);
      background:color-mix(in srgb, var(--panel-3) 62%, transparent);
      color:var(--muted);
    }
    .branch-node-badge.current {
      border-color:color-mix(in srgb, var(--accent) 34%, var(--border) 46%);
      background:color-mix(in srgb, var(--accent) 16%, transparent);
      color:var(--accent);
    }
    .branch-node-badge.success {
      border-color:color-mix(in srgb, var(--success) 30%, var(--border) 70%);
      color:var(--success);
    }
    .branch-node-badge.warn {
      border-color:color-mix(in srgb, var(--warn) 30%, var(--border) 70%);
      color:var(--warn);
    }
    .branch-node-badge.danger {
      border-color:color-mix(in srgb, var(--danger) 30%, var(--border) 70%);
      color:var(--danger);
    }
    .branch-name {
      font-size:12px;
      line-height:1.4;
    }
    .branch-name-head {
      display:flex;
      align-items:center;
      gap:8px;
      flex-wrap:wrap;
    }
    .branch-node-meta {
      display:grid;
      gap:6px;
    }
    .branch-node-meta-row {
      display:flex;
      justify-content:space-between;
      gap:10px;
      font-size:11px;
      line-height:1.45;
    }
    .branch-node-meta-label {
      color:var(--muted);
      flex:0 0 auto;
    }
    .branch-node-meta-value {
      color:var(--text);
      text-align:right;
      word-break:break-word;
    }
    .branch-node-actions {
      display:flex;
      justify-content:flex-end;
      gap:8px;
      flex-wrap:wrap;
      margin-top:2px;
      padding-top:8px;
      border-top:1px solid color-mix(in srgb, var(--border) 62%, transparent);
    }
    .branch-inline-action {
      width:auto;
      padding:5px 10px;
      border-radius:999px;
      font-size:11px;
      background:color-mix(in srgb, var(--panel-2) 82%, transparent);
      border:1px solid color-mix(in srgb, var(--border) 72%, transparent);
      color:var(--muted);
      box-shadow:none;
    }
    .branch-inline-action:hover {
      color:var(--text);
      background:color-mix(in srgb, var(--panel-3) 70%, transparent);
    }
    .branch-inline-action.warn {
      background:color-mix(in srgb, var(--panel-2) 82%, var(--warn) 12%);
      border-color:color-mix(in srgb, var(--border) 68%, var(--warn) 16%);
      color:color-mix(in srgb, var(--text) 82%, var(--warn) 38%);
    }
    .branch-inline-action.pending {
      background:color-mix(in srgb, var(--panel-2) 76%, var(--accent) 12%);
      border-color:color-mix(in srgb, var(--border) 68%, var(--accent) 18%);
      color:var(--accent);
      pointer-events:none;
    }
    .branch-card.pending-card {
      border-style:dashed;
      box-shadow:0 0 0 1px color-mix(in srgb, var(--accent) 14%, transparent), 0 8px 22px rgba(4,10,22,.1);
      opacity:.92;
    }
    .archived-list {
      display:grid;
      gap:12px;
      max-height:min(260px, 34vh);
      overflow:auto;
      padding-right:4px;
      scrollbar-gutter:stable;
    }
    .archived-list::-webkit-scrollbar {
      width:8px;
    }
    .archived-list::-webkit-scrollbar-track {
      background:transparent;
    }
    .archived-list::-webkit-scrollbar-thumb {
      background:color-mix(in srgb, var(--panel-3) 58%, var(--accent) 18%);
      border-radius:999px;
    }
    .archived-item {
      display:grid;
      gap:8px;
      padding:10px;
      border-radius:14px;
      border:1px solid color-mix(in srgb, var(--border) 82%, var(--accent) 8%);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 90%, transparent), color-mix(in srgb, var(--panel) 88%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--accent) 10%, transparent), transparent 54%);
      box-shadow:0 10px 22px rgba(4,10,22,.1);
    }
    .archived-empty {
      border:1px dashed color-mix(in srgb, var(--border) 78%, transparent);
      border-radius:16px;
      padding:14px;
      text-align:center;
      background:color-mix(in srgb, var(--panel) 56%, transparent);
    }
    .focus-modal-backdrop {
      position:fixed;
      inset:0;
      z-index:280;
      background:rgba(6, 10, 18, .56);
      backdrop-filter:blur(4px);
      -webkit-backdrop-filter:blur(4px);
    }
    .focus-modal {
      position:fixed;
      inset:0;
      z-index:281;
      display:grid;
      place-items:center;
      padding:20px;
    }
    .focus-modal[hidden],
    .focus-modal-backdrop[hidden],
    .branch-detail-overlay[hidden],
    .toolbar-tooltip-overlay[hidden] {
      display:none !important;
    }
    .focus-modal-card {
      width:min(560px, calc(100vw - 32px));
      max-height:min(88vh, 760px);
      overflow:auto;
      display:grid;
      gap:14px;
      padding:24px;
      border-radius:24px;
      border:1px solid color-mix(in srgb, var(--border) 78%, var(--accent) 12%);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 98%, transparent), color-mix(in srgb, var(--panel) 96%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--accent-violet) 14%, transparent), transparent 42%);
      box-shadow:0 18px 40px rgba(0,0,0,.5), 0 0 30px color-mix(in srgb, var(--accent-primary-glow) 24%, transparent);
    }
    .focus-modal-head {
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:12px;
    }
    .focus-modal-head h3 {
      margin:0;
      font-size:18px;
    }
    .focus-modal-copy {
      display:grid;
      gap:6px;
    }
    .focus-modal-copy p {
      margin:0;
      color:var(--muted);
      font-size:13px;
      line-height:1.55;
    }
    .focus-modal-loading {
      display:grid;
      gap:8px;
      padding:14px 16px;
      border-radius:16px;
      border:1px solid color-mix(in srgb, var(--border) 76%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 88%, transparent), color-mix(in srgb, var(--panel) 92%, transparent)),
        radial-gradient(circle at top right, color-mix(in srgb, var(--accent) 10%, transparent), transparent 52%);
    }
    .focus-modal-loading strong {
      font-size:13px;
    }
    .focus-modal-loading p {
      margin:0;
      color:var(--muted);
      font-size:13px;
      line-height:1.55;
    }
    .focus-modal-close {
      width:auto;
      min-width:40px;
      padding:6px 10px;
      border-radius:999px;
      background:color-mix(in srgb, var(--panel-2) 90%, transparent);
      box-shadow:none;
    }
    .focus-modal-form {
      display:grid;
      gap:12px;
    }
    .focus-modal-field {
      display:grid;
      gap:6px;
    }
    .focus-modal-field span {
      font-size:12px;
      font-weight:700;
      color:var(--muted);
    }
    .focus-modal-field input,
    .focus-modal-field select,
    .focus-modal-field textarea {
      width:100%;
      border-radius:14px;
      border:1px solid color-mix(in srgb, var(--border) 80%, transparent);
      background:color-mix(in srgb, var(--panel-2) 90%, transparent);
      color:var(--text);
      padding:10px 12px;
      font:inherit;
      resize:vertical;
      min-height:44px;
    }
    .focus-modal-field textarea {
      min-height:88px;
    }
    .focus-modal-note {
      font-size:12px;
      line-height:1.55;
      color:var(--muted);
    }
    .focus-modal-section {
      display:grid;
      gap:6px;
      padding:12px;
      border-radius:16px;
      border:1px solid color-mix(in srgb, var(--border) 76%, transparent);
      background:color-mix(in srgb, var(--panel-2) 82%, transparent);
    }
    .focus-modal-section h4 {
      margin:0;
      font-size:13px;
    }
    .focus-modal-section ul {
      margin:0;
      padding-left:18px;
      display:grid;
      gap:4px;
      color:var(--text);
      font-size:13px;
      line-height:1.5;
    }
    .focus-modal-summary {
      white-space:pre-wrap;
      color:var(--text);
      font-size:13px;
      line-height:1.55;
    }
    .focus-modal-actions {
      display:flex;
      justify-content:flex-end;
      gap:10px;
      flex-wrap:wrap;
      margin-top:14px;
      padding-top:14px;
      border-top:1px solid color-mix(in srgb, var(--border) 74%, transparent);
    }
    .focus-modal-actions button {
      min-height:46px;
      padding:10px 18px;
      border-radius:16px;
      font-weight:700;
      letter-spacing:.01em;
      box-shadow:none;
    }
    .focus-modal-actions button:hover {
      transform:translateY(-1px);
    }
    #cancel-merge-review {
      background:color-mix(in srgb, var(--panel-2) 94%, transparent);
      border-color:color-mix(in srgb, var(--border) 78%, transparent);
      color:var(--muted);
    }
    #cancel-merge-review:hover {
      background:color-mix(in srgb, var(--panel-3) 82%, transparent);
      color:var(--text);
    }
    #regenerate-merge-review {
      background:color-mix(in srgb, var(--panel-2) 84%, var(--accent) 12%);
      border-color:color-mix(in srgb, var(--accent) 24%, var(--border) 76%);
      color:color-mix(in srgb, var(--text) 90%, var(--accent) 10%);
    }
    #regenerate-merge-review:hover {
      background:color-mix(in srgb, var(--panel-3) 72%, var(--accent) 22%);
      border-color:color-mix(in srgb, var(--accent) 34%, var(--border) 66%);
    }
    #submit-merge-review {
      background:linear-gradient(180deg, color-mix(in srgb, var(--accent) 82%, white 10%), color-mix(in srgb, var(--accent) 90%, black 8%));
      border-color:color-mix(in srgb, var(--accent) 46%, var(--border) 54%);
      color:white;
      box-shadow:0 10px 22px color-mix(in srgb, var(--accent) 18%, transparent);
    }
    #submit-merge-review:hover {
      background:linear-gradient(180deg, color-mix(in srgb, var(--accent) 88%, white 8%), color-mix(in srgb, var(--accent) 92%, black 6%));
      border-color:color-mix(in srgb, var(--accent) 56%, var(--border) 44%);
      box-shadow:0 14px 28px color-mix(in srgb, var(--accent) 24%, transparent);
    }
    body.has-modal {
      overflow:hidden;
    }
    @media (max-width: 1280px) {
      .shell { grid-template-columns: minmax(260px, var(--sidebar-width)) var(--resizer-width) minmax(0,1fr); }
    }
    @media (max-width: 960px) {
      .shell { grid-template-columns: 1fr; }
      .panel { border-right:none; border-bottom:1px solid var(--border); }
      .panel-resizer { display:none; }
      .chat-header-top {
        grid-template-columns:auto minmax(0, 1fr);
      }
      .chat-header-actions {
        justify-content:flex-end;
      }
      .chat-header-primary-actions,
      .chat-header-nav,
      .chat-header-settings {
        justify-content:flex-end;
      }
      .chat-toolbar {
        justify-content:flex-end;
      }
      .sidebar-panel {
        min-height:auto;
        height:auto;
        overflow:visible;
      }
      .sidebar-scroll {
        overflow:visible;
        padding-right:0;
      }
      .archived-list {
        max-height:none;
        overflow:visible;
        padding-right:0;
      }
      .chat-history { max-height:none; min-height:360px; }
      .brand-copy {
        flex-wrap:wrap;
        align-items:flex-start;
      }
      .brand-meta {
        width:100%;
      }
      .sidebar-preferences-row {
        width:100%;
      }
      .composer-input-shell {
        grid-template-columns:minmax(0, 1fr);
      }
      .composer-input-row {
        min-height:unset;
      }
      .composer-footer-row {
        align-items:stretch;
        flex-direction:column;
        min-height:unset;
      }
      .composer-actions-row {
        justify-content:flex-end;
      }
      .composer-model-row {
        align-items:stretch;
        width:100%;
        flex:0 0 auto;
      }
      .composer-model-anchor {
        max-width:none;
        flex-basis:100%;
      }
      .composer-model-trigger {
        max-width:none;
        width:100%;
      }
      .composer-model-panel {
        width:100%;
      }
      .composer-inline-actions {
        width:auto;
        grid-template-columns:auto 34px;
      }
      .composer-actions-row .composer-inline-actions {
        margin-left:auto;
      }
    }
  </style>
</head>
<body>
  <div id="app-shell" class="shell">
    <aside id="sidebar-panel" class="panel sidebar-panel">
      <div class="sidebar-copy">
        <div class="sidebar-brand-stack">
          <div class="brand-lockup" aria-label="Focus Agent">
            <span class="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs>
                  <linearGradient id="focus-agent-brand-accent" x1="10" y1="8" x2="38" y2="40" gradientUnits="userSpaceOnUse">
                    <stop offset="0" stop-color="#0F62FE"/>
                    <stop offset="1" stop-color="#6BA9FF"/>
                  </linearGradient>
                </defs>
                <circle cx="16.5" cy="24" r="8.5" stroke="url(#focus-agent-brand-accent)" stroke-width="3"/>
                <circle cx="16.5" cy="24" r="3.25" fill="url(#focus-agent-brand-accent)"/>
                <path d="M25 24H31V15.5H37.5" stroke="#1D3557" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M31 24V32.5H37.5" stroke="#1D3557" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                <circle cx="37.5" cy="15.5" r="3.1" fill="#1D3557"/>
                <circle cx="31" cy="24" r="3.1" fill="#1D3557"/>
                <circle cx="37.5" cy="32.5" r="3.1" fill="#1D3557"/>
              </svg>
            </span>
            <div class="brand-copy">
              <span class="brand-wordmark">Focus Agent</span>
            </div>
          </div>
          <div class="sidebar-settings">
            <button id="toggle-tree" type="button" class="tree-toggle-button sidebar-settings-toggle" aria-expanded="true" aria-label="Collapse sidebar" title="Collapse sidebar">
              <span id="toggle-tree-label" class="sr-only">Collapse sidebar</span>
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <rect x="4.15" y="4" width="2.2" height="12" rx="1.1" fill="currentColor" opacity="0.96"></rect>
                <path d="M12.85 6.1 9.05 9.65a.48.48 0 0 0 0 .7l3.8 3.55c.31.29.8.07.8-.35V6.45c0-.42-.49-.64-.8-.35Z" fill="currentColor"></path>
              </svg>
            </button>
            <div class="tree-title-row sidebar-settings-tree-pill">
              <h3>Branches</h3>
              <div class="tree-help">
                <button type="button" class="info-trigger" aria-label="How branches work">?</button>
                <div class="hover-tip">
                  <strong>How branches work</strong><br />
                  1. Start the conversation in the main thread.<br />
                  2. Click New branch whenever you want to spin out a focused side path.<br />
                  3. Hover here any time if you want to see this reminder again.
                </div>
              </div>
            </div>
            <div class="sidebar-preferences-row">
              <input id="language-select" class="sidebar-preference-input" type="hidden" value="en" />
              <input id="theme-select" class="sidebar-preference-input" type="hidden" value="system" />
              <input id="color-select" class="sidebar-preference-input" type="hidden" value="white" />
              <button id="language-toggle" type="button" class="sidebar-preference-toggle" data-preference-group="language" data-preference-value="en">
                <span class="sidebar-picker-text">Language</span>
                <span id="language-toggle-icon" class="sidebar-preference-icon" aria-hidden="true"></span>
                <span id="language-toggle-value" class="sidebar-preference-value">English</span>
              </button>
              <button id="theme-toggle" type="button" class="sidebar-preference-toggle" data-preference-group="theme" data-preference-value="system">
                <span class="sidebar-picker-text">Theme</span>
                <span id="theme-toggle-icon" class="sidebar-preference-icon" aria-hidden="true"></span>
                <span id="theme-toggle-value" class="sidebar-preference-value">Follow system</span>
              </button>
              <button id="color-toggle" type="button" class="sidebar-preference-toggle" data-preference-group="color" data-preference-value="white">
                <span class="sidebar-picker-text">Color</span>
                <span id="color-toggle-icon" class="sidebar-preference-icon" aria-hidden="true"></span>
                <span id="color-toggle-value" class="sidebar-preference-value">White</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="sidebar-scroll">
        <section id="branch-tree-panel" class="card stack sidebar-card branch-tree-panel">
          <div class="tree-toolbar">
            <div class="tree-actions">
              <button id="create-branch" class="tree-action-button primary">New branch</button>
              <button id="load-tree" class="tree-action-button secondary">Refresh branches</button>
              <span id="tree-branch-count-summary" class="tree-count-summary">In progress 0 · Archived 0</span>
            </div>
          </div>
          <div id="tree-panel-body" class="tree-panel-body">
            <div class="tree-graph-summary">Hover or click any node to inspect its branch details, then open it only when you want to switch context.</div>
            <div id="tree-graph-legend" class="tree-graph-legend"></div>
            <div id="tree-root" class="tree"></div>
          </div>
        </section>

        <section class="card stack sidebar-card">
          <div>
            <h3>Archived branches</h3>
            <div class="tree-summary">Archived branches are hidden from the tree until you activate them again.</div>
          </div>
          <div id="archived-root" class="archived-list">
            <div class="muted archived-empty">No archived branches.</div>
          </div>
        </section>
      </div>
    </aside>
    <div id="panel-resizer" class="panel-resizer" role="separator" aria-orientation="vertical" aria-label="Resize panels" tabindex="0"></div>

    <main class="panel chat-panel">
      <section class="card chat-header">
        <div class="chat-header-top">
          <div class="chat-header-copy">
            <button
              id="chat-logo-toggle"
              type="button"
              class="brand-lockup chat-brand-lockup chat-logo-toggle"
              aria-controls="sidebar-panel"
              aria-expanded="true"
              aria-label="Collapse sidebar"
              title="Collapse sidebar"
            >
              <span class="brand-mark" aria-hidden="true">
                <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <defs>
                    <linearGradient id="focus-agent-chat-brand-accent" x1="10" y1="8" x2="38" y2="40" gradientUnits="userSpaceOnUse">
                      <stop offset="0" stop-color="#0F62FE"/>
                      <stop offset="1" stop-color="#6BA9FF"/>
                    </linearGradient>
                  </defs>
                  <circle cx="16.5" cy="24" r="8.5" stroke="url(#focus-agent-chat-brand-accent)" stroke-width="3"/>
                  <circle cx="16.5" cy="24" r="3.25" fill="url(#focus-agent-chat-brand-accent)"/>
                  <path d="M25 24H31V15.5H37.5" stroke="#1D3557" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M31 24V32.5H37.5" stroke="#1D3557" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                  <circle cx="37.5" cy="15.5" r="3.1" fill="#1D3557"/>
                  <circle cx="31" cy="24" r="3.1" fill="#1D3557"/>
                  <circle cx="37.5" cy="32.5" r="3.1" fill="#1D3557"/>
                </svg>
              </span>
            </button>
          </div>
          <div class="chat-header-actions">
            <div class="chat-header-primary-actions">
              <button id="focus-branch-tree" type="button" class="chat-toolbar-pill toolbar-tooltip-host" data-compact-button="true">
                <span class="toolbar-icon" aria-hidden="true">
                  <svg viewBox="0 0 20 20">
                    <path fill-rule="evenodd" clip-rule="evenodd" d="M10 3.2a6.8 6.8 0 1 1 0 13.6 6.8 6.8 0 0 1 0-13.6Zm0 2.3a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Z" fill="currentColor"></path>
                    <rect x="9.15" y="1.85" width="1.7" height="3.1" rx="0.85" fill="currentColor"></rect>
                    <rect x="9.15" y="15.05" width="1.7" height="3.1" rx="0.85" fill="currentColor"></rect>
                    <rect x="1.85" y="9.15" width="3.1" height="1.7" rx="0.85" fill="currentColor"></rect>
                    <rect x="15.05" y="9.15" width="3.1" height="1.7" rx="0.85" fill="currentColor"></rect>
                    <circle cx="10" cy="10" r="1.6" fill="currentColor"></circle>
                  </svg>
                </span>
                <span id="active-thread-pill" class="toolbar-text">current: Main</span>
              </button>
              <button id="composer-create-branch" type="button" class="chat-toolbar-button primary toolbar-tooltip-host" data-compact-button="true">
                <span class="toolbar-icon" aria-hidden="true">
                  <svg viewBox="0 0 20 20">
                    <circle cx="5" cy="5" r="1.75" fill="currentColor" stroke="none"></circle>
                    <circle cx="5" cy="15" r="1.75" fill="currentColor" stroke="none"></circle>
                    <rect x="4.15" y="6.6" width="1.7" height="6.8" rx="0.85" fill="currentColor"></rect>
                    <rect x="6.7" y="14.15" width="4.3" height="1.7" rx="0.85" fill="currentColor"></rect>
                    <path d="M10.4 14.15c2.03 0 3.7-1.66 3.7-3.7V8.3h1.7v2.15a5.4 5.4 0 0 1-5.4 5.4h-.3v-1.7h.3Z" fill="currentColor"></path>
                    <rect x="12.15" y="4.9" width="5.7" height="1.7" rx="0.85" fill="currentColor"></rect>
                    <rect x="14.15" y="2.9" width="1.7" height="5.7" rx="0.85" fill="currentColor"></rect>
                  </svg>
                </span>
                <span id="composer-create-branch-label" class="toolbar-text">New branch</span>
              </button>
              <button id="prepare-merge" type="button" class="chat-toolbar-button toolbar-tooltip-host" data-compact-button="true" hidden>
                <span class="toolbar-icon" aria-hidden="true">⇡</span>
                <span class="toolbar-text">Generate conclusion</span>
              </button>
            </div>
            <div id="thread-nav" class="chat-header-nav" hidden>
              <button id="back-to-main" type="button" class="thread-nav-button chat-toolbar-button toolbar-tooltip-host" data-compact-button="true">
                <span class="toolbar-icon" aria-hidden="true">↩</span>
                <span class="toolbar-text">Back to main</span>
              </button>
              <button id="back-to-parent" type="button" class="thread-nav-button chat-toolbar-button toolbar-tooltip-host" data-compact-button="true">
                <span class="toolbar-icon" aria-hidden="true">↰</span>
                <span class="toolbar-text">Back one level</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      <section class="card chat-transcript">
        <div id="chat-history" class="chat-history">
          <div id="chat-empty" class="chat-empty">
            Start chatting here. Branches appear on the left whenever the agent forks work.
          </div>
        </div>
      </section>

      <section class="card composer">
        <label class="composer-input-shell">
          <span class="sr-only">Message</span>
          <div class="composer-input-row">
            <textarea id="stream-message" rows="1" aria-label="Message" placeholder="Start on the main thread, and create a branch only when you want to explore a separate direction."></textarea>
          </div>
          <div class="composer-footer-row">
            <div class="composer-actions-row">
              <div class="composer-inline-actions">
                <button id="clear-stream" type="button" class="composer-action-button" aria-label="Clear input" title="Clear input">
                  <span class="composer-action-icon" aria-hidden="true">
                    <svg viewBox="0 0 20 20">
                      <path fill-rule="evenodd" clip-rule="evenodd" d="M7.65 3.25c-.83 0-1.5.67-1.5 1.5v.4H4.5a.85.85 0 0 0 0 1.7h.58l.63 8.02a2.05 2.05 0 0 0 2.05 1.88h4.48a2.05 2.05 0 0 0 2.05-1.88l.63-8.02h.58a.85.85 0 1 0 0-1.7h-1.65v-.4c0-.83-.67-1.5-1.5-1.5h-4.7Zm.2 1.7h4.3v.2h-4.3v-.2Zm-.63 1.9-.63 8a.35.35 0 0 0 .35.35h6.12a.35.35 0 0 0 .35-.35l-.63-8H7.22Zm1.28 2.2a.85.85 0 1 1 1.7 0v4.35a.85.85 0 1 1-1.7 0V9.05Zm3.3 0a.85.85 0 1 1 1.7 0v4.35a.85.85 0 1 1-1.7 0V9.05Z" fill="currentColor"></path>
                    </svg>
                  </span>
                  <span class="sr-only">Clear input</span>
                </button>
                <button id="open-stream" type="button" class="composer-action-button" aria-label="Send message" title="Send message">
                  <span class="composer-action-icon" aria-hidden="true">
                    <svg viewBox="0 0 20 20">
                      <path d="M16.99 3.01a.9.9 0 0 0-.94-.16L3.58 8.38a.9.9 0 0 0 .07 1.68l5 1.88 1.88 5a.9.9 0 0 0 1.68.07l5.53-12.47a.9.9 0 0 0-.75-1.53Zm-7.21 8.31L6.2 9.97l8.19-3.62-3.62 8.19-1.35-3.58a.9.9 0 0 1 .2-.95l3.14-3.14a.6.6 0 0 0-.85-.85l-3.14 3.14a.9.9 0 0 1-.95.2l1.96 1.96Z" fill="currentColor"></path>
                    </svg>
                  </span>
                  <span class="sr-only">Send message</span>
                </button>
              </div>
            </div>
            <div class="composer-model-row">
              <div class="composer-model-anchor">
                <button id="composer-model-trigger" type="button" class="composer-model-trigger" aria-label="Model selector" aria-expanded="false">
                  <span class="composer-model-trigger-copy">
                    <span id="composer-model-trigger-logo" class="composer-model-logo-shell">
                      <span class="composer-model-logo-fallback">M</span>
                    </span>
                    <span id="composer-model-trigger-label" class="composer-model-trigger-label">Loading models...</span>
                    <span id="composer-model-trigger-provider" class="composer-model-trigger-provider">...</span>
                  </span>
                  <span class="composer-model-trigger-icon" aria-hidden="true">
                    <svg viewBox="0 0 20 20">
                      <path d="M5.25 7.5 10 12.25 14.75 7.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
                    </svg>
                  </span>
                </button>
                <div id="composer-model-panel" class="composer-model-panel" hidden>
                  <div class="composer-model-panel-head">
                    <div class="composer-model-panel-title">
                      <span>Model selector</span>
                      <small>command palette</small>
                    </div>
                  </div>
                  <div id="composer-model-list" class="composer-model-list">
                    <div class="composer-model-empty">Loading models...</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <span class="sr-only composer-actions-note">Keep the current thread focused here. Create a branch only when you want to split into a separate direction.</span>
        </label>
      </section>
    </main>
  </div>
  <div id="branch-detail-overlay" class="branch-detail-overlay" hidden></div>
  <div id="toolbar-tooltip-overlay" class="toolbar-tooltip-overlay" hidden></div>
  <div id="modal-backdrop" class="focus-modal-backdrop" hidden></div>
  <section id="branch-create-modal" class="focus-modal" role="dialog" aria-modal="true" aria-labelledby="branch-create-title" hidden>
    <div class="focus-modal-card">
      <div class="focus-modal-head">
        <div class="focus-modal-copy">
          <h3 id="branch-create-title">Create branch</h3>
          <p>Choose an optional branch name. New branches can return conclusions upstream by default.</p>
        </div>
        <button id="close-branch-create" type="button" class="focus-modal-close" aria-label="Close">×</button>
      </div>
      <div class="focus-modal-form">
        <label class="focus-modal-field">
          <span>Branch name (optional)</span>
          <input id="branch-name-input" type="text" placeholder="Leave blank to auto-generate a name" />
        </label>
        <div class="focus-modal-note">The current composer draft will still be sent as branch naming context when available. Every branch can later return its conclusion upstream when you choose to merge it.</div>
      </div>
      <div class="focus-modal-actions">
        <button id="cancel-branch-create" type="button">Cancel</button>
        <button id="confirm-branch-create" type="button">Create branch</button>
      </div>
    </div>
  </section>
  <section id="merge-review-modal" class="focus-modal" role="dialog" aria-modal="true" aria-labelledby="merge-review-title" hidden>
    <div class="focus-modal-card">
      <div class="focus-modal-head">
        <div class="focus-modal-copy">
          <h3 id="merge-review-title">Prepare merge</h3>
          <p>Review the branch summary, choose an import mode, and explicitly approve or reject the upstream import.</p>
        </div>
        <button id="close-merge-review" type="button" class="focus-modal-close" aria-label="Close">×</button>
      </div>
      <div id="merge-review-loading" class="focus-modal-loading" hidden>
        <strong id="merge-loading-title">Preparing merge proposal...</strong>
        <p id="merge-loading-copy">This can take a moment while the branch summary is prepared.</p>
      </div>
      <div id="merge-review-content">
        <div class="focus-modal-section">
          <h4 id="merge-summary-heading">Summary</h4>
          <label class="focus-modal-field">
            <span id="merge-summary-label">Summary</span>
            <textarea id="merge-proposal-summary" placeholder="Edit the summary before merging"></textarea>
          </label>
        </div>
        <div class="focus-modal-section">
          <h4 id="merge-findings-heading">Key findings</h4>
          <label class="focus-modal-field">
            <span id="merge-findings-label">Key findings</span>
            <textarea id="merge-proposal-findings" placeholder="One finding per line"></textarea>
          </label>
        </div>
        <div class="focus-modal-section">
          <h4 id="merge-open-questions-heading">Open questions</h4>
          <label class="focus-modal-field">
            <span id="merge-open-questions-label">Open questions</span>
            <textarea id="merge-proposal-open-questions" placeholder="One open question per line"></textarea>
          </label>
        </div>
        <div class="focus-modal-section">
          <h4 id="merge-evidence-heading">Evidence refs</h4>
          <label class="focus-modal-field">
            <span id="merge-evidence-label">Evidence refs</span>
            <textarea id="merge-proposal-evidence" placeholder="One evidence ref per line"></textarea>
          </label>
        </div>
        <div class="focus-modal-section">
          <h4 id="merge-artifacts-heading">Artifacts</h4>
          <label class="focus-modal-field">
            <span id="merge-artifacts-label">Artifacts</span>
            <textarea id="merge-proposal-artifacts" placeholder="One artifact path or id per line"></textarea>
          </label>
        </div>
        <div class="focus-modal-note" id="merge-proposal-recommended-mode">Recommended import mode: summary_only</div>
        <div class="focus-modal-form">
          <label class="focus-modal-field">
            <span>Decision</span>
            <select id="merge-decision-select">
              <option value="approve">Approve</option>
              <option value="reject">Reject</option>
            </select>
          </label>
          <label class="focus-modal-field">
            <span>Import mode</span>
            <select id="merge-mode-select">
              <option value="summary_only">Summary only</option>
              <option value="summary_plus_evidence">Summary + evidence</option>
              <option value="selected_artifacts">Selected artifacts only</option>
            </select>
          </label>
          <label class="focus-modal-field">
            <span>Merge target</span>
            <select id="merge-target-select">
              <option value="return_thread">Return upstream</option>
              <option value="root_thread">Main branch</option>
            </select>
          </label>
          <label id="merge-selected-artifacts-row" class="focus-modal-field" hidden>
            <span>Selected artifacts</span>
            <textarea id="merge-selected-artifacts" placeholder="Enter one artifact path or id per line"></textarea>
          </label>
          <label class="focus-modal-field">
            <span>Rationale</span>
            <textarea id="merge-rationale" placeholder="Optional reviewer notes"></textarea>
          </label>
        </div>
        <div class="focus-modal-actions">
          <button id="cancel-merge-review" type="button">Close</button>
          <button id="regenerate-merge-review" type="button">Regenerate conclusion</button>
          <button id="submit-merge-review" type="button">Submit decision</button>
        </div>
      </div>
    </div>
  </section>

  <script>
    const DEMO_USER_ID = "researcher-1";
    const DEMO_TENANT_ID = "demo-tenant";

    const state = {
      token: null,
      tree: null,
      archivedBranches: [],
      pendingBranch: null,
      currentVisibleText: "",
      abortController: null,
      currentAssistantBubble: null,
      lastUserMessage: "",
      themePreference: "system",
      accentPreference: "white",
      rootThreadId: `${DEMO_USER_ID}-main`,
      activeThreadId: `${DEMO_USER_ID}-main`,
      loadedThreadId: null,
      activeBranchMeta: null,
      detailThreadId: null,
      detailAnchorElement: null,
      detailHideTimer: null,
      renderedTree: null,
      statusFeed: [],
      currentStatusText: "",
      currentStatusKind: "",
      currentStatusDetail: "",
      currentActivityMeta: "",
      activityRow: null,
      activityBubble: null,
      threadUiById: {},
      toolbarTooltipAnchor: null,
      availableModels: [],
      defaultModelId: null,
      selectedModel: null,
      selectedProvider: null,
      selectedThinkingMode: "",
      activeMergeProposal: null,
      activeMergeThreadId: null,
      pendingMergeProposal: false,
      mergeReviewRequestId: 0,
      chatAutoFollow: true,
      chatLastScrollTop: 0,
      chatTouchY: null,
      streamingResponseActive: false,
    };

    const $ = (id) => document.getElementById(id);
    const apiBase = () => window.location.origin;
    const colorModeQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const LANGUAGE_OPTIONS = ["en", "zh"];
    const THEME_OPTIONS = ["system", "light", "dark"];
    const ACCENT_OPTIONS = ["white", "blue", "mint", "sunset", "graphite"];
    const PREFERENCE_INPUT_IDS = {
      language: "language-select",
      theme: "theme-select",
      color: "color-select",
    };
    const PREFERENCE_BUTTON_IDS = {
      language: "language-toggle",
      theme: "theme-toggle",
      color: "color-toggle",
    };
    const PREFERENCE_VALUE_IDS = {
      language: "language-toggle-value",
      theme: "theme-toggle-value",
      color: "color-toggle-value",
    };
    const PREFERENCE_ICON_IDS = {
      language: "language-toggle-icon",
      theme: "theme-toggle-icon",
      color: "color-toggle-icon",
    };
    const SIDEBAR_WIDTH_KEY = "focus-agent-sidebar-width";
    const SIDEBAR_COLLAPSED_KEY = "focus-agent-sidebar-collapsed";
    const ACCENT_THEME_KEY = "focus-agent-accent";
    const MODEL_PROVIDER_STORAGE_KEY = "focus-agent-model-provider";
    const MODEL_ID_STORAGE_KEY = "focus-agent-selected-model";
    const THINKING_MODE_STORAGE_KEY = "focus-agent-thinking-mode";
    const SIDEBAR_MIN_WIDTH = 248;
    const MAX_BRANCH_DEPTH = 5;
    const SIDEBAR_MAX_VIEWPORT_RATIO = 0.5;
    const BRANCH_DETAIL_HIDE_DELAY_MS = 140;
    const BRANCH_NAME_PHRASES_ZH = {
      "alternatives analysis draft": "备选方案分析草稿",
      "explore alternatives": "探索备选方案",
      "explore payment retry fixes": "排查支付重试修复",
      "import retry bug": "导入重试问题",
      "new branch": "新分支",
      "retry loop hotfix": "重试循环热修复",
      "alternative path": "备选路径",
      "deep dive": "深入分析",
      "verification": "验证分支",
      "writeup": "总结整理",
      "main": "主线",
    };
    const BRANCH_NAME_WORDS_ZH = {
      alternative: "备选",
      alternatives: "备选方案",
      analysis: "分析",
      branch: "分支",
      bug: "问题",
      deep: "深入",
      dive: "分析",
      draft: "草稿",
      explore: "探索",
      failure: "失败",
      fix: "修复",
      fixes: "修复",
      hotfix: "热修复",
      import: "导入",
      loop: "循环",
      main: "主线",
      new: "新",
      path: "路径",
      payment: "支付",
      recovered: "恢复",
      recovery: "恢复",
      retry: "重试",
      upload: "上传",
      verification: "验证",
      verify: "验证",
      writeup: "总结",
    };

    function preferenceButtonElement(group) {
      const buttonId = PREFERENCE_BUTTON_IDS[group];
      return buttonId ? $(buttonId) : null;
    }

    function preferenceValueElement(group) {
      const valueId = PREFERENCE_VALUE_IDS[group];
      return valueId ? $(valueId) : null;
    }

    function preferenceIconElement(group) {
      const iconId = PREFERENCE_ICON_IDS[group];
      return iconId ? $(iconId) : null;
    }

    function preferenceChoices(group) {
      if (group === "language") {
        return LANGUAGE_OPTIONS;
      }
      if (group === "theme") {
        return THEME_OPTIONS;
      }
      if (group === "color") {
        return ACCENT_OPTIONS;
      }
      return [];
    }

    function preferenceGroupLabel(group) {
      if (group === "language") {
        return isChineseUi() ? "语言" : "Language";
      }
      if (group === "theme") {
        return isChineseUi() ? "主题" : "Theme";
      }
      if (group === "color") {
        return isChineseUi() ? "色系" : "Color";
      }
      return "";
    }

    function preferenceValueLabel(group, value) {
      if (group === "language") {
        return value === "zh" ? "中文" : "English";
      }
      if (group === "theme") {
        if (value === "light") {
          return isChineseUi() ? "浅色" : "Light";
        }
        if (value === "dark") {
          return isChineseUi() ? "深色" : "Dark";
        }
        return isChineseUi() ? "跟随系统" : "Follow system";
      }
      if (group === "color") {
        if (value === "white") {
          return isChineseUi() ? "白色" : "White";
        }
        if (value === "mint") {
          return isChineseUi() ? "薄荷" : "Mint";
        }
        if (value === "sunset") {
          return isChineseUi() ? "暮光" : "Sunset";
        }
        if (value === "graphite") {
          return isChineseUi() ? "石墨" : "Graphite";
        }
        return isChineseUi() ? "蓝色" : "Blue";
      }
      return value;
    }

    function loadingModelsLabel() {
      return isChineseUi() ? "加载模型中..." : "Loading models...";
    }

    function chooseModelLabel() {
      return isChineseUi() ? "选择模型" : "Choose a model";
    }

    function modelSelectorLabel() {
      return isChineseUi() ? "模型选择器" : "Model selector";
    }

    function searchModelsLabel() {
      return isChineseUi() ? "搜索模型" : "Search models";
    }

    function noMatchingModelsLabel() {
      return isChineseUi() ? "没有匹配的模型" : "No matching models";
    }

    function modelSelectorHintLabel() {
      return isChineseUi() ? "命令面板" : "command palette";
    }

    function thinkingModeLabel() {
      return isChineseUi() ? "思考模式" : "Thinking mode";
    }

    function thinkingEnabledLabel() {
      return isChineseUi() ? "开启" : "On";
    }

    function thinkingDisabledLabel() {
      return isChineseUi() ? "关闭" : "Off";
    }

    function thinkingAvailableLabel() {
      return isChineseUi() ? "支持思考" : "Thinking available";
    }

    function thinkingDefaultOnLabel() {
      return isChineseUi() ? "支持思考，默认开启" : "Thinking available, default on";
    }

    function thinkingUnavailableLabel() {
      return isChineseUi() ? "不支持思考切换" : "Thinking unavailable";
    }

    function thinkingOnStatusLabel() {
      return isChineseUi() ? "思考已开启" : "Thinking on";
    }

    function thinkingOffStatusLabel() {
      return isChineseUi() ? "思考已关闭" : "Thinking off";
    }

    function providerOptionLabel(provider) {
      if (provider === "moonshot") {
        return "Moonshot AI";
      }
      if (provider === "ollama") {
        return "Ollama";
      }
      if (provider === "anthropic") {
        return "Anthropic";
      }
      return isChineseUi() ? "OpenAI 兼容" : "OpenAI Compatible";
    }

    function providerLogoSlug(provider) {
      if (provider === "moonshot") {
        return "moonshotai";
      }
      if (provider === "ollama") {
        return "ollama";
      }
      if (provider === "anthropic") {
        return "anthropic";
      }
      return "openai";
    }

    function providerLogoLetter(provider) {
      if (provider === "moonshot") {
        return "K";
      }
      if (provider === "ollama") {
        return "O";
      }
      if (provider === "anthropic") {
        return "A";
      }
      return "O";
    }

    function renderProviderLogo(shell, provider) {
      if (!(shell instanceof HTMLElement)) {
        return;
      }
      const fallbackLetter = providerLogoLetter(provider);
      const slug = providerLogoSlug(provider);
      shell.innerHTML = "";
      const img = document.createElement("img");
      img.className = "composer-model-logo";
      img.alt = `${providerOptionLabel(provider)} logo`;
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.src = `https://models.dev/logos/${slug}.svg`;

      const fallback = document.createElement("span");
      fallback.className = "composer-model-logo-fallback";
      fallback.textContent = fallbackLetter;

      img.addEventListener("error", () => {
        img.remove();
      });

      shell.appendChild(img);
      shell.appendChild(fallback);
    }

    function modelOptionLabel(model) {
      if (!model) {
        return "";
      }
      return model.label || `${model.name || model.id} · ${providerOptionLabel(model.provider)}`;
    }

    function providerModels(provider) {
      return state.availableModels.filter((item) => item.provider === provider);
    }

    function availableProviders() {
      return Array.from(new Set((state.availableModels || []).map((item) => item.provider).filter(Boolean)));
    }

    function selectedModelOption() {
      return (state.availableModels || []).find((item) => item.id === state.selectedModel) || null;
    }

    function normalizeThinkingMode(value) {
      const normalized = String(value || "").trim().toLowerCase();
      if (normalized === "enabled" || normalized === "disabled") {
        return normalized;
      }
      return "";
    }

    function modelSupportsThinking(model) {
      return Boolean(model && model.supports_thinking);
    }

    function defaultThinkingModeForModel(model) {
      if (!modelSupportsThinking(model)) {
        return "";
      }
      return model.default_thinking_enabled ? "enabled" : "disabled";
    }

    function pageDefaultThinkingModeForModel(model) {
      if (!modelSupportsThinking(model)) {
        return "";
      }
      return "disabled";
    }

    function effectiveThinkingModeForModel(model, preferredMode = "") {
      if (!modelSupportsThinking(model)) {
        return "";
      }
      return normalizeThinkingMode(preferredMode) || pageDefaultThinkingModeForModel(model);
    }

    function thinkingStatusText(mode) {
      return mode === "enabled" ? thinkingOnStatusLabel() : thinkingOffStatusLabel();
    }

    function thinkingOptionMetaLabel(model) {
      if (!modelSupportsThinking(model)) {
        return thinkingUnavailableLabel();
      }
      return model.default_thinking_enabled ? thinkingDefaultOnLabel() : thinkingAvailableLabel();
    }

    function currentModelSearchValue() {
      return "";
    }

    function isComposerModelPanelOpen() {
      return !$("composer-model-panel").hidden;
    }

    function closeComposerModelPanel({ focusTrigger = false } = {}) {
      const panel = $("composer-model-panel");
      const trigger = $("composer-model-trigger");
      if (panel) {
        panel.hidden = true;
      }
      if (trigger) {
        trigger.setAttribute("aria-expanded", "false");
      }
      if (focusTrigger && trigger instanceof HTMLButtonElement) {
        trigger.focus();
      }
    }

    function openComposerModelPanel() {
      const panel = $("composer-model-panel");
      const trigger = $("composer-model-trigger");
      if (panel) {
        panel.hidden = false;
      }
      if (trigger) {
        trigger.setAttribute("aria-expanded", "true");
      }
      renderModelOptions();
    }

    function toggleComposerModelPanel() {
      if (isComposerModelPanelOpen()) {
        closeComposerModelPanel();
      } else {
        openComposerModelPanel();
      }
    }

    function syncComposerModelLabels() {
      const trigger = $("composer-model-trigger");
      const logo = $("composer-model-trigger-logo");
      const label = $("composer-model-trigger-label");
      const provider = $("composer-model-trigger-provider");
      const selected = selectedModelOption();
      if (trigger) {
        trigger.setAttribute("aria-label", modelSelectorLabel());
        trigger.title = selected ? `${selected.name || selected.id} · ${providerOptionLabel(selected.provider)}` : chooseModelLabel();
      }
      renderProviderLogo(logo, selected?.provider || "openai");
      if (label) {
        label.textContent = selected ? (selected.name || selected.id) : loadingModelsLabel();
      }
      if (provider) {
        provider.textContent = selected
          ? `${providerOptionLabel(selected.provider)} · ${modelSupportsThinking(selected) ? thinkingStatusText(state.selectedThinkingMode) : thinkingUnavailableLabel()}`
          : chooseModelLabel();
      }
      const titleText = document.querySelector(".composer-model-panel-title span");
      if (titleText) {
        titleText.textContent = modelSelectorLabel();
      }
      const title = document.querySelector(".composer-model-panel-title small");
      if (title) {
        title.textContent = modelSelectorHintLabel();
      }
    }

    function syncComposerThinkingUi() {
      const selected = selectedModelOption();
      state.selectedThinkingMode = effectiveThinkingModeForModel(selected, state.selectedThinkingMode);
    }

    function renderModelOptions(filterText = "") {
      const list = $("composer-model-list");
      if (!list) {
        return;
      }
      const normalizedFilter = String(filterText || "").trim().toLowerCase();
      list.innerHTML = "";
      const models = (state.availableModels || []).filter((item) => {
        if (!normalizedFilter) {
          return true;
        }
        const haystack = [
          item.id,
          item.name,
          item.label,
          item.provider,
          item.provider_label,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(normalizedFilter);
      });
      if (!models.length) {
        list.innerHTML = `<div class="composer-model-empty">${noMatchingModelsLabel()}</div>`;
        return;
      }
      for (const provider of availableProviders()) {
        const providerItems = models.filter((item) => item.provider === provider);
        if (!providerItems.length) {
          continue;
        }
        const group = document.createElement("div");
        group.className = "composer-model-group";

        const title = document.createElement("div");
        title.className = "composer-model-group-label";
        title.textContent = providerOptionLabel(provider);
        group.appendChild(title);

        for (const model of providerItems) {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "composer-model-option";
          if (model.id === state.selectedModel) {
            option.classList.add("is-selected");
          }

          const leading = document.createElement("span");
          leading.className = "composer-model-option-leading";

          const logo = document.createElement("span");
          logo.className = "composer-model-logo-shell";
          renderProviderLogo(logo, model.provider);

          const copy = document.createElement("span");
          copy.className = "composer-model-option-copy";

          const optionLabel = document.createElement("span");
          optionLabel.className = "composer-model-option-label";
          optionLabel.textContent = model.name || model.id;

          const optionMeta = document.createElement("span");
          optionMeta.className = "composer-model-option-meta";
          optionMeta.textContent = `${model.provider_label || providerOptionLabel(model.provider)} · ${thinkingOptionMetaLabel(model)}`;

          copy.appendChild(optionLabel);
          copy.appendChild(optionMeta);

          const check = document.createElement("span");
          check.className = "composer-model-check";
          check.textContent = "✓";

          const trailing = document.createElement("span");
          trailing.className = "composer-model-option-trailing";

          if (modelSupportsThinking(model)) {
            const optionThinkingMode = effectiveThinkingModeForModel(
              model,
              model.id === state.selectedModel ? state.selectedThinkingMode : "",
            );
            const toggle = document.createElement("span");
            toggle.className = "composer-model-thinking-toggle";
            toggle.setAttribute("role", "group");
            toggle.setAttribute("aria-label", `${model.name || model.id} ${thinkingModeLabel()}`);

            const enabledButton = document.createElement("button");
            enabledButton.type = "button";
            enabledButton.className = "composer-thinking-button";
            enabledButton.textContent = thinkingEnabledLabel();
            enabledButton.classList.toggle("is-active", optionThinkingMode === "enabled");
            enabledButton.setAttribute("aria-pressed", optionThinkingMode === "enabled" ? "true" : "false");
            enabledButton.addEventListener("click", (event) => {
              event.preventDefault();
              event.stopPropagation();
              applyComposerModelSelection(model.id, { persist: true, thinkingMode: "enabled" });
              closeComposerModelPanel({ focusTrigger: true });
            });

            const disabledButton = document.createElement("button");
            disabledButton.type = "button";
            disabledButton.className = "composer-thinking-button";
            disabledButton.textContent = thinkingDisabledLabel();
            disabledButton.classList.toggle("is-active", optionThinkingMode === "disabled");
            disabledButton.setAttribute("aria-pressed", optionThinkingMode === "disabled" ? "true" : "false");
            disabledButton.addEventListener("click", (event) => {
              event.preventDefault();
              event.stopPropagation();
              applyComposerModelSelection(model.id, { persist: true, thinkingMode: "disabled" });
              closeComposerModelPanel({ focusTrigger: true });
            });

            toggle.appendChild(enabledButton);
            toggle.appendChild(disabledButton);
            trailing.appendChild(toggle);
          }

          leading.appendChild(logo);
          leading.appendChild(copy);
          option.appendChild(leading);
          trailing.appendChild(check);
          option.appendChild(trailing);
          option.addEventListener("click", () => {
            applyComposerModelSelection(model.id, { persist: true });
            closeComposerModelPanel({ focusTrigger: true });
          });
          group.appendChild(option);
        }

        list.appendChild(group);
      }
    }

    function persistModelSelection() {
      if (state.selectedProvider) {
        window.localStorage.setItem(MODEL_PROVIDER_STORAGE_KEY, state.selectedProvider);
      }
      if (state.selectedModel) {
        window.localStorage.setItem(MODEL_ID_STORAGE_KEY, state.selectedModel);
      }
      if (state.selectedThinkingMode) {
        window.localStorage.setItem(THINKING_MODE_STORAGE_KEY, state.selectedThinkingMode);
      } else {
        window.localStorage.removeItem(THINKING_MODE_STORAGE_KEY);
      }
    }

    function applyComposerThinkingSelection(thinkingMode, { persist = true } = {}) {
      const selected = selectedModelOption();
      state.selectedThinkingMode = effectiveThinkingModeForModel(selected, thinkingMode);
      syncComposerThinkingUi();
      syncComposerModelLabels();
      renderModelOptions(currentModelSearchValue());
      if (persist) {
        persistModelSelection();
      }
      return state.selectedThinkingMode;
    }

    function applyComposerModelSelection(modelId, { persist = true, thinkingMode = null } = {}) {
      const selected =
        (state.availableModels || []).find((item) => item.id === modelId) ||
        (state.availableModels || []).find((item) => item.id === state.defaultModelId) ||
        state.availableModels[0] ||
        null;
      if (!selected) {
        syncComposerModelLabels();
        renderModelOptions(currentModelSearchValue());
        return null;
      }
      state.selectedProvider = selected.provider;
      state.selectedModel = selected.id;
      state.selectedThinkingMode = effectiveThinkingModeForModel(
        selected,
        thinkingMode === null ? state.selectedThinkingMode : thinkingMode,
      );
      syncComposerThinkingUi();
      syncComposerModelLabels();
      renderModelOptions(currentModelSearchValue());
      if (persist) {
        persistModelSelection();
      }
      return selected.id;
    }

    async function loadAvailableModels() {
      if (!state.token) await issueToken();
      const response = await fetch(`${apiBase()}/v1/models`, { headers: headers(false) });
      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }
      const payload = await response.json();
      state.availableModels = Array.isArray(payload.models) ? payload.models : [];
      state.defaultModelId = payload.default_model || state.availableModels[0]?.id || null;
      const savedModelId = window.localStorage.getItem(MODEL_ID_STORAGE_KEY);
      const savedThinkingMode = normalizeThinkingMode(window.localStorage.getItem(THINKING_MODE_STORAGE_KEY));
      state.selectedThinkingMode = savedThinkingMode;
      syncComposerModelLabels();
      syncComposerThinkingUi();
      const modelId =
        (savedModelId && state.availableModels.some((item) => item.id === savedModelId) && savedModelId) ||
        state.defaultModelId ||
        state.availableModels[0]?.id ||
        null;
      if (modelId) {
        applyComposerModelSelection(modelId, { persist: false, thinkingMode: savedThinkingMode });
      } else {
        renderModelOptions();
      }
    }

    function preferenceIconMarkup(group, value) {
      if (group === "language") {
        if (value === "zh") {
          return '<svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3.35" y="4.1" width="9.1" height="1.8" rx=".9" fill="currentColor"></rect><rect x="6.95" y="2.75" width="1.8" height="3.9" rx=".9" fill="currentColor"></rect><path d="M10.2 5.85c-.55 2.35-1.98 4.25-4.23 5.66" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"></path><path d="M7.5 8.65c1.06 1.56 2.56 2.88 4.32 3.81" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"></path><rect x="11.7" y="11.7" width="5.1" height="1.8" rx=".9" fill="currentColor"></rect><path d="M14.25 7.15 16.4 15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
        }
        return '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 15.5 8.75 4.5 13.5 15.5" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round"></path><path d="M6.1 10.75h5.3" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round"></path><path d="M15.25 6.25v9.25" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round"></path><path d="M13.25 8.5h4" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round"></path></svg>';
      }
      if (group === "theme") {
        if (value === "light") {
          return '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="3.4" fill="none" stroke="currentColor" stroke-width="1.9"></circle><path d="M10 2.5v2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path><path d="M10 15.5v2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path><path d="M2.5 10h2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path><path d="M15.5 10h2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path><path d="m4.7 4.7 1.4 1.4" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path><path d="m13.9 13.9 1.4 1.4" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path><path d="m13.9 6.1 1.4-1.4" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path><path d="m4.7 15.3 1.4-1.4" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path></svg>';
        }
        if (value === "dark") {
          return '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M14.75 12.9A6.75 6.75 0 0 1 7.1 5.25a6.75 6.75 0 1 0 7.65 7.65Z" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
        }
        return '<svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="4.5" width="14" height="9.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.9"></rect><path d="M7 16h6" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path><path d="M10 14v2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"></path></svg>';
      }
      if (group === "color") {
        if (value === "white") {
          return '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="5.55" fill="none" stroke="currentColor" stroke-width="1.95"></circle><path d="M10 4.1c1.52 2.1 3.8 3.74 6.55 4.7-2.75.96-5.03 2.6-6.55 4.7-1.52-2.1-3.8-3.74-6.55-4.7 2.75-.96 5.03-2.6 6.55-4.7Z" fill="none" stroke="currentColor" stroke-width="1.45" stroke-linejoin="round"></path></svg>';
        }
        if (value === "mint") {
          return '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 16.5c-2.7 0-4.75-2.14-4.75-4.78 0-3.1 3.43-6.49 4.75-8.22 1.32 1.73 4.75 5.12 4.75 8.22 0 2.64-2.05 4.78-4.75 4.78Z" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
        }
        if (value === "sunset") {
          return '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 3.5v13" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round"></path><path d="m6.75 6.75 6.5 6.5" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round"></path><path d="m13.25 6.75-6.5 6.5" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round"></path></svg>';
        }
        if (value === "graphite") {
          return '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 16.25s-5.25-3.03-5.25-7.1a2.98 2.98 0 0 1 5.25-1.95A2.98 2.98 0 0 1 15.25 9.15c0 4.07-5.25 7.1-5.25 7.1Z" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
        }
        return '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 4.25a5.75 5.75 0 1 0 0 11.5h.6a1.65 1.65 0 0 0 1.64-1.64 1.5 1.5 0 0 0-.32-.94 1.39 1.39 0 0 1 1.08-2.27h.75a2.75 2.75 0 0 0 0-5.5H10Z" fill="none" stroke="currentColor" stroke-width="1.95" stroke-linecap="round" stroke-linejoin="round"></path><circle cx="6.9" cy="9" r=".85" fill="currentColor"></circle><circle cx="9.25" cy="6.8" r=".85" fill="currentColor"></circle><circle cx="12.1" cy="7.25" r=".85" fill="currentColor"></circle></svg>';
      }
      return "";
    }

    function nextPreferenceValue(group, currentValue) {
      const values = preferenceChoices(group);
      if (!values.length) {
        return currentValue;
      }
      const currentIndex = values.indexOf(currentValue);
      const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % values.length : 0;
      return values[nextIndex];
    }

    function setPreferenceGroupValue(group, value) {
      const inputId = PREFERENCE_INPUT_IDS[group];
      const input = inputId ? $(inputId) : null;
      if (input) {
        input.value = value;
      }
      const button = preferenceButtonElement(group);
      const valueNode = preferenceValueElement(group);
      const iconNode = preferenceIconElement(group);
      const label = preferenceValueLabel(group, value);
      const groupLabel = preferenceGroupLabel(group);
      if (valueNode) {
        valueNode.textContent = label;
      }
      if (iconNode) {
        iconNode.innerHTML = preferenceIconMarkup(group, value);
      }
      if (!(button instanceof HTMLButtonElement)) {
        return;
      }
      button.dataset.preferenceValue = value;
      const summary = groupLabel ? `${groupLabel}: ${label}` : label;
      button.title = summary;
      button.setAttribute("aria-label", summary);
      button.dataset.fullLabel = summary;
    }

    function bindPreferenceToggle(group, onSelect) {
      const button = preferenceButtonElement(group);
      if (!(button instanceof HTMLButtonElement)) {
        return;
      }
      button.addEventListener("click", () => {
        const inputId = PREFERENCE_INPUT_IDS[group];
        const currentValue = (inputId ? $(inputId)?.value : "") || button.dataset.preferenceValue || preferenceChoices(group)[0];
        onSelect(nextPreferenceValue(group, currentValue));
      });
    }

    function resolveColorMode(preference) {
      if (preference === "light" || preference === "dark") return preference;
      return colorModeQuery.matches ? "dark" : "light";
    }

    function applyColorMode(preference, persist = true) {
      const normalized = preference === "light" || preference === "dark" ? preference : "system";
      state.themePreference = normalized;
      const actual = resolveColorMode(normalized);
      document.documentElement.dataset.theme = actual;
      setPreferenceGroupValue("theme", normalized);
      if (persist) {
        window.localStorage.setItem("focus-agent-theme", normalized);
      }
    }

    function loadColorModePreference() {
      const saved = window.localStorage.getItem("focus-agent-theme") || "system";
      applyColorMode(saved, false);
    }

    function applyAccentTheme(preference, persist = true) {
      const normalized = ACCENT_OPTIONS.includes(preference) ? preference : "white";
      state.accentPreference = normalized;
      document.documentElement.dataset.accent = normalized;
      setPreferenceGroupValue("color", normalized);
      if (persist) {
        window.localStorage.setItem(ACCENT_THEME_KEY, normalized);
      }
    }

    function loadAccentThemePreference() {
      const saved = window.localStorage.getItem(ACCENT_THEME_KEY) || "white";
      applyAccentTheme(saved, false);
    }

    function maxSidebarWidth() {
      return Math.max(
        SIDEBAR_MIN_WIDTH,
        Math.min(Math.floor(window.innerWidth * SIDEBAR_MAX_VIEWPORT_RATIO), window.innerWidth - 320)
      );
    }

    function collapseSidebarLabel() {
      return isChineseUi() ? "收起侧栏" : "Collapse sidebar";
    }

    function showSidebarLabel() {
      return isChineseUi() ? "显示分支树" : "Show branches";
    }

    function isSidebarCollapsed() {
      return $("app-shell").classList.contains("is-sidebar-collapsed");
    }

    function applySidebarCollapsed(isCollapsed, persist = true) {
      const normalized = Boolean(isCollapsed);
      const shell = $("app-shell");
      const toggle = $("toggle-tree");
      const label = $("toggle-tree-label");
      const chatLogoToggle = $("chat-logo-toggle");
      const buttonLabel = collapseSidebarLabel();
      const chatLogoLabel = normalized ? showSidebarLabel() : collapseSidebarLabel();
      shell.classList.toggle("is-sidebar-collapsed", normalized);
      toggle.setAttribute("aria-expanded", String(!normalized));
      toggle.setAttribute("aria-label", buttonLabel);
      toggle.setAttribute("title", buttonLabel);
      label.textContent = buttonLabel;
      chatLogoToggle.setAttribute("aria-expanded", String(!normalized));
      chatLogoToggle.setAttribute("aria-label", chatLogoLabel);
      chatLogoToggle.setAttribute("title", chatLogoLabel);
      chatLogoToggle.classList.toggle("is-sidebar-collapsed", normalized);
      if (persist) {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, normalized ? "1" : "0");
      }
      updateActiveThreadPill();
    }

    function loadSidebarCollapsedPreference() {
      const saved = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
      applySidebarCollapsed(saved === "1", false);
    }

    function toggleSidebarCollapsed() {
      applySidebarCollapsed(!isSidebarCollapsed());
    }

    function applySidebarWidth(width, persist = true) {
      const normalized = Math.min(maxSidebarWidth(), Math.max(SIDEBAR_MIN_WIDTH, Math.round(width)));
      document.documentElement.style.setProperty("--sidebar-width", `${normalized}px`);
      if (persist) {
        window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(normalized));
      }
      scheduleActiveThreadPillRefresh();
    }

    function loadSidebarWidthPreference() {
      const saved = Number.parseInt(window.localStorage.getItem(SIDEBAR_WIDTH_KEY) || "", 10);
      if (Number.isFinite(saved)) {
        applySidebarWidth(saved, false);
      }
    }

    function headers(withJson = true) {
      const base = {};
      if (withJson) base["Content-Type"] = "application/json";
      if (state.token) base["Authorization"] = `Bearer ${state.token}`;
      return base;
    }

    function currentUserId() {
      return DEMO_USER_ID;
    }

    function mainBranchLabel() {
      return isChineseUi() ? "主线" : "Main";
    }

    function defaultThreadId() {
      return `${currentUserId()}-main`;
    }

    function branchLabelForThread(threadId, branchMeta = null) {
      const candidateName = branchMeta?.branch_name;
      if (candidateName) {
        return localizeBranchName(candidateName);
      }
      const node = state.tree ? findNodeByThreadId(state.tree, threadId) : null;
      if (node?.branch_name) {
        return localizeBranchName(node.branch_name);
      }
      const archivedNode = state.archivedBranches.find((item) => item.thread_id === threadId);
      if (archivedNode?.branch_name) {
        return localizeBranchName(archivedNode.branch_name);
      }
      if (threadId === state.rootThreadId || threadId === defaultThreadId()) {
        return mainBranchLabel();
      }
      return isChineseUi() ? "分支对话" : "Branch Chat";
    }

    function pendingBranchCardLabel() {
      return isChineseUi() ? "正在创建分支..." : "Creating branch...";
    }

    function pendingBranchButtonLabel() {
      return isChineseUi() ? "创建中..." : "Creating...";
    }

    function newBranchButtonLabel() {
      return isChineseUi() ? "新建分支" : "New branch";
    }

    function branchDepthLimitLabel() {
      return isChineseUi()
        ? `最多只支持 ${MAX_BRANCH_DEPTH} 层子分支`
        : `Branch depth is limited to ${MAX_BRANCH_DEPTH} levels`;
    }

    function countBranchNodes(node) {
      if (!node) {
        return 0;
      }
      let total = node.branch_id && !node.is_pending ? 1 : 0;
      for (const child of node.children || []) {
        total += countBranchNodes(child);
      }
      return total;
    }

    function treeBranchCountSummaryLabel(activeCount, archivedCount) {
      return isChineseUi()
        ? `进行中 ${activeCount} · 已归档 ${archivedCount}`
        : `In progress ${activeCount} · Archived ${archivedCount}`;
    }

    function updateTreeBranchSummary() {
      const countNode = $("tree-branch-count-summary");
      if (!countNode) {
        return;
      }
      const activeCount = countBranchNodes(state.tree);
      const archivedCount = state.archivedBranches?.length || 0;
      const total = activeCount + archivedCount;
      countNode.textContent = treeBranchCountSummaryLabel(activeCount, archivedCount);
      countNode.title = isChineseUi() ? `共 ${total} 个分支节点` : `${total} total branch nodes`;
    }

    function currentUiLanguage() {
      return isChineseUi() ? "zh" : "en";
    }

    function syncLanguagePicker() {
      setPreferenceGroupValue("language", currentUiLanguage());
    }

    function switchUiLanguage(lang) {
      const nextLang = lang === "zh" ? "zh" : "en";
      const url = new URL(window.location.href);
      url.pathname = "/app";
      if (nextLang === "en") {
        url.searchParams.delete("lang");
      } else {
        url.searchParams.set("lang", nextLang);
      }
      window.location.assign(url.toString());
    }

    function updateBranchCreationUi() {
      const isCreating = Boolean(state.pendingBranch);
      const currentDepth = Number(state.activeBranchMeta?.branch_depth || 0);
      const hitDepthLimit = currentDepth >= MAX_BRANCH_DEPTH;
      const sidebarButton = $("create-branch");
      const toolbarButton = $("composer-create-branch");
      const toolbarLabel = $("composer-create-branch-label");
      const buttonLabel = isCreating ? pendingBranchButtonLabel() : newBranchButtonLabel();
      const actionLabel = hitDepthLimit ? branchDepthLimitLabel() : buttonLabel;
      sidebarButton.disabled = isCreating || hitDepthLimit;
      toolbarButton.disabled = isCreating || hitDepthLimit;
      sidebarButton.textContent = buttonLabel;
      toolbarLabel.textContent = buttonLabel;
      sidebarButton.title = actionLabel;
      sidebarButton.setAttribute("aria-label", actionLabel);
      toolbarButton.title = actionLabel;
      toolbarButton.setAttribute("aria-label", actionLabel);
      toolbarButton.dataset.fullLabel = actionLabel;
    }

    function updateActiveThreadPill(branchMeta = state.activeBranchMeta) {
      const prefix = isChineseUi() ? "当前分支" : "current";
      const baseLabel = `${prefix}: ${branchLabelForThread(state.activeThreadId, branchMeta)}`;
      const text = isSidebarCollapsed() ? `${showSidebarLabel()} · ${baseLabel}` : baseLabel;
      const pill = $("active-thread-pill");
      const trigger = $("focus-branch-tree");
      pill.textContent = text;
      pill.title = text;
      trigger.setAttribute("aria-label", text);
      trigger.dataset.fullLabel = text;
      updatePrepareMergeUi(branchMeta);
      scheduleActiveThreadPillRefresh();
    }

    function syncToolbarTitles() {
      const mainLabel = isChineseUi() ? "回到主分支" : "Back to main";
      const parentLabel = isChineseUi() ? "回到上一层" : "Back one level";
      const languageLabel = isChineseUi() ? "语言" : "Language";
      const themeLabel = isChineseUi() ? "主题" : "Theme";
      const colorLabel = isChineseUi() ? "色系" : "Color";
      const prepareMergeLabel = mergeButtonLabel();
      $("back-to-main").setAttribute("aria-label", mainLabel);
      $("back-to-main").dataset.fullLabel = mainLabel;
      $("back-to-parent").setAttribute("aria-label", parentLabel);
      $("back-to-parent").dataset.fullLabel = parentLabel;
      $("prepare-merge").setAttribute("aria-label", prepareMergeLabel);
      $("prepare-merge").dataset.fullLabel = prepareMergeLabel;
      $("language-select").title = languageLabel;
      $("theme-select").title = themeLabel;
      $("color-select").title = colorLabel;
      setPreferenceGroupValue("language", currentUiLanguage());
      setPreferenceGroupValue("theme", state.themePreference || "system");
      setPreferenceGroupValue("color", state.accentPreference || "white");
      syncComposerModelLabels();
      syncComposerThinkingUi();
      syncBranchCreateModalCopy();
      syncMergeReviewModalCopy();
    }

    let activeThreadPillFrame = 0;

    function buttonLabelIsTruncated(button) {
      if (!(button instanceof HTMLElement)) {
        return false;
      }
      const label = button.querySelector(".toolbar-text");
      if (!(label instanceof HTMLElement)) {
        return false;
      }
      return label.scrollWidth > label.clientWidth + 2;
    }

    function visibleElementWidth(element) {
      if (!(element instanceof HTMLElement) || element.hidden) {
        return 0;
      }
      return Math.ceil(Math.max(element.scrollWidth, element.getBoundingClientRect().width));
    }

    function actionGroupsNeedCompact(actions) {
      if (!(actions instanceof HTMLElement)) {
        return false;
      }
      const groups = Array.from(actions.children).filter(
        (child) => child instanceof HTMLElement && !child.hidden
      );
      if (!groups.length) {
        return false;
      }
      const styles = getComputedStyle(actions);
      const gap = Number.parseFloat(styles.columnGap || styles.gap || "0") || 0;
      const requiredWidth =
        groups.reduce((total, group) => total + visibleElementWidth(group), 0) + gap * Math.max(0, groups.length - 1);
      return requiredWidth > actions.clientWidth + 2;
    }

    function compactButtonsAreClipped(actions, compactButtons) {
      if (!(actions instanceof HTMLElement) || !compactButtons.length) {
        return false;
      }
      const actionsRect = actions.getBoundingClientRect();
      return compactButtons.some((button) => {
        if (!(button instanceof HTMLElement)) {
          return false;
        }
        const rect = button.getBoundingClientRect();
        return rect.left < actionsRect.left - 1 || rect.right > actionsRect.right + 1;
      });
    }

    function refreshActiveThreadPillVisibility() {
      activeThreadPillFrame = 0;
      const actions = document.querySelector(".chat-header-actions");
      if (!actions) {
        return;
      }
      const compactButtons = Array.from(actions.querySelectorAll('[data-compact-button="true"]'));
      actions.classList.remove("is-compact");
      for (const button of compactButtons) {
        delete button.dataset.tooltip;
      }
      const hasTruncatedLabel = compactButtons.some((button) => buttonLabelIsTruncated(button));
      const shouldHideLabel =
        actionGroupsNeedCompact(actions) ||
        compactButtonsAreClipped(actions, compactButtons) ||
        hasTruncatedLabel;
      actions.classList.toggle("is-compact", shouldHideLabel);
      for (const button of compactButtons) {
        const tooltip = button.dataset.fullLabel || button.getAttribute("aria-label") || "";
        if (shouldHideLabel && tooltip) {
          button.dataset.tooltip = tooltip;
        } else {
          delete button.dataset.tooltip;
        }
      }
      if (!shouldHideLabel) {
        hideToolbarTooltip();
      }
    }

    function scheduleActiveThreadPillRefresh() {
      if (activeThreadPillFrame) {
        cancelAnimationFrame(activeThreadPillFrame);
      }
      activeThreadPillFrame = requestAnimationFrame(refreshActiveThreadPillVisibility);
    }

    function currentBranchBadgeLabel() {
      return isChineseUi() ? "当前" : "Current";
    }

    function branchNameFieldLabel() {
      return isChineseUi() ? "分支名称（可选）" : "Branch name (optional)";
    }

    function createBranchDialogTitle() {
      return isChineseUi() ? "创建分支" : "Create branch";
    }

    function createBranchDialogCopy() {
      return isChineseUi()
        ? "填写一个可选分支名即可，后续是否带回上游始终由你决定。"
        : "Choose an optional branch name. You decide later whether to merge its conclusion upstream.";
    }

    function createBranchConfirmLabel() {
      return isChineseUi() ? "创建分支" : "Create branch";
    }

    function generateConclusionButtonLabel() {
      return isChineseUi() ? "生成带回结论" : "Generate conclusion";
    }

    function mergeConclusionButtonLabel() {
      return isChineseUi() ? "合并结论" : "Merge conclusion";
    }

    function mergeButtonLabel(threadId = state.activeThreadId, branchMeta = state.activeBranchMeta) {
      if (
        (state.pendingMergeProposal && state.activeMergeThreadId === threadId) ||
        branchMeta?.branch_status === "preparing_merge_review"
      ) {
        return pendingMergeButtonLabel();
      }
      if (hasReadyMergeProposal(threadId, branchMeta) || branchMeta?.branch_status === "awaiting_merge_review") {
        return mergeConclusionButtonLabel();
      }
      return generateConclusionButtonLabel();
    }

    function mergeReviewTitle() {
      return generateConclusionButtonLabel();
    }

    function mergeReviewCopy() {
      return isChineseUi()
        ? "查看分支总结，选择导入方式，并显式批准或拒绝这次上游导入。"
        : "Review the branch summary, choose an import mode, and explicitly approve or reject the upstream import.";
    }

    function preparingMergeTitle() {
      return isChineseUi() ? "结论生成中..." : "Generating conclusion...";
    }

    function preparingMergeCopy() {
      return isChineseUi()
        ? "正在整理本分支的结论摘要，通常需要几秒钟到一分钟。"
        : "Summarizing this branch now. This can take a few seconds or longer for bigger branches.";
    }

    function pendingMergeButtonLabel() {
      return isChineseUi() ? "结论生成中..." : "Generating...";
    }

    function mergeDecisionFieldLabel() {
      return isChineseUi() ? "审阅决定" : "Decision";
    }

    function mergeSummaryFieldLabel() {
      return isChineseUi() ? "摘要" : "Summary";
    }

    function mergeFindingsFieldLabel() {
      return isChineseUi() ? "关键结论" : "Key findings";
    }

    function mergeOpenQuestionsFieldLabel() {
      return isChineseUi() ? "开放问题" : "Open questions";
    }

    function mergeEvidenceFieldLabel() {
      return isChineseUi() ? "证据引用" : "Evidence refs";
    }

    function mergeModeFieldLabel() {
      return isChineseUi() ? "导入方式" : "Import mode";
    }

    function mergeRationaleFieldLabel() {
      return isChineseUi() ? "审阅备注" : "Rationale";
    }

    function mergeTargetFieldLabel() {
      return isChineseUi() ? "带回目标" : "Merge target";
    }

    function mergeArtifactsFieldLabel() {
      return isChineseUi() ? "选择导入的 artifacts" : "Selected artifacts";
    }

    function mergeCloseLabel() {
      return isChineseUi() ? "关闭" : "Close";
    }

    function mergeSubmitLabel() {
      return isChineseUi() ? "提交决定" : "Submit decision";
    }

    function mergeRegenerateLabel() {
      return isChineseUi() ? "重新生成结论" : "Regenerate conclusion";
    }

    function mergeApproveLabel() {
      return isChineseUi() ? "批准" : "Approve";
    }

    function mergeRejectLabel() {
      return isChineseUi() ? "拒绝" : "Reject";
    }

    function recommendedImportModeLabel(mode) {
      return isChineseUi()
        ? `推荐导入方式：${mergeModeOptionLabel(mode)}`
        : `Recommended import mode: ${mergeModeOptionLabel(mode)}`;
    }

    function mergeModeOptionLabel(mode) {
      const labels = isChineseUi()
        ? {
            summary_only: "仅摘要：只带回结论摘要",
            summary_plus_evidence: "摘要 + 证据：带回摘要和关键证据引用",
            selected_artifacts: "指定 artifacts：只导入你勾选或填写的 artifacts",
          }
        : {
            summary_only: "Summary only - import the conclusion summary only",
            summary_plus_evidence: "Summary + evidence - include key evidence refs",
            selected_artifacts: "Selected artifacts only - import only the artifacts you choose",
          };
      return labels[mode] || mode || "summary_only";
    }

    function mergeTargetOptionLabel(target, branchMeta = state.activeBranchMeta) {
      const upstreamIsMain = branchMeta?.return_thread_id && branchMeta.return_thread_id === branchMeta.root_thread_id;
      const labels = isChineseUi()
        ? {
            return_thread: upstreamIsMain ? "带回到上游（主分支）" : "带回到上游（父分支）",
            root_thread: upstreamIsMain ? "带回到主分支（与上游相同）" : "带回到主分支",
          }
        : {
            return_thread: upstreamIsMain ? "Return upstream (main branch)" : "Return upstream (parent branch)",
            root_thread: upstreamIsMain ? "Return to main branch (same as upstream)" : "Return to main branch",
          };
      return labels[target] || target || "return_thread";
    }

    function noneLabel() {
      return "(none)";
    }

    function threadReadyMessage(threadLabel) {
      return isChineseUi()
        ? `${threadLabel} 已切换完成，可以在这里继续对话。`
        : `${threadLabel} is ready. Continue the conversation here.`;
    }

    function threadLoadingMessage(threadLabel) {
      return isChineseUi()
        ? `正在加载 ${threadLabel} 的对话内容...`
        : `Loading the conversation for ${threadLabel}...`;
    }

    function hasReadyMergeProposal(threadId = state.activeThreadId, branchMeta = state.activeBranchMeta) {
      return Boolean(
        canPrepareMerge(branchMeta) &&
          state.activeMergeThreadId === threadId &&
          state.activeMergeProposal &&
          !state.pendingMergeProposal
      );
    }

    function canPrepareMerge(branchMeta = state.activeBranchMeta) {
      return Boolean(
        branchMeta?.branch_id &&
          !["merged", "discarded", "closed"].includes(String(branchMeta?.branch_status || ""))
      );
    }

    function updatePrepareMergeUi(branchMeta = state.activeBranchMeta) {
      const button = $("prepare-merge");
      if (!button) {
        return;
      }
      const visible = canPrepareMerge(branchMeta);
      const isPending = visible && state.pendingMergeProposal && state.activeMergeThreadId === state.activeThreadId;
      const labelText = visible ? mergeButtonLabel(state.activeThreadId, branchMeta) : generateConclusionButtonLabel();
      button.hidden = !visible;
      button.disabled = !visible || isPending;
      button.title = labelText;
      button.setAttribute("aria-label", labelText);
      button.dataset.fullLabel = labelText;
      const label = button.querySelector(".toolbar-text");
      if (label) {
        label.textContent = labelText;
      }
    }

    function syncModalBackdrop() {
      const backdrop = $("modal-backdrop");
      const anyOpen = !$("branch-create-modal").hidden || !$("merge-review-modal").hidden;
      backdrop.hidden = !anyOpen;
      document.body.classList.toggle("has-modal", anyOpen);
    }

    function closeAllModals({ exceptId = null } = {}) {
      if (exceptId !== "branch-create-modal") {
        $("branch-create-modal").hidden = true;
      }
      if (exceptId !== "merge-review-modal") {
        $("merge-review-modal").hidden = true;
      }
      syncModalBackdrop();
    }

    function openModal(id) {
      closeAllModals({ exceptId: id });
      $(id).hidden = false;
      syncModalBackdrop();
    }

    function closeModal(id) {
      $(id).hidden = true;
      syncModalBackdrop();
    }

    function syncBranchCreateModalCopy() {
      $("branch-create-title").textContent = createBranchDialogTitle();
      $("close-branch-create").setAttribute("aria-label", mergeCloseLabel());
      $("branch-create-modal").querySelector(".focus-modal-copy p").textContent = createBranchDialogCopy();
      $("branch-create-modal").querySelector(".focus-modal-field span").textContent = branchNameFieldLabel();
      $("branch-name-input").placeholder = isChineseUi() ? "留空则自动生成名称" : "Leave blank to auto-generate a name";
      $("branch-create-modal").querySelector(".focus-modal-note").textContent = isChineseUi()
        ? "如果输入区里已有草稿内容，仍会把它当作分支命名的上下文。所有分支后续都可以由你决定是否带回上游。"
        : "The current composer draft will still be sent as branch naming context when available. You decide later whether to merge upstream.";
      $("cancel-branch-create").textContent = mergeCloseLabel();
      $("confirm-branch-create").textContent = createBranchConfirmLabel();
    }

    function syncMergeReviewModalCopy() {
      $("merge-review-title").textContent = mergeReviewTitle();
      $("merge-review-modal").querySelector(".focus-modal-copy p").textContent = mergeReviewCopy();
      $("merge-loading-title").textContent = preparingMergeTitle();
      $("merge-loading-copy").textContent = preparingMergeCopy();
      $("merge-summary-heading").textContent = mergeSummaryFieldLabel();
      $("merge-findings-heading").textContent = mergeFindingsFieldLabel();
      $("merge-open-questions-heading").textContent = mergeOpenQuestionsFieldLabel();
      $("merge-evidence-heading").textContent = mergeEvidenceFieldLabel();
      $("merge-artifacts-heading").textContent = isChineseUi() ? "Artifacts" : "Artifacts";
      $("merge-summary-label").textContent = mergeSummaryFieldLabel();
      $("merge-findings-label").textContent = mergeFindingsFieldLabel();
      $("merge-open-questions-label").textContent = mergeOpenQuestionsFieldLabel();
      $("merge-evidence-label").textContent = mergeEvidenceFieldLabel();
      $("merge-artifacts-label").textContent = isChineseUi() ? "Artifacts" : "Artifacts";
      $("close-merge-review").setAttribute("aria-label", mergeCloseLabel());
      $("cancel-merge-review").textContent = mergeCloseLabel();
      $("regenerate-merge-review").textContent = mergeRegenerateLabel();
      $("submit-merge-review").textContent = mergeSubmitLabel();
      $("merge-decision-select").previousElementSibling.textContent = mergeDecisionFieldLabel();
      $("merge-mode-select").previousElementSibling.textContent = mergeModeFieldLabel();
      $("merge-target-select").previousElementSibling.textContent = mergeTargetFieldLabel();
      $("merge-rationale").previousElementSibling.textContent = mergeRationaleFieldLabel();
      $("merge-selected-artifacts").previousElementSibling.textContent = mergeArtifactsFieldLabel();
      $("merge-rationale").placeholder = isChineseUi() ? "可选的审阅备注" : "Optional reviewer notes";
      $("merge-selected-artifacts").placeholder = isChineseUi()
        ? "每行输入一个 artifact 路径或 id"
        : "Enter one artifact path or id per line";
      $("merge-proposal-summary").placeholder = isChineseUi()
        ? "可在合并前修改这段摘要"
        : "Edit the summary before merging";
      $("merge-proposal-findings").placeholder = isChineseUi()
        ? "每行输入一条关键结论"
        : "One finding per line";
      $("merge-proposal-open-questions").placeholder = isChineseUi()
        ? "每行输入一条开放问题"
        : "One open question per line";
      $("merge-proposal-evidence").placeholder = isChineseUi()
        ? "每行输入一条证据引用"
        : "One evidence ref per line";
      $("merge-proposal-artifacts").placeholder = isChineseUi()
        ? "每行输入一个 artifact 路径或 id"
        : "One artifact path or id per line";
      $("merge-decision-select").options[0].textContent = mergeApproveLabel();
      $("merge-decision-select").options[1].textContent = mergeRejectLabel();
      $("merge-mode-select").options[0].textContent = mergeModeOptionLabel("summary_only");
      $("merge-mode-select").options[1].textContent = mergeModeOptionLabel("summary_plus_evidence");
      $("merge-mode-select").options[2].textContent = mergeModeOptionLabel("selected_artifacts");
      $("merge-target-select").options[0].textContent = mergeTargetOptionLabel("return_thread");
      $("merge-target-select").options[1].textContent = mergeTargetOptionLabel("root_thread");
    }

    function syncDefaultThreadIds() {
      const fallback = defaultThreadId();
      if (!state.rootThreadId || state.rootThreadId === "main-1") {
        state.rootThreadId = fallback;
      }
      if (!state.activeThreadId || state.activeThreadId === "main-1") {
        state.activeThreadId = fallback;
      }
      updateActiveThreadPill();
    }

    async function readErrorMessage(response) {
      const raw = await response.text();
      if (!raw) return `HTTP ${response.status}`;
      try {
        const payload = JSON.parse(raw);
        return payload.detail || payload.message || raw;
      } catch {
        return raw;
      }
    }

    function showUiError(title, message) {
      clearAgentActivityBubble();
      setStatus(title, "danger");
      createMessageBubble("system", `${title}: ${message}`, "System", "error");
    }

    function createThreadUiState() {
      return {
        statusFeed: [],
        currentStatusText: "",
        currentStatusKind: "",
        currentStatusDetail: "",
        activityMeta: "",
        showActivity: false,
      };
    }

    function getThreadUiState(threadId) {
      if (!threadId) {
        return null;
      }
      if (!state.threadUiById[threadId]) {
        state.threadUiById[threadId] = createThreadUiState();
      }
      return state.threadUiById[threadId];
    }

    function cloneStatusFeed(items) {
      return (items || []).map((item) => ({
        text: item.text,
        kind: item.kind,
        detail: item.detail,
      }));
    }

    function syncVisibleThreadUiState(threadId = state.activeThreadId) {
      const snapshot = getThreadUiState(threadId);
      if (!snapshot) {
        return;
      }
      snapshot.statusFeed = cloneStatusFeed(state.statusFeed);
      snapshot.currentStatusText = state.currentStatusText;
      snapshot.currentStatusKind = state.currentStatusKind;
      snapshot.currentStatusDetail = state.currentStatusDetail;
      snapshot.activityMeta = state.currentActivityMeta;
      snapshot.showActivity = Boolean(state.activityBubble);
    }

    function clearThreadUiState(threadId) {
      const snapshot = getThreadUiState(threadId);
      if (!snapshot) {
        return;
      }
      snapshot.statusFeed = [];
      snapshot.currentStatusText = "";
      snapshot.currentStatusKind = "";
      snapshot.currentStatusDetail = "";
      snapshot.activityMeta = "";
      snapshot.showActivity = false;
      if (threadId === state.activeThreadId) {
        state.statusFeed = [];
        state.currentStatusText = "";
        state.currentStatusKind = "";
        state.currentStatusDetail = "";
        state.currentActivityMeta = "";
      }
    }

    function restoreThreadUiState(threadId) {
      const snapshot = getThreadUiState(threadId);
      if (!snapshot || !snapshot.showActivity || !snapshot.activityMeta) {
        return;
      }
      state.statusFeed = cloneStatusFeed(snapshot.statusFeed);
      state.currentStatusText = snapshot.currentStatusText;
      state.currentStatusKind = snapshot.currentStatusKind;
      state.currentStatusDetail = snapshot.currentStatusDetail;
      state.currentActivityMeta = snapshot.activityMeta;
      createAgentActivityBubble(snapshot.activityMeta, threadId);
    }

    function unknownErrorLabel() {
      return isChineseUi() ? "未知错误" : "unknown error";
    }

    function extractNestedProviderMessage(message) {
      const raw = String(message || "").trim();
      if (!raw) {
        return "";
      }
      const patterns = [
        /["']message["']\\s*:\\s*["']([^"']+)["']/i,
        /message\\s*=\\s*["']([^"']+)["']/i,
      ];
      for (const pattern of patterns) {
        const match = raw.match(pattern);
        if (match && match[1]) {
          return String(match[1]).trim();
        }
      }
      return "";
    }

    function isModelOverloadedMessage(message) {
      const raw = String(message || "").trim().toLowerCase();
      if (!raw) {
        return false;
      }
      return (
        raw.includes("engine_overloaded") ||
        raw.includes("currently overloaded") ||
        raw.includes("rate limit") ||
        raw.includes("too many requests") ||
        raw.includes("error code: 429") ||
        raw.includes("status code 429")
      );
    }

    function selectedModelFailureLabel() {
      const selected =
        (state.availableModels || []).find((item) => item.id === state.selectedModel) || null;
      return selected?.name || state.selectedModel || "";
    }

    function turnFailedLabel() {
      return isChineseUi() ? "执行失败" : "failed";
    }

    function overloadedModelLabel() {
      return isChineseUi() ? "模型服务繁忙" : "model overloaded";
    }

    function turnFailedBubbleText(message) {
      const normalizedMessage = String(message || "").trim() || unknownErrorLabel();
      if (isModelOverloadedMessage(normalizedMessage)) {
        const detail = extractNestedProviderMessage(normalizedMessage) || normalizedMessage;
        const modelName = selectedModelFailureLabel();
        if (isChineseUi()) {
          return [
            "当前模型服务繁忙，暂时无法完成这轮对话。",
            modelName ? `模型：${modelName}` : "",
            "建议稍后重试，或切换到其他模型后再发送。",
            detail ? `详情：${detail}` : "",
          ]
            .filter(Boolean)
            .join("\\n\\n");
        }
        return [
          "The selected model is temporarily overloaded and could not finish this turn.",
          modelName ? `Model: ${modelName}` : "",
          "Please retry in a moment, or switch to another model and send again.",
          detail ? `Details: ${detail}` : "",
        ]
          .filter(Boolean)
          .join("\\n\\n");
      }
      return isChineseUi()
        ? `本轮执行失败\\n\\n${normalizedMessage}`
        : `This turn failed.\\n\\n${normalizedMessage}`;
    }

    function presentTurnFailure(payload) {
      const message = String(payload?.message || payload?.error || unknownErrorLabel()).trim() || unknownErrorLabel();
      const statusLabel = isModelOverloadedMessage(message) ? overloadedModelLabel() : turnFailedLabel();
      setStatus(statusLabel, "danger", message);
      clearThreadUiState(state.activeThreadId);
      clearAgentActivityBubble();
      createMessageBubble("system", turnFailedBubbleText(message), isChineseUi() ? "系统" : "System", "error");
      if (state.currentAssistantBubble && !bubbleRawText(state.currentAssistantBubble)) {
        setBubbleContent(state.currentAssistantBubble, message);
      }
    }

    function renderModalList(id, items) {
      const root = $(id);
      root.innerHTML = "";
      const normalized = (items || []).filter((item) => String(item || "").trim());
      if (!normalized.length) {
        root.innerHTML = `<li>${noneLabel()}</li>`;
        return;
      }
      for (const item of normalized) {
        const li = document.createElement("li");
        li.textContent = String(item);
        root.appendChild(li);
      }
    }

    async function openBranchCreateModal() {
      if (state.pendingBranch) {
        return;
      }
      await createBranch();
    }

    function closeBranchCreateModal() {
      closeModal("branch-create-modal");
    }

    function openMergeReviewModal(proposal, threadId) {
      state.activeMergeProposal = proposal;
      state.activeMergeThreadId = threadId;
      state.pendingMergeProposal = false;
      syncMergeReviewModalCopy();
      $("merge-proposal-summary").value = String(proposal?.summary || "");
      $("merge-proposal-findings").value = (proposal?.key_findings || []).join("\\\\n");
      $("merge-proposal-open-questions").value = (proposal?.open_questions || []).join("\\\\n");
      $("merge-proposal-evidence").value = (proposal?.evidence_refs || []).join("\\\\n");
      $("merge-proposal-artifacts").value = (proposal?.artifacts || []).join("\\\\n");
      $("merge-proposal-recommended-mode").textContent = recommendedImportModeLabel(
        proposal?.recommended_import_mode || "summary_only"
      );
      $("merge-decision-select").value = "approve";
      $("merge-mode-select").value = proposal?.recommended_import_mode || "summary_only";
      $("merge-target-select").value = "return_thread";
      $("merge-selected-artifacts").value = "";
      $("merge-rationale").value = "";
      updateMergeArtifactsField();
      $("merge-review-loading").hidden = true;
      $("merge-review-content").hidden = false;
      updatePrepareMergeUi();
      openModal("merge-review-modal");
      window.setTimeout(() => $("merge-proposal-summary").focus(), 0);
    }

    function openMergeReviewLoadingModal(threadId) {
      state.activeMergeProposal = null;
      state.activeMergeThreadId = threadId;
      state.pendingMergeProposal = true;
      syncMergeReviewModalCopy();
      $("merge-loading-title").textContent = preparingMergeTitle();
      $("merge-loading-copy").textContent = preparingMergeCopy();
      $("merge-review-loading").hidden = false;
      $("merge-review-content").hidden = true;
      updatePrepareMergeUi();
      openModal("merge-review-modal");
      window.setTimeout(() => $("close-merge-review").focus(), 0);
    }

    function closeMergeReviewModal() {
      state.mergeReviewRequestId += 1;
      if (state.pendingMergeProposal) {
        state.activeMergeProposal = null;
        state.activeMergeThreadId = null;
      }
      state.pendingMergeProposal = false;
      $("merge-review-loading").hidden = true;
      $("merge-review-content").hidden = false;
      updatePrepareMergeUi();
      closeModal("merge-review-modal");
    }

    function updateMergeArtifactsField() {
      const shouldShow =
        $("merge-decision-select").value === "approve" && $("merge-mode-select").value === "selected_artifacts";
      $("merge-selected-artifacts-row").hidden = !shouldShow;
    }

    function parseLineList(value) {
      return String(value || "")
        .split(/\\n+/)
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function idleStatusLabel() {
      return isChineseUi() ? "空闲" : "idle";
    }

    function idleStatusDetail() {
      return isChineseUi()
        ? "等待你的下一条消息。Agent 的运行进度和工具调用会实时显示在这里。"
        : "Ready for your next prompt. Live agent progress and tool activity will appear here.";
    }

    function agentRunTitle() {
      return isChineseUi() ? "Agent 正在运行" : "Agent is working";
    }

    function agentRunDetail() {
      return isChineseUi()
        ? "思考、规划和工具调用会先显示在这里，正式回复生成后会自动切换。"
        : "Thinking, planning, and tool activity appear here first, then switch to the final answer automatically.";
    }

    function statusDetailFor(text) {
      const value = String(text || "").trim();
      if (!value || value === idleStatusLabel()) {
        return idleStatusDetail();
      }
      return value;
    }

    function clearAgentActivityBubble() {
      if (state.activityRow) {
        state.activityRow.remove();
      }
      state.activityRow = null;
      state.activityBubble = null;
      state.currentActivityMeta = "";
    }

    function renderAgentActivityBubble() {
      const bubble = state.activityBubble;
      if (!bubble) {
        return;
      }
      const currentLabel = state.currentStatusText || (isChineseUi() ? "连接中" : "connecting");
      const currentKind = state.currentStatusKind || "warn";
      bubble.className = `message-bubble agent-run-bubble ${currentKind}`.trim();
      bubble.innerHTML = "";

      const head = document.createElement("div");
      head.className = "agent-run-head";

      const pulse = document.createElement("span");
      pulse.className = "agent-run-pulse";
      head.appendChild(pulse);

      const copy = document.createElement("div");
      copy.className = "agent-run-copy";

      const title = document.createElement("div");
      title.className = "agent-run-title";
      title.textContent = currentLabel;
      copy.appendChild(title);

      const detail = document.createElement("div");
      detail.className = "agent-run-detail";
      detail.textContent = state.currentStatusDetail || agentRunDetail();
      copy.appendChild(detail);

      head.appendChild(copy);
      bubble.appendChild(head);

      const steps = document.createElement("div");
      steps.className = "agent-run-steps";
      const items = state.statusFeed.length
        ? state.statusFeed.slice(0, 4)
        : [{ text: currentLabel, kind: currentKind }];

      for (const item of items) {
        const row = document.createElement("div");
        row.className = `agent-run-step ${item.kind || ""}`.trim();

        const dot = document.createElement("span");
        dot.className = "agent-run-step-dot";
        row.appendChild(dot);

        const text = document.createElement("span");
        text.textContent = item.text;
        row.appendChild(text);

        steps.appendChild(row);
      }
      bubble.appendChild(steps);
    }

    function createAgentActivityBubble(meta, threadId = state.activeThreadId) {
      const snapshot = getThreadUiState(threadId);
      if (snapshot) {
        snapshot.activityMeta = meta;
        snapshot.showActivity = true;
      }
      if (threadId !== state.activeThreadId) {
        return null;
      }
      clearAgentActivityBubble();
      removeChatEmptyState();
      const shouldFollow = shouldAutoFollowChat();
      const row = document.createElement("div");
      row.className = "message-row activity";

      const metaLine = document.createElement("div");
      metaLine.className = "message-meta";
      metaLine.textContent = meta;

      const bubble = document.createElement("div");
      bubble.className = "message-bubble agent-run-bubble warn";

      row.appendChild(metaLine);
      row.appendChild(bubble);
      $("chat-history").appendChild(row);

      state.activityRow = row;
      state.activityBubble = bubble;
      state.currentActivityMeta = meta;
      renderAgentActivityBubble();
      if (shouldFollow) {
        scrollChatToBottom();
      }
      syncVisibleThreadUiState(threadId);
      return bubble;
    }

    function ensureAssistantBubble(threadLabel) {
      if (state.currentAssistantBubble) {
        return state.currentAssistantBubble;
      }
      clearThreadUiState(state.activeThreadId);
      clearAgentActivityBubble();
      state.currentAssistantBubble = createMessageBubble("assistant", "", `Focus Agent · ${threadLabel}`);
      return state.currentAssistantBubble;
    }

    function setStatus(
      text,
      kind = "",
      detailOverride = null,
      threadId = state.activeThreadId,
      options = {},
    ) {
      const recordInActivity = options.recordInActivity !== false;
      const value = String(text || "").trim() || idleStatusLabel();
      const detail = detailOverride == null ? statusDetailFor(value) : String(detailOverride || "").trim() || statusDetailFor(value);
      const snapshot = getThreadUiState(threadId);
      if (threadId === state.activeThreadId && state.activityBubble) {
        const changed =
          value !== state.currentStatusText ||
          kind !== state.currentStatusKind ||
          detail !== state.currentStatusDetail;
        state.currentStatusText = value;
        state.currentStatusKind = kind;
        state.currentStatusDetail = detail;
        if (!changed) {
          return;
        }
        if (recordInActivity) {
          state.statusFeed.unshift({
            text: value,
            kind,
            detail,
          });
          if (state.statusFeed.length > 4) {
            state.statusFeed.length = 4;
          }
        }
        renderAgentActivityBubble();
        syncVisibleThreadUiState(threadId);
        return;
      }
      if (!snapshot || !snapshot.showActivity) {
        return;
      }
      const changed =
        value !== snapshot.currentStatusText ||
        kind !== snapshot.currentStatusKind ||
        detail !== snapshot.currentStatusDetail;
      snapshot.currentStatusText = value;
      snapshot.currentStatusKind = kind;
      snapshot.currentStatusDetail = detail;
      if (!changed) {
        return;
      }
      if (!recordInActivity) {
        return;
      }
      snapshot.statusFeed.unshift({
        text: value,
        kind,
        detail,
      });
      if (snapshot.statusFeed.length > 4) {
        snapshot.statusFeed.length = 4;
      }
    }

    function removeChatEmptyState() {
      const empty = $("chat-empty");
      if (empty) empty.remove();
    }

    function scrollChatToBottom() {
      const history = $("chat-history");
      if (!history) {
        return;
      }
      history.scrollTop = history.scrollHeight;
      state.chatAutoFollow = true;
      state.chatLastScrollTop = history.scrollTop;
    }

    function isChatNearBottom(threshold = 48) {
      const history = $("chat-history");
      if (!history) {
        return true;
      }
      return history.scrollHeight - history.scrollTop - history.clientHeight <= threshold;
    }

    function shouldAutoFollowChat({ forceScroll = false } = {}) {
      if (forceScroll) {
        return true;
      }
      if (state.streamingResponseActive) {
        return state.chatAutoFollow;
      }
      return state.chatAutoFollow || isChatNearBottom();
    }

    function syncChatAutoFollowFromScroll() {
      const history = $("chat-history");
      if (!history) {
        state.chatAutoFollow = true;
        state.chatLastScrollTop = 0;
        return;
      }
      const currentTop = history.scrollTop;
      if (isChatNearBottom(12)) {
        state.chatAutoFollow = true;
      } else if (currentTop < state.chatLastScrollTop) {
        state.chatAutoFollow = false;
      }
      state.chatLastScrollTop = currentTop;
    }

    function pauseChatAutoFollow() {
      state.chatAutoFollow = false;
    }

    function handleChatWheel(event) {
      if (state.streamingResponseActive) {
        pauseChatAutoFollow();
      }
    }

    function handleChatTouchStart(event) {
      const touch = event.touches && event.touches[0];
      state.chatTouchY = touch ? touch.clientY : null;
      if (state.streamingResponseActive) {
        pauseChatAutoFollow();
      }
    }

    function handleChatTouchMove(event) {
      const touch = event.touches && event.touches[0];
      if (!touch) {
        return;
      }
      if (state.chatTouchY != null && touch.clientY > state.chatTouchY) {
        pauseChatAutoFollow();
      }
      state.chatTouchY = touch.clientY;
    }

    function handleChatTouchEnd() {
      state.chatTouchY = null;
    }

    function escapeHtml(text) {
      return String(text || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function renderInlineCode(text) {
      return String(text || "")
        .split(/(`[^`]+`)/g)
        .map((part) => {
          if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
            return `<code class="message-inline-code">${escapeHtml(part.slice(1, -1))}</code>`;
          }
          return escapeHtml(part);
        })
        .join("");
    }

    function applyInlineMarkdown(html) {
      return String(html || "")
        .replace(/(\\*\\*|__)(.+?)\\1/g, "<strong>$2</strong>")
        .replace(/(^|[^\\w])\\*([^*\\n]+)\\*(?!\\*)/g, "$1<em>$2</em>")
        .replace(/(^|[^\\w])_([^_\\n]+)_(?!_)/g, "$1<em>$2</em>")
        .replace(/~~(.+?)~~/g, "<del>$1</del>");
    }

    function stashInlineToken(tokens, html) {
      const marker = `@@MDTOKEN${tokens.length}@@`;
      tokens.push({ marker, html });
      return marker;
    }

    function restoreInlineTokens(text, tokens) {
      let restored = String(text || "");
      for (const token of tokens) {
        restored = restored.replaceAll(token.marker, token.html);
      }
      return restored;
    }

    function sanitizeMessageHref(rawHref) {
      const value = String(rawHref || "").trim();
      if (!value) {
        return "";
      }
      try {
        const parsed = new URL(value, window.location.origin);
        const protocol = parsed.protocol.toLowerCase();
        if (protocol === "http:" || protocol === "https:" || protocol === "mailto:") {
          return parsed.href;
        }
      } catch {}
      return "";
    }

    function renderInlineMarkdown(text) {
      const tokens = [];
      let working = String(text || "");
      working = working.replace(/`([^`]+)`/g, (_, codeText) =>
        stashInlineToken(tokens, `<code class="message-inline-code">${escapeHtml(codeText)}</code>`)
      );
      working = working.replace(/\\[([^\\]]+)\\]\\(([^\\s)]+)\\)/g, (match, label, href) => {
        const safeHref = sanitizeMessageHref(href);
        if (!safeHref) {
          return match;
        }
        const linkHtml = `<a class="message-link" href="${escapeHtml(safeHref)}" target="_blank" rel="noreferrer noopener">${applyInlineMarkdown(escapeHtml(label))}</a>`;
        return stashInlineToken(tokens, linkHtml);
      });
      const formatted = applyInlineMarkdown(escapeHtml(working));
      return restoreInlineTokens(formatted, tokens);
    }

    function appendParagraph(parent, text) {
      const paragraph = document.createElement("p");
      paragraph.innerHTML = renderInlineMarkdown(text).replaceAll("\\n", "<br>");
      parent.appendChild(paragraph);
    }

    function appendList(parent, lines, ordered) {
      const list = document.createElement(ordered ? "ol" : "ul");
      const pattern = ordered ? /^\\s*\\d+\\.\\s+(.*)$/ : /^\\s*[-*+]\\s+(.*)$/;
      for (const line of lines) {
        const match = line.match(pattern);
        if (!match) {
          continue;
        }
        const item = document.createElement("li");
        item.innerHTML = renderInlineMarkdown(match[1]);
        list.appendChild(item);
      }
      if (list.childElementCount) {
        parent.appendChild(list);
      }
    }

    function appendBlockquote(parent, lines) {
      const quote = document.createElement("blockquote");
      appendPlainText(
        quote,
        lines
          .map((line) => line.replace(/^\\s*>\\s?/, ""))
          .join("\\n")
      );
      if (quote.childElementCount) {
        parent.appendChild(quote);
      }
    }

    function appendMarkdownBlock(parent, block) {
      const value = String(block || "").trim();
      if (!value) {
        return;
      }
      if (/^([-*_])(?:\\s*\\1){2,}\\s*$/.test(value)) {
        parent.appendChild(document.createElement("hr"));
        return;
      }
      const lines = value.split("\\n");
      if (lines.length === 1) {
        const heading = value.match(/^(#{1,6})\\s+(.*)$/);
        if (heading) {
          const level = Math.min(heading[1].length, 6);
          const node = document.createElement(`h${level}`);
          node.innerHTML = renderInlineMarkdown(heading[2]);
          parent.appendChild(node);
          return;
        }
      }
      if (lines.every((line) => /^\\s*>\\s?/.test(line))) {
        appendBlockquote(parent, lines);
        return;
      }
      if (lines.every((line) => /^\\s*[-*+]\\s+/.test(line))) {
        appendList(parent, lines, false);
        return;
      }
      if (lines.every((line) => /^\\s*\\d+\\.\\s+/.test(line))) {
        appendList(parent, lines, true);
        return;
      }
      appendParagraph(parent, value);
    }

    function appendPlainText(fragment, text) {
      const value = String(text || "");
      if (!value.trim()) {
        return;
      }
      for (const block of value.split(/\\n{2,}/)) {
        if (!block.trim()) {
          continue;
        }
        appendMarkdownBlock(fragment, block);
      }
    }

    function codeBlockLabel(language) {
      const normalized = String(language || "").trim();
      if (normalized) {
        return normalized;
      }
      return isChineseUi() ? "代码" : "Code";
    }

    function codeCopyLabel() {
      return isChineseUi() ? "复制" : "Copy";
    }

    function codeCopiedLabel() {
      return isChineseUi() ? "已复制" : "Copied";
    }

    function codeCopyFailedLabel() {
      return isChineseUi() ? "复制失败" : "Copy failed";
    }

    function autoResizeComposerInput() {
      const input = $("stream-message");
      if (!input) {
        return;
      }
      const computed = window.getComputedStyle(input);
      const lineHeight = Number.parseFloat(computed.lineHeight) || 17;
      const configuredMinHeight = Number.parseFloat(computed.minHeight) || 0;
      const minHeight = Math.max(Math.ceil(lineHeight), Math.ceil(configuredMinHeight));
      const maxHeight = Math.max(minHeight, 136);
      input.style.height = "0px";
      const nextHeight = Math.min(Math.max(input.scrollHeight, minHeight), maxHeight);
      input.style.height = `${nextHeight}px`;
      input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
    }

    function shouldSubmitComposerOnEnter(event) {
      return (
        event.key === "Enter" &&
        !event.shiftKey &&
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.isComposing &&
        event.keyCode !== 229
      );
    }

    async function copyTextToClipboard(text) {
      const value = String(text || "");
      if (!value) {
        return true;
      }
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(value);
        return true;
      }

      const helper = document.createElement("textarea");
      helper.value = value;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      helper.style.pointerEvents = "none";
      document.body.appendChild(helper);
      helper.focus();
      helper.select();
      const copied = document.execCommand("copy");
      helper.remove();
      return copied;
    }

    function buildMessageContent(text) {
      const fragment = document.createDocumentFragment();
      const value = String(text || "");
      const pattern = /```([a-zA-Z0-9_+#.-]*)\\n?([\\s\\S]*?)```/g;
      let lastIndex = 0;
      for (const match of value.matchAll(pattern)) {
        const [rawBlock, language = "", codeText = ""] = match;
        const startIndex = match.index || 0;
        appendPlainText(fragment, value.slice(lastIndex, startIndex));

        const block = document.createElement("div");
        block.className = "message-code-block";
        const header = document.createElement("div");
        header.className = "message-code-header";

        const label = document.createElement("span");
        label.className = "message-code-label";
        label.textContent = codeBlockLabel(language);
        header.appendChild(label);

        const copyButton = document.createElement("button");
        copyButton.type = "button";
        copyButton.className = "code-copy-button";
        copyButton.textContent = codeCopyLabel();
        copyButton.setAttribute("aria-label", `${codeCopyLabel()} ${codeBlockLabel(language)}`);
        copyButton.addEventListener("click", async () => {
          const originalLabel = codeCopyLabel();
          try {
            await copyTextToClipboard(codeText.replace(/\\n$/, ""));
            copyButton.textContent = codeCopiedLabel();
            copyButton.classList.add("is-copied");
          } catch {
            copyButton.textContent = codeCopyFailedLabel();
            copyButton.classList.remove("is-copied");
          }
          if (copyButton._copyLabelTimer) {
            window.clearTimeout(copyButton._copyLabelTimer);
          }
          copyButton._copyLabelTimer = window.setTimeout(() => {
            copyButton.textContent = originalLabel;
            copyButton.classList.remove("is-copied");
            copyButton._copyLabelTimer = null;
          }, 1400);
        });
        header.appendChild(copyButton);
        block.appendChild(header);

        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeText.replace(/\\n$/, "");
        pre.appendChild(code);
        block.appendChild(pre);
        fragment.appendChild(block);

        lastIndex = startIndex + rawBlock.length;
      }
      appendPlainText(fragment, value.slice(lastIndex));
      return fragment;
    }

    function setBubbleContent(bubble, text) {
      bubble.dataset.rawText = String(text || "");
      bubble.replaceChildren(buildMessageContent(text));
    }

    function bubbleRawText(bubble) {
      if (!bubble) {
        return "";
      }
      return bubble.dataset.rawText || "";
    }

    function createMessageBubble(role, text, meta, tone = "", forceScroll = false) {
      removeChatEmptyState();
      const shouldFollow = shouldAutoFollowChat({ forceScroll });
      const row = document.createElement("div");
      row.className = `message-row ${role}`;
      if (tone) {
        row.classList.add(tone);
      }

      const metaLine = document.createElement("div");
      metaLine.className = "message-meta";
      metaLine.textContent = meta;

      const bubble = document.createElement("div");
      bubble.className = "message-bubble";
      setBubbleContent(bubble, text);

      row.appendChild(metaLine);
      row.appendChild(bubble);
      $("chat-history").appendChild(row);
      if (shouldFollow) {
        scrollChatToBottom();
      }
      return bubble;
    }

    function resetChatHistory(message = "Start chatting here. Branches appear on the left whenever the agent forks work.") {
      $("chat-history").innerHTML = `<div id="chat-empty" class="chat-empty">${message}</div>`;
      clearAgentActivityBubble();
      state.currentAssistantBubble = null;
      state.currentVisibleText = "";
      state.statusFeed = [];
      state.chatAutoFollow = true;
      state.chatLastScrollTop = 0;
    }

    function renderThreadMessages(messages, threadId) {
      const history = $("chat-history");
      history.innerHTML = "";
      clearAgentActivityBubble();
      state.currentAssistantBubble = null;
      state.statusFeed = [];
      state.chatAutoFollow = true;
      state.chatLastScrollTop = 0;
      let rendered = 0;
      const threadLabel = branchLabelForThread(threadId, state.activeThreadId === threadId ? state.activeBranchMeta : null);
      for (const message of messages || []) {
        const messageType = String(message.type || "").toLowerCase();
        const content = String(message.content || "").trim();
        if (!content) {
          continue;
        }
        if (messageType === "human") {
          createMessageBubble("user", content, `You · ${threadLabel}`);
          rendered += 1;
          continue;
        }
        if (messageType === "ai") {
          createMessageBubble("assistant", content, `Focus Agent · ${threadLabel}`);
          rendered += 1;
          continue;
        }
        if (messageType === "system") {
          createMessageBubble("system", content, `${isChineseUi() ? "系统" : "System"} · ${threadLabel}`, "success");
          rendered += 1;
          continue;
        }
      }
      if (!rendered) {
        resetChatHistory(threadReadyMessage(threadLabel));
      }
    }

    function beginChatTurn() {
      const threadId = state.activeThreadId;
      const message = $("stream-message").value.trim();
      const threadLabel = branchLabelForThread(threadId, state.activeBranchMeta);
      state.lastUserMessage = message;
      state.currentAssistantBubble = null;
      clearThreadUiState(threadId);
      createMessageBubble("user", message, `You · ${threadLabel}`, "", true);
      createAgentActivityBubble(`Focus Agent · ${threadLabel}`, threadId);
      state.loadedThreadId = threadId;
    }

    async function selectThread(threadId) {
      state.activeThreadId = threadId;
      syncDefaultThreadIds();
      renderTree();
      resetChatHistory(threadLoadingMessage(branchLabelForThread(threadId)));
      setStatus("loading thread", "warn", null, threadId, { recordInActivity: false });
      await loadThreadState(threadId);
      setStatus("thread ready", "success", null, threadId, { recordInActivity: false });
    }

    function findNodeByThreadId(node, threadId) {
      if (!node || !threadId) return null;
      if (node.thread_id === threadId) return node;
      for (const child of node.children || []) {
        const match = findNodeByThreadId(child, threadId);
        if (match) return match;
      }
      return null;
    }

    function isChineseUi() {
      return document.documentElement.lang.toLowerCase().startsWith("zh");
    }

    function localizeBranchName(name) {
      const raw = String(name || "").trim();
      if (!raw) {
        return raw;
      }
      if (!isChineseUi()) {
        return raw;
      }
      if (/[\u4e00-\u9fff]/.test(raw)) {
        return raw;
      }
      const normalized = raw.replace(/[_-]+/g, " ").replace(/\\s+/g, " ").trim();
      const lower = normalized.toLowerCase();
      if (BRANCH_NAME_PHRASES_ZH[lower]) {
        return BRANCH_NAME_PHRASES_ZH[lower];
      }
      const translated = normalized.split(" ").map((word) => BRANCH_NAME_WORDS_ZH[word.toLowerCase()] || word);
      const allChinese = translated.every((part) => /^[\u4e00-\u9fff]+$/.test(part));
      return allChinese ? translated.join("") : translated.join(" ");
    }

    function updateThreadNav() {
      const nav = $("thread-nav");
      const mainButton = $("back-to-main");
      const parentButton = $("back-to-parent");
      const meta = state.activeBranchMeta;
      const hasParent = Boolean(meta && meta.parent_thread_id);
      if (!hasParent) {
        nav.hidden = true;
        mainButton.disabled = true;
        parentButton.disabled = true;
        scheduleActiveThreadPillRefresh();
        return;
      }
      nav.hidden = false;
      const mainTarget = meta.root_thread_id || state.rootThreadId || defaultThreadId();
      const parentTarget = meta.parent_thread_id || state.rootThreadId || defaultThreadId();
      mainButton.disabled = !mainTarget || mainTarget === state.activeThreadId;
      parentButton.disabled = !parentTarget || parentTarget === state.activeThreadId;
      scheduleActiveThreadPillRefresh();
    }

    let branchTreeFlashTimer = null;
    let branchNameRefreshTimer = null;

    function focusBranchTreePanel() {
      const panel = $("branch-tree-panel");
      if (!panel) {
        return;
      }
      if (isSidebarCollapsed()) {
        applySidebarCollapsed(false);
      }
      panel.scrollIntoView({ block: "start", behavior: "smooth" });
      panel.classList.remove("flash-focus");
      void panel.offsetWidth;
      panel.classList.add("flash-focus");
      if (branchTreeFlashTimer !== null) {
        window.clearTimeout(branchTreeFlashTimer);
      }
      branchTreeFlashTimer = window.setTimeout(() => {
        panel.classList.remove("flash-focus");
        branchTreeFlashTimer = null;
      }, 720);
    }

    function scheduleBranchNameBackfillRefresh(childThreadId) {
      if (branchNameRefreshTimer !== null) {
        window.clearTimeout(branchNameRefreshTimer);
      }
      branchNameRefreshTimer = window.setTimeout(async () => {
        branchNameRefreshTimer = null;
        try {
          await loadTree();
          if (state.activeThreadId === childThreadId) {
            await loadThreadState(childThreadId);
          }
        } catch {
          // Ignore delayed rename refresh failures and keep the current UI responsive.
        }
      }, 1800);
    }

    let activeResizePointerId = null;

    function beginSidebarResize(event) {
      if (window.innerWidth <= 960) {
        return;
      }
      activeResizePointerId = event.pointerId;
      document.body.classList.add("is-resizing");
      if ($("panel-resizer").setPointerCapture) {
        $("panel-resizer").setPointerCapture(event.pointerId);
      }
      event.preventDefault();
    }

    function updateSidebarResize(event) {
      if (activeResizePointerId === null) {
        return;
      }
      applySidebarWidth(event.clientX);
    }

    function endSidebarResize() {
      if (activeResizePointerId === null) {
        return;
      }
      if ($("panel-resizer").releasePointerCapture) {
        try {
          $("panel-resizer").releasePointerCapture(activeResizePointerId);
        } catch {
          // Ignore browsers that already released the pointer capture.
        }
      }
      activeResizePointerId = null;
      document.body.classList.remove("is-resizing");
    }

    function handleResizerKeydown(event) {
      if (window.innerWidth <= 960) {
        return;
      }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      const current = Number.parseInt(
        getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width"),
        10
      ) || SIDEBAR_MIN_WIDTH;
      const delta = event.key === "ArrowLeft" ? -20 : 20;
      applySidebarWidth(current + delta);
      event.preventDefault();
    }

    function renderArchivedBranches() {
      const root = $("archived-root");
      root.innerHTML = "";
      if (!state.archivedBranches.length) {
        root.innerHTML = '<div class="muted archived-empty">No archived branches.</div>';
        return;
      }
      for (const node of state.archivedBranches) {
        const item = document.createElement("div");
        item.className = "archived-item";
        const displayName = localizeBranchName(node.branch_name || node.thread_id);

        const title = document.createElement("div");
        title.className = "branch-name";
        const titleHead = document.createElement("div");
        titleHead.className = "branch-name-head";
        const titleStrong = document.createElement("strong");
        titleStrong.textContent = displayName;
        titleHead.appendChild(titleStrong);
        title.appendChild(titleHead);

        const actions = document.createElement("div");
        actions.className = "branch-node-actions";
        const activateButton = document.createElement("button");
        activateButton.type = "button";
        activateButton.className = "branch-inline-action";
        activateButton.textContent = "Activate";
        activateButton.addEventListener("click", async () => {
          try {
            await activateBranch(node);
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            showUiError("activate branch failed", message);
          }
        });
        actions.appendChild(activateButton);

        item.appendChild(title);
        item.appendChild(actions);
        root.appendChild(item);
      }
    }

    function branchRoleLabel(role) {
      const labels = isChineseUi()
        ? {
            main: "主线",
            explore_alternatives: "探索",
            deep_dive: "深挖",
            verify: "验证",
            writeup: "整理",
          }
        : {
            main: "Main",
            explore_alternatives: "Explore",
            deep_dive: "Deep dive",
            verify: "Verify",
            writeup: "Writeup",
          };
      return labels[role] || role || (isChineseUi() ? "分支" : "Branch");
    }

    function branchStatusLabel(status) {
      const labels = isChineseUi()
        ? {
            active: "进行中",
            paused: "已暂停",
            preparing_merge_review: "结论生成中",
            awaiting_merge_review: "结论已生成",
            merged: "已合并",
            discarded: "已丢弃",
            closed: "已关闭",
          }
        : {
            active: "Active",
            paused: "Paused",
            preparing_merge_review: "Generating conclusion",
            awaiting_merge_review: "Conclusion ready",
            merged: "Merged",
            discarded: "Discarded",
            closed: "Closed",
          };
      return labels[status] || status || (isChineseUi() ? "未知状态" : "Unknown");
    }

    function branchStatusTone(status) {
      if (status === "merged") {
        return "danger";
      }
      if (status === "awaiting_merge_review") {
        return "success";
      }
      if (status === "paused" || status === "preparing_merge_review") {
        return "warn";
      }
      return "";
    }

    function branchDisplayStatus(threadId, status) {
      if (state.pendingMergeProposal && state.activeMergeThreadId === threadId) {
        return "preparing_merge_review";
      }
      return status;
    }

    function threadMetaLabel() {
      return isChineseUi() ? "线程" : "Thread";
    }

    function parentMetaLabel() {
      return isChineseUi() ? "父分支" : "Parent";
    }

    function roleMetaLabel() {
      return isChineseUi() ? "角色" : "Role";
    }

    function statusMetaLabel() {
      return isChineseUi() ? "状态" : "Status";
    }

    function depthMetaLabel() {
      return isChineseUi() ? "层级" : "Depth";
    }

    function graphNodeHintLabel() {
      return isChineseUi()
        ? "悬浮或点击任意节点查看分支详情，需要切换上下文时再打开它。"
        : "Hover or click any node to inspect its branch details, then open it only when you want to switch context.";
    }

    function mainTimelineLabel() {
      return isChineseUi() ? "主线时间轴" : "Main timeline";
    }

    function branchRoleTheme(role) {
      const themes = {
        main: { color: "#6BA9FF" },
        explore_alternatives: { color: "#5EC2FF" },
        deep_dive: { color: "#A78BFA" },
        verify: { color: "#F59E0B" },
        writeup: { color: "#34D399" },
      };
      return themes[role] || { color: "#5EC2FF" };
    }

    function graphLegendRoles() {
      return ["main", "explore_alternatives", "deep_dive", "verify", "writeup"];
    }

    function renderTreeLegend() {
      const root = $("tree-graph-legend");
      if (!root) {
        return;
      }
      root.innerHTML = "";
      for (const role of graphLegendRoles()) {
        const item = document.createElement("span");
        item.className = "tree-graph-legend-item";
        item.style.setProperty("--legend-color", branchRoleTheme(role).color);
        item.textContent = role === "main" ? mainTimelineLabel() : branchRoleLabel(role);
        root.appendChild(item);
      }
    }

    const BRANCH_GRAPH_LAYOUT = {
      paddingX: 34,
      paddingY: 48,
      laneGap: 94,
      rowGap: 76,
      detailWidth: 228,
    };

    function computeBranchGraphLayout(rootNode) {
      let leafIndex = 0;
      const nodes = [];
      const edges = [];

      function visit(node, depth) {
        const childItems = [];
        for (const child of node.children || []) {
          childItems.push(visit(child, depth + 1));
        }
        const y = childItems.length
          ? (childItems[0].y + childItems[childItems.length - 1].y) / 2
          : BRANCH_GRAPH_LAYOUT.paddingY + leafIndex++ * BRANCH_GRAPH_LAYOUT.rowGap;
        const item = {
          node,
          depth,
          x: BRANCH_GRAPH_LAYOUT.paddingX + depth * BRANCH_GRAPH_LAYOUT.laneGap,
          y,
        };
        nodes.push(item);
        for (const childItem of childItems) {
          edges.push({ from: item, to: childItem });
        }
        return item;
      }

      visit(rootNode, 0);
      const maxDepth = nodes.reduce((value, item) => Math.max(value, item.depth), 0);
      const maxY = nodes.reduce((value, item) => Math.max(value, item.y), BRANCH_GRAPH_LAYOUT.paddingY);
      const width =
        BRANCH_GRAPH_LAYOUT.paddingX * 2 +
        maxDepth * BRANCH_GRAPH_LAYOUT.laneGap +
        BRANCH_GRAPH_LAYOUT.detailWidth +
        54;
      const height = Math.max(180, maxY + BRANCH_GRAPH_LAYOUT.paddingY);
      return { nodes, edges, width, height };
    }

    function branchEdgePath(from, to) {
      const startX = from.x;
      const startY = from.y + 13;
      const endX = to.x;
      const endY = to.y - 13;
      const offsetY = Math.max(24, Math.min(48, (endY - startY) * 0.35));
      const offsetX = Math.max(28, Math.abs(endX - startX) * 0.4);
      return `M ${startX} ${startY} C ${startX + offsetX} ${startY + offsetY}, ${endX - offsetX} ${endY - offsetY}, ${endX} ${endY}`;
    }

    function findBranchPath(node, threadId, path = []) {
      if (!node) {
        return null;
      }
      const nextPath = [...path, node];
      if (node.thread_id === threadId) {
        return nextPath;
      }
      for (const child of node.children || []) {
        const match = findBranchPath(child, threadId, nextPath);
        if (match) {
          return match;
        }
      }
      return null;
    }

    function findBranchNode(node, threadId) {
      if (!node) {
        return null;
      }
      if (node.thread_id === threadId) {
        return node;
      }
      for (const child of node.children || []) {
        const match = findBranchNode(child, threadId);
        if (match) {
          return match;
        }
      }
      return null;
    }

    function visibleEdgeKeysForThread(tree, threadId, includeChildEdges = false) {
      if (!tree || !threadId) {
        return new Set();
      }
      const keys = new Set();
      const path = findBranchPath(tree, threadId) || [];
      for (let index = 1; index < path.length; index += 1) {
        keys.add(`${path[index - 1].thread_id}->${path[index].thread_id}`);
      }
      if (includeChildEdges) {
        const node = path[path.length - 1] || findBranchNode(tree, threadId);
        for (const child of node?.children || []) {
          keys.add(`${node.thread_id}->${child.thread_id}`);
        }
      }
      return keys;
    }

    function applyEdgeVisibility(hoveredThreadId = null) {
      const root = $("tree-root");
      const tree = state.renderedTree;
      if (!root || !tree) {
        return;
      }
      const contextKeys = visibleEdgeKeysForThread(tree, state.activeThreadId, false);
      const focusThreadId = hoveredThreadId || state.detailThreadId || null;
      const focusedKeys = visibleEdgeKeysForThread(tree, focusThreadId, true);
      for (const edge of root.querySelectorAll(".branch-graph-edge")) {
        const edgeKey = edge.dataset.edgeKey || "";
        const isFocused = Boolean(focusThreadId) && focusedKeys.has(edgeKey);
        const isContext = contextKeys.has(edgeKey);
        edge.classList.toggle("is-context", isContext);
        edge.classList.toggle("is-focused", isFocused);
      }
    }

    function parentBranchLabel(node) {
      if (!node.parent_thread_id) {
        return mainBranchLabel();
      }
      const parent = state.tree ? findNodeByThreadId(state.tree, node.parent_thread_id) : null;
      if (!parent) {
        return node.parent_thread_id;
      }
      return localizeBranchName(parent.branch_name || parent.thread_id);
    }

    function branchDetailOverlay() {
      return $("branch-detail-overlay");
    }

    function toolbarTooltipOverlay() {
      return $("toolbar-tooltip-overlay");
    }

    function hideToolbarTooltip() {
      const overlay = toolbarTooltipOverlay();
      if (!overlay) {
        return;
      }
      state.toolbarTooltipAnchor = null;
      overlay.hidden = true;
      overlay.classList.remove("is-visible");
      overlay.textContent = "";
    }

    function positionToolbarTooltip() {
      const overlay = toolbarTooltipOverlay();
      const anchor = state.toolbarTooltipAnchor;
      if (!overlay || !anchor || overlay.hidden) {
        return;
      }
      if (!document.body.contains(anchor)) {
        hideToolbarTooltip();
        return;
      }
      const rect = anchor.getBoundingClientRect();
      const margin = 12;
      const gap = 10;
      const overlayWidth = overlay.offsetWidth || 180;
      const overlayHeight = overlay.offsetHeight || 36;
      const left = Math.min(
        Math.max(margin, rect.left + rect.width / 2 - overlayWidth / 2),
        window.innerWidth - overlayWidth - margin
      );
      const top = Math.max(margin, rect.top - overlayHeight - gap);
      overlay.style.left = `${left}px`;
      overlay.style.top = `${top}px`;
    }

    function showToolbarTooltip(anchor, text) {
      const overlay = toolbarTooltipOverlay();
      if (!overlay || !(anchor instanceof HTMLElement) || !text) {
        return;
      }
      state.toolbarTooltipAnchor = anchor;
      overlay.textContent = text;
      overlay.hidden = false;
      overlay.classList.add("is-visible");
      positionToolbarTooltip();
    }

    function hideBranchDetail() {
      clearBranchDetailHideTimer();
      const overlay = branchDetailOverlay();
      if (!overlay) {
        return;
      }
      state.detailThreadId = null;
      state.detailAnchorElement = null;
      overlay.hidden = true;
      overlay.classList.remove("is-visible", "active-card");
      overlay.innerHTML = "";
      applyEdgeVisibility();
    }

    function clearBranchDetailHideTimer() {
      if (!state.detailHideTimer) {
        return;
      }
      window.clearTimeout(state.detailHideTimer);
      state.detailHideTimer = null;
    }

    function scheduleHideBranchDetail() {
      clearBranchDetailHideTimer();
      state.detailHideTimer = window.setTimeout(() => {
        state.detailHideTimer = null;
        hideBranchDetail();
      }, BRANCH_DETAIL_HIDE_DELAY_MS);
    }

    function currentDetailAnchorShell() {
      return state.detailAnchorElement?.closest(".branch-graph-node-shell") || null;
    }

    function positionBranchDetailOverlay() {
      const overlay = branchDetailOverlay();
      const anchor = state.detailAnchorElement;
      if (!overlay || !anchor || overlay.hidden) {
        return;
      }
      if (!document.body.contains(anchor)) {
        hideBranchDetail();
        return;
      }
      const rect = anchor.getBoundingClientRect();
      const margin = 16;
      const gap = 18;
      const overlayWidth = overlay.offsetWidth || 220;
      const overlayHeight = overlay.offsetHeight || 240;
      const left = Math.min(window.innerWidth - overlayWidth - margin, rect.right + gap);
      const centeredTop = rect.top + rect.height / 2 - overlayHeight / 2;
      const top = Math.min(
        Math.max(margin, centeredTop),
        Math.max(margin, window.innerHeight - overlayHeight - margin)
      );
      overlay.style.left = `${Math.max(margin, left)}px`;
      overlay.style.top = `${top}px`;
    }

    function refreshBranchDetailOverlay() {
      if (!state.detailThreadId || !state.detailAnchorElement) {
        return;
      }
      const node = state.tree ? findNodeByThreadId(state.tree, state.detailThreadId) : null;
      if (!node) {
        return;
      }
      renderBranchDetailOverlay(
        node,
        branchRoleTheme(node.branch_role).color,
        Number(node.branch_depth || 0)
      );
      applyEdgeVisibility(node.thread_id);
    }

    function renderBranchDetailOverlay(node, roleColor, depth) {
      const overlay = branchDetailOverlay();
      if (!overlay) {
        return;
      }
      const displayStatus = branchDisplayStatus(node.thread_id, node.branch_status);
      overlay.innerHTML = "";
      overlay.style.setProperty("--branch-role-color", roleColor);
      overlay.classList.toggle("active-card", node.thread_id === state.activeThreadId);

      const detail = document.createElement("div");
      detail.className = "branch-node-detail";
      detail.style.setProperty("--branch-role-color", roleColor);

      const head = document.createElement("div");
      head.className = "branch-node-detail-head";

      const title = document.createElement("div");
      title.className = "branch-node-title";
      title.textContent = localizeBranchName(node.branch_name || node.thread_id);
      head.appendChild(title);

      const subtitle = document.createElement("div");
      subtitle.className = "branch-node-subtitle";
      subtitle.textContent = `${threadMetaLabel()} · ${node.thread_id}`;
      head.appendChild(subtitle);

      const badges = document.createElement("div");
      badges.className = "branch-node-badges";

      if (node.thread_id === state.activeThreadId) {
        const currentBadge = document.createElement("span");
        currentBadge.className = "branch-node-badge current";
        currentBadge.textContent = currentBranchBadgeLabel();
        badges.appendChild(currentBadge);
      }

      const roleBadge = document.createElement("span");
      roleBadge.className = "branch-node-badge";
      roleBadge.style.borderColor = `color-mix(in srgb, ${roleColor} 26%, var(--border) 74%)`;
      roleBadge.style.background = `color-mix(in srgb, ${roleColor} 12%, var(--panel-3) 88%)`;
      roleBadge.textContent = branchRoleLabel(node.branch_role);
      badges.appendChild(roleBadge);

      const statusBadge = document.createElement("span");
      statusBadge.className = `branch-node-badge ${branchStatusTone(displayStatus)}`.trim();
      statusBadge.textContent = branchStatusLabel(displayStatus);
      badges.appendChild(statusBadge);

      const depthBadge = document.createElement("span");
      depthBadge.className = "branch-node-badge";
      depthBadge.textContent = `${depthMetaLabel()} ${depth}`;
      badges.appendChild(depthBadge);

      head.appendChild(badges);
      detail.appendChild(head);

      const meta = document.createElement("div");
      meta.className = "branch-node-meta";

      const metaRows = [
        [threadMetaLabel(), node.thread_id],
        [parentMetaLabel(), parentBranchLabel(node)],
        [roleMetaLabel(), branchRoleLabel(node.branch_role)],
        [statusMetaLabel(), branchStatusLabel(displayStatus)],
        [depthMetaLabel(), String(depth)],
      ];

      for (const [label, value] of metaRows) {
        const row = document.createElement("div");
        row.className = "branch-node-meta-row";

        const labelNode = document.createElement("span");
        labelNode.className = "branch-node-meta-label";
        labelNode.textContent = label;

        const valueNode = document.createElement("span");
        valueNode.className = "branch-node-meta-value";
        valueNode.textContent = value;

        row.appendChild(labelNode);
        row.appendChild(valueNode);
        meta.appendChild(row);
      }

      detail.appendChild(meta);

      const actions = document.createElement("div");
      actions.className = "branch-node-actions";
      const isPendingMerge = state.pendingMergeProposal && state.activeMergeThreadId === node.thread_id;

      if (node.branch_id && !node.is_pending) {
        if (!["merged", "discarded", "closed"].includes(String(node.branch_status || ""))) {
          const isReadyToMerge =
            !isPendingMerge &&
            (node.branch_status === "awaiting_merge_review" || hasReadyMergeProposal(node.thread_id, node));
          if (isReadyToMerge) {
            const regenerateButton = document.createElement("button");
            regenerateButton.type = "button";
            regenerateButton.dataset.branchAction = "regenerate-merge";
            regenerateButton.className = `branch-inline-action${isPendingMerge ? " pending" : ""}`;
            regenerateButton.textContent = mergeRegenerateLabel();
            regenerateButton.disabled = isPendingMerge;
            regenerateButton.addEventListener("click", async (event) => {
              event.preventDefault();
              event.stopPropagation();
              try {
                await prepareMergeReview(node.thread_id);
              } catch (error) {
                const message = error instanceof Error ? error.message : String(error);
                showUiError("merge action failed", message);
              }
            });
            actions.appendChild(regenerateButton);
          }
          const mergeButton = document.createElement("button");
          mergeButton.type = "button";
          mergeButton.dataset.branchAction = "prepare-merge";
          mergeButton.className = `branch-inline-action${isPendingMerge ? " pending" : ""}`;
          mergeButton.textContent = mergeButtonLabel(node.thread_id, node);
          mergeButton.disabled = isPendingMerge;
          mergeButton.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();
            try {
              await handleMergeAction(node.thread_id, node);
            } catch (error) {
              const message = error instanceof Error ? error.message : String(error);
              showUiError("merge action failed", message);
            }
          });
          actions.appendChild(mergeButton);
        }
        const archiveButton = document.createElement("button");
        archiveButton.type = "button";
        archiveButton.dataset.branchAction = "archive";
        archiveButton.className = "branch-inline-action warn";
        archiveButton.textContent = "Archive";
        archiveButton.addEventListener("click", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          try {
            hideBranchDetail();
            await archiveBranch(node);
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            showUiError("archive branch failed", message);
          }
        });
        actions.appendChild(archiveButton);
      }

      if (node.is_pending) {
        const pendingBadge = document.createElement("span");
        pendingBadge.className = "branch-inline-action pending";
        pendingBadge.textContent = pendingBranchButtonLabel();
        actions.appendChild(pendingBadge);
      }

      if (actions.childElementCount) {
        detail.appendChild(actions);
      }

      overlay.appendChild(detail);
      overlay.hidden = false;
      overlay.classList.add("is-visible");
      positionBranchDetailOverlay();
    }

    function showBranchDetail(node, anchorElement, depth) {
      clearBranchDetailHideTimer();
      state.detailThreadId = node.thread_id;
      state.detailAnchorElement = anchorElement;
      renderBranchDetailOverlay(node, branchRoleTheme(node.branch_role).color, depth);
      applyEdgeVisibility(node.thread_id);
    }

    async function openBranchFromNode(node) {
      if (!node || node.thread_id === state.activeThreadId) {
        return;
      }
      hideBranchDetail();
      try {
        await selectThread(node.thread_id);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("load thread failed", message);
      }
    }

    function renderTree() {
      const root = $("tree-root");
      const summary = document.querySelector(".tree-graph-summary");
      renderTreeLegend();
      if (summary) {
        summary.textContent = graphNodeHintLabel();
      }
      if (!state.tree) {
        state.renderedTree = null;
        root.innerHTML = "";
        return;
      }

      state.renderedTree = state.tree;
      const layout = computeBranchGraphLayout(state.tree);
      const graph = document.createElement("div");
      graph.className = "branch-graph";
      graph.classList.toggle("has-active-selection", Boolean(state.activeThreadId));
      graph.style.width = `${layout.width}px`;
      graph.style.height = `${layout.height}px`;

      const rootNode = layout.nodes.find((item) => item.depth === 0);
      if (rootNode) {
        const label = document.createElement("div");
        label.className = "branch-graph-root-label";
        label.style.left = `${Math.max(8, rootNode.x - 56)}px`;
        label.style.setProperty("--lane-color", branchRoleTheme(rootNode.node.branch_role).color);
        label.textContent = mainTimelineLabel();
        graph.appendChild(label);
      }

      const lines = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      lines.setAttribute("class", "branch-graph-lines");
      lines.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);
      lines.setAttribute("width", String(layout.width));
      lines.setAttribute("height", String(layout.height));
      lines.setAttribute("aria-hidden", "true");

      for (const edge of layout.edges) {
        const edgeColor = branchRoleTheme(edge.to.node.branch_role).color;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("class", "branch-graph-edge");
        path.setAttribute("d", branchEdgePath(edge.from, edge.to));
        path.setAttribute("style", `stroke:${edgeColor};`);
        path.dataset.edgeKey = `${edge.from.node.thread_id}->${edge.to.node.thread_id}`;
        lines.appendChild(path);
      }
      graph.appendChild(lines);

      for (const item of layout.nodes) {
        graph.appendChild(renderGraphNode(item, layout));
      }

      root.innerHTML = "";
      root.appendChild(graph);
      hideBranchDetail();
      applyEdgeVisibility();
      const activeNode = root.querySelector(".active-card");
      if (activeNode) {
        activeNode.scrollIntoView({ block: "nearest", inline: "center" });
      }
    }

    function renderGraphNode(item, layout) {
      const { node, depth, x, y } = item;
      const isPending = Boolean(node.is_pending);
      const isRoot = !node.branch_id && !node.parent_thread_id && !isPending;
      const isActive = node.thread_id === state.activeThreadId;
      const displayName = localizeBranchName(node.branch_name || node.thread_id);
      const roleColor = branchRoleTheme(node.branch_role).color;
      const wrapper = document.createElement("div");
      wrapper.className = "branch-graph-node-shell";
      wrapper.style.left = `${x}px`;
      wrapper.style.top = `${y}px`;
      if (isActive) {
        wrapper.classList.add("active-card");
      }

      const button = document.createElement("button");
      button.type = "button";
      button.className = "branch-graph-node";
      button.style.setProperty("--branch-role-color", roleColor);
      if (isRoot) {
        button.classList.add("is-root");
      }
      if (isActive) {
        button.classList.add("is-active");
      }
      if (isPending) {
        button.classList.add("is-pending");
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
      }
      if (node.branch_status === "paused") {
        button.classList.add("is-paused");
      }
      if (node.branch_status === "awaiting_merge_review") {
        button.classList.add("is-ready");
      }
      if (node.branch_status === "merged") {
        button.classList.add("is-merged");
      }
      button.setAttribute(
        "aria-label",
        isPending
          ? pendingBranchCardLabel()
          : `${displayName} · ${branchRoleLabel(node.branch_role)} · ${branchStatusLabel(node.branch_status)}`
      );
      if (!isPending) {
        button.addEventListener("click", async (event) => {
          event.preventDefault();
          event.stopPropagation();
          await openBranchFromNode(node);
        });
        button.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" && event.key !== " ") {
            return;
          }
          event.preventDefault();
          event.stopPropagation();
          void openBranchFromNode(node);
        });
      }
      wrapper.appendChild(button);

      if (!isPending) {
        wrapper.addEventListener("mouseenter", () => {
          showBranchDetail(node, button, depth);
        });
        wrapper.addEventListener("mouseleave", (event) => {
          if (event.relatedTarget instanceof Node && branchDetailOverlay()?.contains(event.relatedTarget)) {
            return;
          }
          scheduleHideBranchDetail();
        });
        wrapper.addEventListener("focusin", () => {
          showBranchDetail(node, button, depth);
        });
        wrapper.addEventListener("focusout", (event) => {
          if (
            event.relatedTarget instanceof Node &&
            (wrapper.contains(event.relatedTarget) || branchDetailOverlay()?.contains(event.relatedTarget))
          ) {
            return;
          }
          scheduleHideBranchDetail();
        });
      }
      return wrapper;
    }

    async function issueToken() {
      syncDefaultThreadIds();
      const response = await fetch(`${apiBase()}/v1/auth/demo-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: DEMO_USER_ID,
          tenant_id: DEMO_TENANT_ID,
          scopes: ["chat", "branches"],
        }),
      });
      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }
      const payload = await response.json();
      state.token = payload.access_token;
    }

    async function loadThreadState(threadId = state.activeThreadId) {
      if (!state.token) await issueToken();
      const response = await fetch(`${apiBase()}/v1/threads/${encodeURIComponent(threadId)}`, { headers: headers(false) });
      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }
      const payload = await response.json();
      state.rootThreadId = payload.root_thread_id || state.rootThreadId || defaultThreadId();
      state.activeThreadId = payload.thread_id || threadId;
      state.loadedThreadId = payload.thread_id;
      state.activeBranchMeta = payload.branch_meta || null;
      if (state.activeBranchMeta?.branch_status === "preparing_merge_review") {
        state.activeMergeProposal = null;
        state.activeMergeThreadId = payload.thread_id;
        state.pendingMergeProposal = true;
      } else if (
        state.activeBranchMeta?.branch_id &&
        state.activeBranchMeta?.branch_status === "awaiting_merge_review" &&
        payload.merge_proposal
      ) {
        state.activeMergeProposal = payload.merge_proposal;
        state.activeMergeThreadId = payload.thread_id;
        state.pendingMergeProposal = false;
      } else if (!state.pendingMergeProposal || state.activeMergeThreadId === payload.thread_id) {
        state.activeMergeProposal = null;
        if (!state.pendingMergeProposal) {
          state.activeMergeThreadId = null;
        }
      }
      if (payload.selected_model) {
        applyComposerModelSelection(payload.selected_model, {
          persist: true,
          thinkingMode: payload.selected_thinking_mode || null,
        });
      } else if (!state.selectedModel && state.defaultModelId) {
        applyComposerModelSelection(state.defaultModelId, { persist: false });
      }
      updateBranchCreationUi();
      updateActiveThreadPill(state.activeBranchMeta);
      updateThreadNav();
      renderThreadMessages(payload.messages || [], payload.thread_id);
      restoreThreadUiState(payload.thread_id);
      return payload;
    }

    async function loadTree() {
      if (!state.token) await issueToken();
      syncDefaultThreadIds();
      const rootThreadId = state.rootThreadId || defaultThreadId();
      if (!rootThreadId) return;
      const response = await fetch(`${apiBase()}/v1/branches/tree/${encodeURIComponent(rootThreadId)}`, { headers: headers(false) });
      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }
      const payload = await response.json();
      if (!payload || !payload.root || !payload.root.thread_id) {
        throw new Error("Invalid branch tree payload.");
      }
      state.tree = payload.root;
      state.archivedBranches = payload.archived_branches || [];
      state.rootThreadId = payload.root.thread_id;
      if (
        state.detailThreadId &&
        !findNodeByThreadId(state.tree, state.detailThreadId) &&
        !state.archivedBranches.some((item) => item.thread_id === state.detailThreadId)
      ) {
        hideBranchDetail();
      }
      renderTree();
      renderArchivedBranches();
      updateTreeBranchSummary();
      refreshBranchDetailOverlay();
    }

    async function archiveBranch(node) {
      if (!state.token) await issueToken();
      const previousTree = state.tree;
      const previousArchivedBranches = state.archivedBranches;
      const previousRootThreadId = state.rootThreadId;
      const previousActiveThreadId = state.activeThreadId;
      setStatus("archiving branch", "warn");
      const hidingActiveThread = Boolean(findNodeByThreadId(node, state.activeThreadId));
      if (hidingActiveThread) {
        state.activeThreadId = node.parent_thread_id || state.rootThreadId || defaultThreadId();
        syncDefaultThreadIds();
      }
      try {
        const response = await fetch(`${apiBase()}/v1/branches/${encodeURIComponent(node.thread_id)}/archive`, {
          method: "POST",
          headers: headers(false),
        });
        if (!response.ok) {
          throw new Error(await readErrorMessage(response));
        }
        await loadTree();
        if (hidingActiveThread) {
          await loadThreadState(state.activeThreadId);
        }
        setStatus("branch archived", "success");
      } catch (error) {
        state.tree = previousTree;
        state.archivedBranches = previousArchivedBranches;
        state.rootThreadId = previousRootThreadId;
        state.activeThreadId = previousActiveThreadId;
        renderTree();
        renderArchivedBranches();
        throw error;
      }
    }

    async function activateBranch(node) {
      if (!state.token) await issueToken();
      setStatus("activating branch", "warn");
      const response = await fetch(`${apiBase()}/v1/branches/${encodeURIComponent(node.thread_id)}/activate`, {
        method: "POST",
        headers: headers(false),
      });
      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }
      await loadTree();
      if (findNodeByThreadId(state.tree, node.thread_id)) {
        await selectThread(node.thread_id);
      }
      setStatus("branch activated", "success");
    }

    async function createBranch({ branchName = null } = {}) {
      if (state.pendingBranch) {
        return;
      }
      if (!state.token) await issueToken();
      const parentThreadId = state.activeThreadId;
      const nameSource = $("stream-message").value.trim() || null;
      state.pendingBranch = {
        parentThreadId,
      };
      updateBranchCreationUi();
      setStatus("creating branch", "warn");
      try {
        const response = await fetch(`${apiBase()}/v1/branches/fork`, {
          method: "POST",
          headers: headers(true),
          body: JSON.stringify({
            parent_thread_id: parentThreadId,
            branch_name: branchName,
            name_source: nameSource,
            branch_role: "explore_alternatives",
          }),
        });
        if (!response.ok) {
          throw new Error(await readErrorMessage(response));
        }
        const payload = await response.json();
        await loadTree();
        await selectThread(payload.child_thread_id);
        setStatus("branch created", "success");
      } finally {
        state.pendingBranch = null;
        updateBranchCreationUi();
      }
    }

    async function submitBranchCreateModal() {
      await createBranch({
        branchName: $("branch-name-input").value.trim() || null,
      });
      closeBranchCreateModal();
    }

    async function prepareMergeReview(threadId = state.activeThreadId) {
      if (!state.token) await issueToken();
      if (state.pendingMergeProposal && state.activeMergeThreadId === threadId) {
        return;
      }
      const requestId = state.mergeReviewRequestId + 1;
      state.mergeReviewRequestId = requestId;
      state.activeMergeProposal = null;
      state.activeMergeThreadId = threadId;
      state.pendingMergeProposal = true;
      if (threadId === state.activeThreadId) {
        updateActiveThreadPill(state.activeBranchMeta);
      }
      refreshBranchDetailOverlay();
      setStatus("generating conclusion", "warn");
      try {
        const response = await fetch(`${apiBase()}/v1/branches/${encodeURIComponent(threadId)}/proposal`, {
          method: "POST",
          headers: headers(true),
          body: JSON.stringify({}),
        });
        if (!response.ok) {
          throw new Error(await readErrorMessage(response));
        }
        const proposal = await response.json();
        if (requestId !== state.mergeReviewRequestId) {
          return;
        }
        state.activeMergeProposal = proposal;
        state.activeMergeThreadId = threadId;
        state.pendingMergeProposal = false;
        if (threadId === state.activeThreadId) {
          state.activeBranchMeta = {
            ...(state.activeBranchMeta || {}),
            branch_status: "awaiting_merge_review",
          };
          updateActiveThreadPill(state.activeBranchMeta);
          await loadThreadState(threadId);
        }
        await loadTree();
        refreshBranchDetailOverlay();
        setStatus("conclusion ready to merge", "success");
      } catch (error) {
        if (requestId === state.mergeReviewRequestId) {
          state.pendingMergeProposal = false;
          if (state.activeMergeThreadId === threadId) {
            state.activeMergeThreadId = null;
            state.activeMergeProposal = null;
          }
          if (threadId === state.activeThreadId) {
            updateActiveThreadPill(state.activeBranchMeta);
          }
          refreshBranchDetailOverlay();
        }
        throw error;
      }
    }

    async function regenerateMergeReview(threadId = state.activeMergeThreadId || state.activeThreadId) {
      closeModal("merge-review-modal");
      await prepareMergeReview(threadId);
    }

    async function submitMergeReview(threadId = state.activeThreadId) {
      if (threadId !== state.activeThreadId) {
        await selectThread(threadId);
      }
      if (!state.token) await issueToken();
      if (!state.activeMergeProposal) {
        await loadThreadState(state.activeThreadId);
      }
      if (!state.activeMergeProposal) {
        throw new Error(isChineseUi() ? "请先生成分支结论，再执行合并。" : "Generate the branch conclusion before merging upstream.");
      }
      const editedSummary = $("merge-proposal-summary").value.trim();
      if (!editedSummary) {
        throw new Error(isChineseUi() ? "请先填写结论摘要。" : "Please provide a merge summary.");
      }
      const approved = $("merge-decision-select").value === "approve";
      const mode = approved ? $("merge-mode-select").value : "none";
      setStatus(approved ? "merging upstream" : "rejecting merge", "warn");
      const response = await fetch(`${apiBase()}/v1/branches/${encodeURIComponent(state.activeThreadId)}/merge`, {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          approved,
          mode,
          target: approved ? $("merge-target-select").value : "return_thread",
          rationale: $("merge-rationale").value.trim() || null,
          selected_artifacts: mode === "selected_artifacts" ? parseLineList($("merge-selected-artifacts").value) : [],
          proposal_overrides: {
            summary: editedSummary,
            key_findings: parseLineList($("merge-proposal-findings").value),
            open_questions: parseLineList($("merge-proposal-open-questions").value),
            evidence_refs: parseLineList($("merge-proposal-evidence").value),
            artifacts: parseLineList($("merge-proposal-artifacts").value),
          },
        }),
      });
      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }
      closeMergeReviewModal();
      state.activeMergeProposal = null;
      state.activeMergeThreadId = null;
      state.pendingMergeProposal = false;
      await loadTree();
      await loadThreadState(state.activeThreadId);
      setStatus(approved ? "merged upstream" : "merge rejected", "success");
    }

    async function openMergeReviewForThread(threadId = state.activeThreadId, branchMeta = state.activeBranchMeta) {
      if (threadId !== state.activeThreadId) {
        await selectThread(threadId);
      }
      if (!hasReadyMergeProposal(state.activeThreadId, branchMeta) && branchMeta?.branch_status !== "awaiting_merge_review") {
        throw new Error(isChineseUi() ? "请先生成分支结论，再执行合并。" : "Generate the branch conclusion before merging upstream.");
      }
      if (!state.activeMergeProposal || state.activeMergeThreadId !== state.activeThreadId) {
        await loadThreadState(state.activeThreadId);
      }
      if (!state.activeMergeProposal) {
        throw new Error(isChineseUi() ? "还没拿到可合并的结论摘要，请稍后重试。" : "The merge conclusion is not ready yet. Please try again shortly.");
      }
      openMergeReviewModal(state.activeMergeProposal, state.activeThreadId);
    }

    async function handleMergeAction(threadId = state.activeThreadId, branchMeta = state.activeBranchMeta) {
      if (threadId !== state.activeThreadId) {
        await selectThread(threadId);
      }
      if (hasReadyMergeProposal(state.activeThreadId, branchMeta) || branchMeta?.branch_status === "awaiting_merge_review") {
        await openMergeReviewForThread(state.activeThreadId, branchMeta);
        return;
      }
      await prepareMergeReview(state.activeThreadId);
    }

    async function goToMainBranch() {
      const target = state.activeBranchMeta?.root_thread_id || state.rootThreadId || defaultThreadId();
      if (!target || target === state.activeThreadId) {
        return;
      }
      await selectThread(target);
    }

    async function goToParentBranch() {
      const target = state.activeBranchMeta?.parent_thread_id || state.rootThreadId || defaultThreadId();
      if (!target || target === state.activeThreadId) {
        return;
      }
      await selectThread(target);
    }

    function clearComposerInput({ focus = true } = {}) {
      const input = $("stream-message");
      if (!input) {
        return;
      }
      input.value = "";
      autoResizeComposerInput();
      if (focus) {
        input.focus();
      }
    }

    function handleEvent(eventName, payload, threadId = state.activeThreadId) {
      const targetThreadId = threadId || state.activeThreadId;
      const isVisibleThread = targetThreadId === state.activeThreadId;
      if (eventName === "visible_text.delta") {
        if (!isVisibleThread) {
          clearThreadUiState(targetThreadId);
          return;
        }
        if (payload.metadata && payload.metadata.langgraph_node && payload.metadata.langgraph_node !== "agent_loop") {
          return;
        }
        state.currentVisibleText += payload.delta || "";
        setStatus("streaming text", "success");
        const threadLabel = branchLabelForThread(state.activeThreadId, state.activeBranchMeta);
        const assistantBubble = ensureAssistantBubble(threadLabel);
        const shouldFollow = shouldAutoFollowChat();
        setBubbleContent(assistantBubble, state.currentVisibleText);
        if (shouldFollow) {
          scrollChatToBottom();
        }
      } else if (eventName === "visible_text.completed") {
        if (!isVisibleThread) {
          clearThreadUiState(targetThreadId);
          return;
        }
        if (payload.content) {
          state.currentVisibleText = payload.content;
          const threadLabel = branchLabelForThread(state.activeThreadId, state.activeBranchMeta);
          const assistantBubble = ensureAssistantBubble(threadLabel);
          setBubbleContent(assistantBubble, payload.content);
        }
        setStatus("text completed", "success");
        Promise.resolve(loadTree()).catch(() => {});
        state.loadedThreadId = state.activeThreadId;
      } else if (eventName === "reasoning.delta") {
        setStatus("thinking", "warn", null, targetThreadId);
      } else if (eventName === "tool_call.delta") {
        setStatus(`using ${payload.name || "tool"}`, "warn", null, targetThreadId);
      } else if (eventName.startsWith("tool.")) {
        const label = payload.tool_name || payload.name || "tool";
        if (eventName === "tool.error") {
          setStatus(`${label} failed`, "danger", payload.error || payload.message || label, targetThreadId);
        } else if (eventName === "tool.result" || eventName === "tool.end") {
          setStatus(`${label} completed`, "success", null, targetThreadId);
        } else {
          setStatus(`using ${label}`, "warn", null, targetThreadId);
        }
      } else if (eventName === "turn.failed") {
        if (!isVisibleThread) {
          clearThreadUiState(targetThreadId);
          return;
        }
        state.streamingResponseActive = false;
        presentTurnFailure(payload);
      } else if (eventName === "turn.completed") {
        if (!isVisibleThread) {
          clearThreadUiState(targetThreadId);
          return;
        }
        state.streamingResponseActive = false;
        setStatus("turn completed", "success", null, targetThreadId);
        clearThreadUiState(targetThreadId);
        clearAgentActivityBubble();
        if (state.activeBranchMeta?.branch_id) {
          scheduleBranchNameBackfillRefresh(state.activeThreadId);
        }
      } else if (eventName === "turn.interrupt") {
        state.streamingResponseActive = false;
        setStatus("waiting for resume", "warn", null, targetThreadId);
        if (!isVisibleThread) {
          return;
        }
        if (state.currentAssistantBubble && bubbleRawText(state.currentAssistantBubble)) {
          setBubbleContent(
            state.currentAssistantBubble,
            `${bubbleRawText(state.currentAssistantBubble)}\\n\\n[Waiting for resume decision]`
          );
        }
      }
    }

    async function openStream() {
      try {
        const message = $("stream-message").value.trim();
        if (!message) {
          return;
        }
        if (!state.token) await issueToken();
        syncDefaultThreadIds();
        if (state.abortController) state.abortController.abort();
        state.abortController = new AbortController();
        state.currentVisibleText = "";
        state.chatAutoFollow = true;
        state.streamingResponseActive = true;
        const streamThreadId = state.activeThreadId;
        updateActiveThreadPill();
        setStatus("connecting", "warn");
        beginChatTurn();

        const response = await fetch(`${apiBase()}/v1/chat/turns/stream`, {
          method: "POST",
          headers: headers(true),
          body: JSON.stringify({
            thread_id: streamThreadId,
            message,
            model: state.selectedModel || undefined,
            thinking_mode: state.selectedThinkingMode || undefined,
          }),
          signal: state.abortController.signal,
        });
        if (!response.ok) {
          throw new Error(await readErrorMessage(response));
        }
        if (!response.body) {
          throw new Error("Streaming response body is unavailable.");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\\n\\n");
          buffer = frames.pop() || "";
          for (const frame of frames) {
            if (!frame || frame.startsWith(":")) continue;
            let eventName = "message";
            const dataLines = [];
            for (const line of frame.split("\\n")) {
              if (line.startsWith("event: ")) eventName = line.slice(7).trim();
              if (line.startsWith("data: ")) dataLines.push(line.slice(6));
            }
            try {
              handleEvent(eventName, JSON.parse(dataLines.join("\\n") || "{}"), streamThreadId);
            } catch {
              handleEvent(eventName, { raw: dataLines.join("\\n") }, streamThreadId);
            }
          }
        }
      } catch (error) {
        state.streamingResponseActive = false;
        const message = error instanceof Error ? error.message : String(error);
        if (state.activeThreadId === streamThreadId) {
          showUiError("request failed", message);
        } else {
          clearThreadUiState(streamThreadId);
        }
        if (state.activeThreadId === streamThreadId && state.currentAssistantBubble && !bubbleRawText(state.currentAssistantBubble)) {
          setBubbleContent(state.currentAssistantBubble, message);
        }
      }
    }

    $("load-tree").addEventListener("click", async () => {
      try {
        await loadTree();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("load tree failed", message);
      }
    });
    $("toggle-tree").addEventListener("click", toggleSidebarCollapsed);
    $("chat-logo-toggle").addEventListener("click", toggleSidebarCollapsed);
    $("create-branch").addEventListener("click", async () => {
      try {
        await openBranchCreateModal();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("create branch failed", message);
      }
    });
    $("composer-create-branch").addEventListener("click", async () => {
      try {
        await openBranchCreateModal();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("create branch failed", message);
      }
    });
    $("prepare-merge").addEventListener("click", async () => {
      try {
        await handleMergeAction();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("merge action failed", message);
      }
    });
    $("close-branch-create").addEventListener("click", closeBranchCreateModal);
    $("cancel-branch-create").addEventListener("click", closeBranchCreateModal);
    $("branch-create-modal").addEventListener("click", (event) => {
      if (event.target === event.currentTarget) {
        closeBranchCreateModal();
      }
    });
    $("confirm-branch-create").addEventListener("click", async () => {
      try {
        await submitBranchCreateModal();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("create branch failed", message);
      }
    });
    $("close-merge-review").addEventListener("click", closeMergeReviewModal);
    $("cancel-merge-review").addEventListener("click", closeMergeReviewModal);
    $("regenerate-merge-review").addEventListener("click", async () => {
      try {
        await regenerateMergeReview();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("merge action failed", message);
      }
    });
    $("merge-review-modal").addEventListener("click", (event) => {
      if (event.target === event.currentTarget) {
        closeMergeReviewModal();
      }
    });
    $("submit-merge-review").addEventListener("click", async () => {
      try {
        await submitMergeReview();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("submit merge review failed", message);
      }
    });
    $("merge-decision-select").addEventListener("change", updateMergeArtifactsField);
    $("merge-mode-select").addEventListener("change", updateMergeArtifactsField);
    $("focus-branch-tree").addEventListener("click", focusBranchTreePanel);
    $("back-to-main").addEventListener("click", async () => {
      try {
        await goToMainBranch();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("load thread failed", message);
      }
    });
    $("back-to-parent").addEventListener("click", async () => {
      try {
        await goToParentBranch();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("load thread failed", message);
      }
    });
    $("open-stream").addEventListener("click", openStream);
    $("chat-history").addEventListener("scroll", syncChatAutoFollowFromScroll, { passive: true });
    $("chat-history").addEventListener("wheel", handleChatWheel, { passive: true });
    $("chat-history").addEventListener("touchstart", handleChatTouchStart, { passive: true });
    $("chat-history").addEventListener("touchmove", handleChatTouchMove, { passive: true });
    $("chat-history").addEventListener("touchend", handleChatTouchEnd, { passive: true });
    $("composer-model-trigger").addEventListener("click", (event) => {
      event.preventDefault();
      toggleComposerModelPanel();
    });
    $("stream-message").addEventListener("input", autoResizeComposerInput);
    $("stream-message").addEventListener("keydown", (event) => {
      if (!shouldSubmitComposerOnEnter(event)) {
        return;
      }
      event.preventDefault();
      void openStream();
    });
    $("clear-stream").addEventListener("click", () => {
      clearComposerInput();
    });
    bindPreferenceToggle("language", switchUiLanguage);
    bindPreferenceToggle("theme", applyColorMode);
    bindPreferenceToggle("color", applyAccentTheme);
    document.addEventListener("pointerover", (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const host = event.target.closest(".toolbar-tooltip-host[data-tooltip]");
      const actions = document.querySelector(".chat-header-actions");
      if (!(host instanceof HTMLElement) || !actions?.classList.contains("is-compact")) {
        return;
      }
      showToolbarTooltip(host, host.dataset.tooltip || "");
    });
    document.addEventListener("pointerout", (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const host = event.target.closest(".toolbar-tooltip-host[data-tooltip]");
      if (!(host instanceof HTMLElement)) {
        return;
      }
      if (event.relatedTarget instanceof Node && host.contains(event.relatedTarget)) {
        return;
      }
      hideToolbarTooltip();
    });
    document.addEventListener("focusin", (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const host = event.target.closest(".toolbar-tooltip-host[data-tooltip]");
      const actions = document.querySelector(".chat-header-actions");
      if (!(host instanceof HTMLElement) || !actions?.classList.contains("is-compact")) {
        hideToolbarTooltip();
        return;
      }
      showToolbarTooltip(host, host.dataset.tooltip || "");
    });
    document.addEventListener("focusout", (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      const host = event.target.closest(".toolbar-tooltip-host[data-tooltip]");
      if (!(host instanceof HTMLElement)) {
        return;
      }
      if (event.relatedTarget instanceof Node && host.contains(event.relatedTarget)) {
        return;
      }
      hideToolbarTooltip();
    });
    document.addEventListener("pointerdown", (event) => {
      if (!isComposerModelPanelOpen()) {
        return;
      }
      if (!(event.target instanceof Element)) {
        closeComposerModelPanel();
        return;
      }
      if (event.target.closest("#composer-model-panel") || event.target.closest("#composer-model-trigger")) {
        return;
      }
      closeComposerModelPanel();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && isComposerModelPanelOpen()) {
        closeComposerModelPanel({ focusTrigger: true });
      }
    });
    $("tree-root").addEventListener("scroll", () => {
      positionBranchDetailOverlay();
    });
    document.querySelector(".chat-header-actions")?.addEventListener("scroll", () => {
      positionToolbarTooltip();
    });
    branchDetailOverlay().addEventListener("mouseenter", () => {
      clearBranchDetailHideTimer();
      if (state.detailThreadId) {
        applyEdgeVisibility(state.detailThreadId);
      }
    });
    branchDetailOverlay().addEventListener("mouseleave", (event) => {
      const anchorShell = currentDetailAnchorShell();
      if (event.relatedTarget instanceof Node && anchorShell?.contains(event.relatedTarget)) {
        return;
      }
      scheduleHideBranchDetail();
    });
    branchDetailOverlay().addEventListener("focusin", () => {
      clearBranchDetailHideTimer();
    });
    branchDetailOverlay().addEventListener("focusout", (event) => {
      const anchorShell = currentDetailAnchorShell();
      if (
        event.relatedTarget instanceof Node &&
        (branchDetailOverlay()?.contains(event.relatedTarget) || anchorShell?.contains(event.relatedTarget))
      ) {
        return;
      }
      scheduleHideBranchDetail();
    });
    document.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) {
        return;
      }
      if (event.target.closest("[data-branch-action]")) {
        return;
      }
      if (event.target.closest("#tree-root")) {
        return;
      }
      if (!state.detailThreadId || branchDetailOverlay()?.contains(event.target)) {
        return;
      }
      hideBranchDetail();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") {
        return;
      }
      if (!$("merge-review-modal").hidden) {
        closeMergeReviewModal();
        return;
      }
      if (!$("branch-create-modal").hidden) {
        closeBranchCreateModal();
        return;
      }
      if (!state.detailThreadId) {
        return;
      }
      hideBranchDetail();
    });
    $("modal-backdrop").addEventListener("click", () => {
      if (!$("merge-review-modal").hidden) {
        closeMergeReviewModal();
      }
      if (!$("branch-create-modal").hidden) {
        closeBranchCreateModal();
      }
    });
    $("panel-resizer").addEventListener("pointerdown", beginSidebarResize);
    $("panel-resizer").addEventListener("keydown", handleResizerKeydown);
    window.addEventListener("pointermove", updateSidebarResize);
    window.addEventListener("pointerup", endSidebarResize);
    window.addEventListener("pointercancel", endSidebarResize);
    window.addEventListener("resize", () => {
      if (window.innerWidth > 960) {
        const current = Number.parseInt(
          getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width"),
          10
        );
        if (Number.isFinite(current)) {
          applySidebarWidth(current, false);
        }
      } else {
        document.body.classList.remove("is-resizing");
        activeResizePointerId = null;
      }
      positionBranchDetailOverlay();
      positionToolbarTooltip();
      scheduleActiveThreadPillRefresh();
    });
    if (typeof ResizeObserver !== "undefined") {
      const headerResizeObserver = new ResizeObserver(() => {
        scheduleActiveThreadPillRefresh();
      });
      const headerTop = document.querySelector(".chat-header-top");
      const headerActions = document.querySelector(".chat-header-actions");
      if (headerTop) {
        headerResizeObserver.observe(headerTop);
      }
      if (headerActions) {
        headerResizeObserver.observe(headerActions);
      }
    }
    colorModeQuery.addEventListener("change", () => {
      if (state.themePreference === "system") {
        applyColorMode("system", false);
      }
    });
    loadColorModePreference();
    loadAccentThemePreference();
    loadSidebarWidthPreference();
    loadSidebarCollapsedPreference();
    syncLanguagePicker();
    syncToolbarTitles();
    updateTreeBranchSummary();
    autoResizeComposerInput();
    closeAllModals();
    syncDefaultThreadIds();
    updateBranchCreationUi();
    updateMergeArtifactsField();
    scheduleActiveThreadPillRefresh();
    if (document.fonts && typeof document.fonts.ready?.then === "function") {
      document.fonts.ready.then(() => {
        scheduleActiveThreadPillRefresh();
      });
    }
    Promise.resolve(issueToken())
      .then(() => loadAvailableModels())
      .then(() => loadTree())
      .then(() => loadThreadState(state.activeThreadId))
      .catch((error) => {
        const message = error instanceof Error ? error.message : String(error);
        showUiError("startup failed", message);
      });
  </script>
</body>
</html>
"""


ZH_REPLACEMENTS = [
    ('<html lang="en">', '<html lang="zh-CN">'),
    ("<title>Focus Agent Console</title>", "<title>Focus Agent 控制台</title>"),
    ("Branch-aware research chat with a focused conversation view.", "带分支能力的研究对话界面，保留聚焦的聊天体验。"),
    ("How branches work", "分支如何使用"),
    ("1. Start the conversation in the main thread.", "1. 先在主线程里开始对话。"),
    ("2. Click New branch whenever you want to spin out a focused side path.", "2. 想单独展开一个方向时，点击新建分支即可。"),
    ("3. Hover here any time if you want to see this reminder again.", "3. 之后想再看这段说明，鼠标移到这里就会显示。"),
    (">Branches<", ">分支树<"),
    (
        "Hover or click any node to inspect its branch details, then open it only when you want to switch context.",
        "悬浮或点击任意节点查看分支详情，需要切换上下文时再打开它。",
    ),
    (">Archived branches<", ">已归档分支<"),
    ("Archived branches are hidden from the tree until you activate them again.", "已归档分支不会出现在分支树中，重新激活后才会回来。"),
    ("No archived branches.", "暂无已归档分支。"),
    ("Collapse sidebar", "收起侧栏"),
    ("Show branches", "显示分支树"),
    ("New branch", "新建分支"),
    ("Refresh branches", "刷新分支树"),
    ("In progress 0 · Archived 0", "进行中 0 · 已归档 0"),
    ("Resize panels", "调整面板宽度"),
    ("Language", "语言"),
    ("Theme", "主题"),
    ("Color", "色系"),
    ("current色系", "currentColor"),
    ("Follow system", "跟随系统"),
    ("Light", "浅色"),
    ("Dark", "深色"),
    ("White", "白色"),
    ("Blue", "蓝色"),
    ("Mint", "薄荷"),
    ("Sunset", "暮光"),
    ("Graphite", "石墨"),
    ("Start chatting here. Branches appear on the left whenever the agent forks work.", "从这里开始聊天。只要 Agent 产生分支，左侧就会显示出来。"),
    ("Agent status", "Agent 运行状态"),
    ("Ready for your next prompt. Live agent progress and tool activity will appear here.", "等待你的下一条消息。Agent 的运行进度和工具调用会实时显示在这里。"),
    ("No recent agent activity yet.", "还没有最近的 Agent 运行事件。"),
    (">idle<", ">空闲<"),
    (">Composer<", ">输入区<"),
    ("branch-aware chat", "分支对话"),
    ("Back to main", "回到主分支"),
    ("Back one level", "回到上一层"),
    ("current: Main", "当前分支: 主线"),
    ("Send message", "发送消息"),
    ("Clear input", "清空输入"),
    ("Thinking mode", "思考模式"),
    ("Thinking unavailable", "不支持思考切换"),
    ("Thinking available, default on", "支持思考，默认开启"),
    ("Thinking available", "支持思考"),
    ("Thinking on", "思考已开启"),
    ("Thinking off", "思考已关闭"),
    ('disabled>On</button>', 'disabled>开启</button>'),
    ('disabled>Off</button>', 'disabled>关闭</button>'),
    ('aria-label="Model selector"', 'aria-label="模型选择器"'),
    ("Choose a model", "选择模型"),
    ("Search models", "搜索模型"),
    ("No matching models", "没有匹配的模型"),
    ("Loading models...", "加载模型中..."),
    (
        "Keep the current thread focused here. Create a branch only when you want to split into a separate direction.",
        "这里先保持当前线程聚焦。只有当你想把问题拆到独立方向时，再创建分支。",
    ),
    (
        'placeholder="Start on the main thread, and create a branch only when you want to explore a separate direction."',
        'placeholder="先在主线程里展开对话，只有在需要单独探索一个方向时再创建分支。"',
    ),
    ('<span class="sr-only">Message</span>', '<span class="sr-only">消息</span>'),
    ('aria-label="Message"', 'aria-label="消息"'),
    ("thread: researcher-1-main", "线程: researcher-1-main"),
    ("You · ", "你 · "),
    ("Focus Agent · ", "Focus Agent · "),
    ("System", "系统"),
    ('setStatus("idle")', 'setStatus("空闲")'),
    ('setStatus("streaming text", "success")', 'setStatus("正在输出文本", "success")'),
    ('setStatus("text completed", "success")', 'setStatus("文本输出完成", "success")'),
    ('setStatus("thinking", "warn")', 'setStatus("思考中", "warn")'),
    ('setStatus("creating branch", "warn")', 'setStatus("创建分支中", "warn")'),
    ('setStatus("branch created", "success")', 'setStatus("分支已创建", "success")'),
    ('setStatus("archiving branch", "warn")', 'setStatus("归档分支中", "warn")'),
    ('setStatus("branch archived", "success")', 'setStatus("分支已归档", "success")'),
    ('setStatus("activating branch", "warn")', 'setStatus("激活分支中", "warn")'),
    ('setStatus("branch activated", "success")', 'setStatus("分支已激活", "success")'),
    ('setStatus("loading thread", "warn")', 'setStatus("加载线程中", "warn")'),
    ('setStatus("thread ready", "success")', 'setStatus("线程已就绪", "success")'),
    ('setStatus("generating conclusion", "warn")', 'setStatus("生成分支结论中", "warn")'),
    ('setStatus("conclusion ready to merge", "success")', 'setStatus("结论已生成，可带回上游", "success")'),
    ('setStatus("merging upstream", "warn")', 'setStatus("带回上游中", "warn")'),
    ('setStatus("merged upstream", "success")', 'setStatus("已带回上游", "success")'),
    ('setStatus("failed", "danger")', 'setStatus("执行失败", "danger")'),
    ('setStatus("turn completed", "success")', 'setStatus("本轮对话完成", "success")'),
    ('setStatus("waiting for resume", "warn")', 'setStatus("等待继续执行", "warn")'),
    ('setStatus("connecting", "warn")', 'setStatus("连接中", "warn")'),
    ('showUiError("request failed", message);', 'showUiError("请求失败", message);'),
    ('showUiError("create branch failed", message);', 'showUiError("创建分支失败", message);'),
    ('showUiError("load tree failed", message);', 'showUiError("加载分支树失败", message);'),
    ('showUiError("load thread failed", message);', 'showUiError("加载线程失败", message);'),
    ('showUiError("archive branch failed", message);', 'showUiError("归档分支失败", message);'),
    ('showUiError("activate branch failed", message);', 'showUiError("激活分支失败", message);'),
    ('showUiError("merge action failed", message);', 'showUiError("带回上游失败", message);'),
    ('showUiError("startup failed", message);', 'showUiError("启动失败", message);'),
    ('activateButton.textContent = "Activate";', 'activateButton.textContent = "激活";'),
    ('archiveButton.textContent = "Archive";', 'archiveButton.textContent = "归档";'),
    ('resetChatHistory(`Thread ${threadId} is ready. Continue the conversation here.`);', 'resetChatHistory(`线程 ${threadId} 已切换完成，可以在这里继续对话。`);'),
    (
        '`Request failed: ${payload.message || payload.error || "unknown error"}`',
        '`请求失败：${payload.message || payload.error || "未知错误"}`',
    ),
    ('[Waiting for resume decision]', '[等待继续执行决策]'),
    ('$("active-thread-pill").textContent = `thread: ${node.thread_id}`;', '$("active-thread-pill").textContent = `线程: ${node.thread_id}`;'),
    ('$("active-thread-pill").textContent = `thread: ${state.activeThreadId}`;', '$("active-thread-pill").textContent = `线程: ${state.activeThreadId}`;'),
    ('throw new Error("Streaming response body is unavailable.");', 'throw new Error("流式响应不可用。");'),
    ('$("chat-history").innerHTML = \'<div id="chat-empty" class="chat-empty">Start chatting here. Branches appear on the left whenever the agent forks work.</div>\';', '$("chat-history").innerHTML = \'<div id="chat-empty" class="chat-empty">从这里开始聊天。只要 Agent 产生分支，左侧就会显示出来。</div>\';'),
]


def render_chat_app_html(lang: str = "en") -> str:
    if not lang.lower().startswith("zh"):
        return BRANCH_TREE_HTML

    html = BRANCH_TREE_HTML
    for source, target in ZH_REPLACEMENTS:
        html = html.replace(source, target)
    return html


render_branch_tree_html = render_chat_app_html
