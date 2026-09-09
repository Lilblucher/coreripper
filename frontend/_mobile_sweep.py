#!/usr/bin/env python3
"""
CoreRipper mobile override sweep.

Inserts (or replaces) a single <style id="cr-mobile"> block just before </head>
in every *.html under frontend/. Idempotent: wrapped in CR_MOBILE_START/END
markers so re-running replaces in place instead of stacking.

Design principle: the block only activates below 768px. Desktop layouts are
completely untouched, and no animations are altered — only layout, spacing,
and tap targets are overridden for mobile.
"""
import os
import re
import glob
import subprocess
import tempfile
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

MOBILE_CSS = r"""
<!-- CR_MOBILE_START do not hand-edit  regenerate with _mobile_sweep.py -->
<style id="cr-mobile">
/* ================================================================
   CoreRipper mobile override layer (<=768px).
   Keeps every desktop layout untouched; overrides only sizing,
   spacing, tap targets and grid direction for phones. All
   animations are preserved. Regenerate via _mobile_sweep.py.
   ================================================================ */
@media (max-width: 768px) {
  html, body { max-width: 100vw; overflow-x: hidden; -webkit-text-size-adjust: 100%; }
  body { font-size: 15px; line-height: 1.55; }

  /* Kill horizontal overflow from any oversized child */
  img, video, canvas, svg, iframe, table, pre, code { max-width: 100%; }
  img, video, canvas, iframe { height: auto; }
  pre, code, .mono-cell { overflow-x: auto; word-break: break-word; -webkit-overflow-scrolling: touch; }
  table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }

  /* Standardize container padding site-wide */
  main, .container, .max-w-7xl, .max-w-6xl, .max-w-5xl, .max-w-4xl,
  .max-w-3xl, .max-w-2xl, .max-w-xl, .max-w-lg, .max-w-md, .max-w-sm {
    padding-left: 16px !important; padding-right: 16px !important;
    max-width: 100% !important;
  }

  /* Collapse all common multi-column grids to a single column */
  .grid-cols-2, .grid-cols-3, .grid-cols-4, .grid-cols-5,
  .md\:grid-cols-2, .md\:grid-cols-3, .md\:grid-cols-4,
  .lg\:grid-cols-2, .lg\:grid-cols-3, .lg\:grid-cols-4,
  .sm\:grid-cols-2, .sm\:grid-cols-3 {
    grid-template-columns: 1fr !important;
  }

  /* Two-column layouts used site-wide (Workbench, hero splits) */
  .cr-half { flex: 0 0 100% !important; width: 100% !important; max-width: 100% !important; }
  .cr-frame, .cr-bar { flex-wrap: wrap !important; }

  /* Nav / header: keep the site's own hamburger, hide desktop link row + top CTA.
     support.html (and any other page following the same pattern) nests its
     hamburger button *inside* .nav-links, so blindly hiding the whole
     container took the hamburger down with it  leaving zero way to
     navigate or reach the mobile menu on that page. Hide only the link
     children, and force the hamburger back on regardless of which
     container it's nested in. */
  .cr-nav-links > *, .nav-links > a, .desktop-nav > * { display: none !important; }
  .nav-links .cr-appshell-menu-btn, .nav-links .cr-menu-btn { display: inline-flex !important; }
  nav .cta-btn, header .cta-btn, .site-header .cta-btn { display: none !important; }
  .cr-nav, header nav, .site-header { padding-left: 12px !important; padding-right: 12px !important; }
  .cr-menu-btn, #crMenuBtn, .hamburger, .mobile-menu-btn { display: inline-flex !important; }

  /* Logged-in header overflow fix (2026-07-31): the credit chip + account
     dropdown replace Login/Get Started once a user is signed in, but at
     phone widths those two plus the hamburger plus the decorative search
     icon never fit on one row  the username label (up to 130px on desktop)
     pushed the hamburger button off-screen entirely, so a logged-in user on
     mobile had no way to open the nav menu at all. Fix: drop the decorative
     search icon, shrink the credit chip and truncate the username hard, and
     pin the hamburger so it can never be squeezed out. */
  nav svg[stroke="#9ca3af"], .ts-nav-right > svg,
  nav button:has(> svg.anim-scan) { display: none !important; }
  nav .flex.items-center.gap-4, nav .flex.items-center.gap-3 { gap: 6px !important; }
  .ts-nav-right { gap: 8px !important; flex-wrap: nowrap !important; }
  .cr-credit-chip { padding: 5px 8px !important; font-size: 12px !important; gap: 4px !important; }
  .cr-credit-chip svg { width: 11px !important; height: 11px !important; }
  .cr-nav-dropdown .cr-dd-btn {
    padding: 5px 6px !important; gap: 3px !important; flex-shrink: 1 !important; min-width: 0 !important;
  }
  .cr-nav-dropdown .cr-dd-btn #navUserLabel, #navUserLabel {
    max-width: 54px !important; font-size: 12px !important;
  }
  .cr-nav-dropdown .cr-dd-chevron { flex-shrink: 0 !important; width: 10px !important; height: 10px !important; }
  .cr-menu-btn, .ts-menu-btn, #tsMenuBtn { flex-shrink: 0 !important; margin-left: 2px !important; }
  #crCreditWrap, .cr-credit-wrap { flex-shrink: 1 !important; min-width: 0 !important; }

  /* settings.html/billing.html/support.html's header carries a "Dashboard"
     text link and a "Back to Site" button alongside the hamburger and
     account dropdown  on top of the app-shell menu button, that's 4-5
     interactive elements crammed in one row, wide enough to push the
     account dropdown itself off the right edge of a phone screen entirely
     (confirmed: navUserWrap rendered at x=402 on a 375px-wide viewport).
     Both links duplicate destinations already one tap away (Workbench via
     the dropdown, Home via the logo), so they're the ones to drop, not the
     hamburger or the dropdown. */
  .wb-nav-inner a[href="dashboard.html"], .wb-nav-inner .secondary-btn,
  .wb-nav-inner .nav-back { display: none !important; }
  .cr-appshell-menu-btn, #navUserWrap.cr-nav-dropdown { flex-shrink: 0 !important; }

  /* Nav dropdowns on mobile: same as desktop (absolute below trigger),
     just ensure they don't overflow the viewport. Closes on outside tap
     via the script block below. */
  .cr-dd-menu {
    max-width: calc(100vw - 24px) !important;
    max-height: 70vh !important; overflow-y: auto !important;
    z-index: 9999 !important;
  }
  .cr-dd-menu .cr-dd-item {
    padding: 12px 18px !important; font-size: 14px !important;
  }
  .cr-dd-menu .cr-dd-email {
    padding: 8px 18px 4px !important; font-size: 12px !important;
  }
  .cr-dd-menu .cr-dd-divider { margin: 4px 14px !important; }
  /* Dashboard's own user dropdown */
  .wb-user-dropdown {
    max-width: calc(100vw - 24px) !important;
    max-height: 70vh !important; overflow-y: auto !important;
    z-index: 9999 !important;
  }
  .wb-dd-item { padding: 12px 18px !important; font-size: 14px !important; }
  /* Credit dropdown */
  .cr-credit-menu {
    max-width: calc(100vw - 24px) !important;
    max-height: 70vh !important; overflow-y: auto !important;
    z-index: 9999 !important;
  }

  /* Tap targets  minimum 40x40 for anything interactive in headers/menus.
     Deliberately excludes plain footer text links: those get their own
     compact sizing below (footer is a dense link list, not primary nav),
     and forcing 40px per link there was bloating the footer's height. */
  .cr-nav a, .cr-nav button, .nav-link, .cr-dd-item, .cr-menu-btn,
  header a, header button, .site-header a, .site-header button
  { min-height: 40px; display: inline-flex; align-items: center; }
  button, .btn, [role="button"], input[type="submit"], input[type="button"] {
    min-height: 40px; padding-top: 10px; padding-bottom: 10px;
  }

  /* Forms: full-width, 16px font (prevents iOS zoom-on-focus) */
  input, select, textarea {
    font-size: 16px !important; width: 100%; box-sizing: border-box;
    min-height: 44px;
  }
  textarea { min-height: 96px; }
  form .row, form .field-group { flex-direction: column !important; gap: 10px !important; }

  /* Headings / hero */
  h1 { font-size: clamp(24px, 6.5vw, 32px) !important; line-height: 1.2 !important; }
  h2 { font-size: clamp(20px, 5.5vw, 26px) !important; line-height: 1.25 !important; }
  h3 { font-size: clamp(17px, 4.6vw, 20px) !important; }
  .hero, .hero-section, section.hero { padding-top: 32px !important; padding-bottom: 32px !important; }

  /* Cards / tool cards  tighter on phones */
  .card, .tool-card, .ts-card, .ts-price-card, .ts-newscard, .ts-chipcard,
  .cr-card, .s-card {
    padding: 16px !important; border-radius: 12px !important;
  }

  /* ================================================================
     Tool hub pages (net_tools / dev_tools / ai_tools)
     ================================================================ */
  /* Tool cards  compact layout on phones: smaller icon, tighter spacing */
  .tool-card .icon-box { width: 40px !important; height: 40px !important; border-radius: 10px !important; }
  .tool-card .icon-box svg { width: 20px !important; height: 20px !important; }
  .tool-card h4 { font-size: 15px !important; }
  .tool-card p { font-size: 13px !important; margin-bottom: 10px !important; }
  .tool-card a { font-size: 13px !important; }
  /* Badges (FREE / PREMIUM / COMING SOON / lock)  keep inline, don't overlap */
  .badge { font-size: 0.65rem !important; padding: 0.15rem 0.5rem !important; }
  .badge-soon { font-size: 0.6rem !important; }
  .lock-badge, .tool-lock-badge { font-size: 10px !important; padding: 2px 7px !important; }
  .upgrade-hint { font-size: 11px !important; }
  /* net_tools.html's "Email/Domain Breach Check" card hardcodes its Coming
     Soon badge as an inline `position:absolute; top:14px; right:14px` span
     instead of using the .badge-soon class the other cards use  the other
     cards' badges got caught by the rule above, this one didn't, and at
     phone widths the card title wraps to two lines right under it, so the
     badge sits on top of the word "Check". !important here beats the
     inline style same as everywhere else in this stylesheet. */
  .tool-card > span[style*="position:absolute"] {
    position: static !important; display: inline-block !important;
    margin: 0 0 10px !important;
  }
  /* Category sections  tighter accordion headers */
  .category-toggle { padding: 14px 0 !important; }
  .category-toggle h3 { font-size: 16px !important; }
  /* Search bar on hub pages */
  .search-wrap { margin-bottom: 20px !important; }
  .search-wrap input { font-size: 15px !important; padding: 12px 14px !important; }
  /* Tab buttons (DNS/SSL/Ping etc. on net_tools) */
  .tab-btn { padding: 10px 12px !important; font-size: 13px !important; white-space: nowrap; }
  /* Results area */
  .result-card { padding: 14px !important; }
  .result-label { font-size: 0.8rem !important; }
  .result-value { font-size: 13px !important; }

  /* ================================================================
     Individual tool pages (networking/*, dev-tools/*, ai-tools/*)
     ================================================================ */
  /* Hero input area  full width, stack form elements */
  .tool-hero, .tool-input-area, .input-section {
    padding: 20px 14px !important;
  }
  /* Result panels + terminal output */
  .result-panel, .output-panel, pre.result, .terminal, .code-output {
    font-size: 12.5px !important; padding: 12px !important; border-radius: 10px !important;
  }
  /* Copy buttons inside result blocks */
  .copy-btn, [data-copy], button[onclick*="copy"] {
    font-size: 11px !important; padding: 4px 8px !important;
  }

  /* ================================================================
     Content pages (blog / news / hardware)
     ================================================================ */
  /* Article card grids  these use Tailwind grids which are already collapsed,
     but the cards themselves need tighter spacing */
  .article-card, .news-card, .hw-card, .blog-card, .post-card {
    padding: 14px !important; border-radius: 12px !important;
  }
  .article-card img, .news-card img, .hw-card img, .blog-card img {
    border-radius: 10px !important; margin-bottom: 10px !important;
  }
  /* Filter/tag strips on content pages */
  .filter-bar, .tag-bar, .content-filters {
    overflow-x: auto !important; flex-wrap: nowrap !important;
    -webkit-overflow-scrolling: touch; scrollbar-width: none;
    gap: 8px !important; padding-bottom: 4px;
  }
  .filter-bar::-webkit-scrollbar, .tag-bar::-webkit-scrollbar,
  .content-filters::-webkit-scrollbar { display: none; }
  /* Article detail pages  readable line length */
  .article-body, .post-body, .post-content, .blog-content {
    font-size: 15px !important; line-height: 1.7 !important;
    padding: 0 !important;
  }
  .article-body h2, .post-body h2, .blog-content h2 { font-size: 20px !important; margin-top: 28px !important; }
  .article-body h3, .post-body h3, .blog-content h3 { font-size: 17px !important; }
  .article-body img, .post-body img { border-radius: 10px !important; }
  .article-body pre, .post-body pre { font-size: 12px !important; padding: 12px !important; overflow-x: auto; }
  /* Sidebar on content pages  collapse below main content */
  .content-sidebar, .blog-sidebar, .article-sidebar {
    position: static !important; width: 100% !important;
    margin-top: 24px !important;
  }

  /* ================================================================
     Account pages (settings / billing / support)
     ================================================================ */
  /* Section cards on settings/billing  full-width, no side padding excess */
  .settings-card, .billing-card, .account-section, .support-card {
    padding: 16px !important; border-radius: 12px !important;
  }
  /* Plan cards on billing  single column */
  .plan-grid, .plans-grid { grid-template-columns: 1fr !important; gap: 12px !important; }
  /* Mobile money operator tiles (billing.html)  2 columns at most */
  .pm-tiles { grid-template-columns: 1fr 1fr !important; gap: 8px !important; }
  /* Payment form  stack amount/method fields */
  .payment-form, .checkout-form { padding: 16px !important; }
  .payment-row, .checkout-row { flex-direction: column !important; gap: 10px !important; }
  /* Active sessions list on settings */
  .session-row, .device-row {
    flex-direction: column !important; align-items: flex-start !important;
    gap: 6px !important; padding: 12px !important;
  }
  /* Support ticket form */
  .ticket-form textarea { min-height: 120px !important; }

  /* ================================================================
     Pricing page
     ================================================================ */
  /* Price comparison cards  single column, compact */
  .pricing-grid, .price-grid { grid-template-columns: 1fr !important; gap: 14px !important; }
  .pricing-card, .price-card {
    padding: 20px 16px !important; border-radius: 14px !important;
  }
  .pricing-card .price, .price-card .amount { font-size: 28px !important; }
  /* Comparison table  horizontal scroll */
  .comparison-table, .feature-table { display: block !important; overflow-x: auto !important; }
  .comparison-table th, .comparison-table td { white-space: nowrap !important; font-size: 12px !important; padding: 8px 10px !important; }

  /* ================================================================
     Auth pages (login / signup / forgot / reset)
     ================================================================ */
  .auth-card, .cr-auth-card {
    width: 100% !important; max-width: none !important;
    margin: 16px auto !important; padding: 20px 16px !important;
    border-radius: 14px !important;
  }
  .auth-card h1, .cr-auth-card h1 { font-size: 22px !important; }
  .auth-card .auth-logo, .cr-auth-card .auth-logo { margin-bottom: 16px !important; }
  /* Google sign-in button  full width */
  .g_id_signin, [data-google-btn], .google-btn-wrap {
    width: 100% !important; max-width: none !important;
  }
  /* Divider ("or") */
  .auth-divider, .or-divider { margin: 16px 0 !important; }

  /* ================================================================
     Admin / Engine Room (admin.html)
     ================================================================ */
  .admin-tabs, .engine-tabs {
    overflow-x: auto !important; flex-wrap: nowrap !important;
    -webkit-overflow-scrolling: touch; scrollbar-width: none;
    gap: 4px !important;
  }
  .admin-tabs::-webkit-scrollbar, .engine-tabs::-webkit-scrollbar { display: none; }
  .admin-tab, .engine-tab {
    flex-shrink: 0 !important; font-size: 12px !important;
    padding: 8px 12px !important; white-space: nowrap;
  }
  /* Admin cards/tables */
  .admin-card, .engine-card { padding: 14px !important; border-radius: 12px !important; }
  .admin-table, .engine-table { display: block !important; overflow-x: auto !important; font-size: 12px !important; }
  .admin-table th, .admin-table td { padding: 6px 8px !important; white-space: nowrap !important; }
  /* Moderation cards  stack image + content */
  .mod-card { flex-direction: column !important; }
  .mod-card img { width: 100% !important; max-height: 200px !important; object-fit: cover !important; border-radius: 10px !important; }

  /* Homepage tool-showcase slideshow  keep the animation, cap the height */
  .ts-viewport { height: auto !important; min-height: 340px; }
  .ts-slide { padding: 22px 18px !important; }
  .ts-slide-name { font-size: 17px !important; }
  .ts-slide-desc { font-size: 13px !important; max-width: 100% !important; }
  .ts-slide-icon { width: 40px !important; height: 40px !important; }
  .ts-slide-icon svg { width: 22px !important; height: 22px !important; }

  /* Homepage pricing / feature grids */
  .ts-price-card { padding: 20px 18px !important; }
  .ts-price-amount { font-size: 30px !important; }

  /* Section paddings across the site */
  section, .section, .ts-sec { padding-top: 36px !important; padding-bottom: 36px !important; }
  .ts-sec-inner, section > .container, section > div { padding-left: 16px !important; padding-right: 16px !important; }

  /* Footer  keep the site's own 2-col link grid (it's already mobile-tuned),
     just tighten it further so it doesn't run long. Brand block always
     spans the full row above the link columns. */
  .cr-footer { padding: 20px 16px 10px !important; }
  .cr-footer-grid {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 10px 16px !important;
    margin-bottom: 10px !important;
  }
  .cr-footer-brand-col { grid-column: 1 / -1 !important; margin-bottom: 4px; }
  .cr-footer-brand-col, .cr-footer-col { max-width: 100%; }
  .cr-footer-col { gap: 4px !important; }
  .cr-footer-col .head { font-size: 11px !important; margin-bottom: 2px !important; }
  .cr-footer-col a { font-size: 13px !important; line-height: 1.5 !important; }
  .cr-footer-blurb { font-size: 12.5px !important; margin: 2px 0 !important; }
  footer .cr-footer-social { justify-content: flex-start !important; gap: 12px !important; }
  /* Social icons are icon-only links  they still need a real tap target,
     unlike the plain text links above. */
  .cr-footer-social a { min-height: 40px !important; min-width: 40px !important; justify-content: center !important; }
  .cr-footer-bottom { flex-direction: column !important; align-items: flex-start !important; padding-top: 10px !important; }
  /* Non-.ts-* generic footer/grid containers elsewhere on the page still stack */
  footer .grid:not(.cr-footer-grid) { grid-template-columns: 1fr !important; }

  /* Cookie / consent banner  no bottom-right overlap of key UI */
  .cr-consent-banner { left: 8px !important; right: 8px !important; bottom: 8px !important;
    max-width: none !important; padding: 14px !important; border-radius: 12px !important; }
  .cr-consent-inner, .cr-consent-actions { flex-direction: column !important; align-items: stretch !important; gap: 10px !important; }
  .cr-consent-btn { width: 100% !important; }

  /* Modals / dialogs */
  .modal, .cr-modal, dialog, [role="dialog"] {
    width: calc(100vw - 24px) !important; max-width: calc(100vw - 24px) !important;
    max-height: calc(100vh - 24px) !important; overflow-y: auto !important;
    padding: 18px !important; border-radius: 14px !important;
  }

  /* ================================================================
     Dashboard / Workbench  comprehensive phone + tablet layout
     ================================================================ */
  /* Nav bar  compact, no overflow */
  .wb-nav-inner {
    padding: 0 12px !important; height: 54px !important; gap: 10px !important;
  }
  .wb-nav-inner .cr-logo { gap: 6px !important; }
  .wb-nav-inner .cr-logo-tile { width: 28px !important; height: 28px !important; }
  .wb-nav-inner .cr-logo-tile svg { width: 20px !important; height: 20px !important; }
  .wb-nav-inner .cr-wordmark { font-size: 15px !important; }
  /* Hide the "Workbench" title + plan pill filler block  scoped with :has()
     to the one div that actually contains .wb-premium-pill, since settings/
     billing/support also share the .wb-nav-inner class but put a completely
     different 2nd child there (the Dashboard link + hamburger + Back to Site
     + account-dropdown actions group). An un-scoped nth-child(2) previously
     nuked that whole actions group on those three pages  including the only
     way to open the account dropdown or log out on mobile. */
  .wb-nav-inner > div:nth-child(2):has(.wb-premium-pill) { display: none !important; }
  .wb-premium-pill { font-size: 10px !important; padding: 3px 8px !important; }
  .wb-credits-pill { padding: 5px 8px !important; }
  .wb-credits-pill .mono { font-size: 11px !important; }
  #navRight { gap: 8px !important; }

  /* Header band  tighter padding */
  .wb-header-inner { padding: 20px 14px 0 !important; }
  .wb-h1 { font-size: 22px !important; }
  .wb-subtitle { font-size: 13px !important; }
  .wb-tabs { gap: 18px !important; margin-top: 14px !important; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
  .wb-tabs::-webkit-scrollbar { display: none; }
  .wb-tab-btn { font-size: 13px !important; white-space: nowrap; flex-shrink: 0; }

  /* Run bar  stack vertically */
  .wb-runbar-wrap { padding: 14px 12px 0 !important; }
  .wb-runbar { padding: 14px !important; flex-direction: column !important; gap: 12px !important; border-radius: 12px !important; }
  .wb-runbar > div, .wb-runbar > label { width: 100% !important; }
  .wb-run-btn { width: 100% !important; text-align: center !important; }

  /* Main 3-col grid  single column */
  .wb-grid {
    grid-template-columns: 1fr !important; padding: 14px 12px 80px !important; gap: 14px !important;
  }
  .wb-sidebar-col, .wb-rightrail-col {
    position: static !important; max-height: none !important;
    overflow-y: visible !important;
  }
  /* On phones, move sidebar (tool picker) above main stream */
  .wb-sidebar-col { order: -1 !important; }

  /* Cards  slightly tighter */
  .wb-card { padding: 12px 14px !important; border-radius: 11px !important; }
  .wb-result-card { padding: 14px !important; border-radius: 12px !important; }
  .wb-result-card:hover { transform: none !important; }
  .wb-card-head { gap: 8px !important; }

  /* Tool picker  horizontal scroll strip instead of full sidebar list */
  .wb-tool-row { padding: 7px 8px !important; font-size: 12px !important; }
  .wb-add-row { flex-direction: column !important; }

  /* Batch progress  wrap chips */
  .wb-batch { padding: 12px 14px !important; border-radius: 11px !important; }
  .wb-batch-head { gap: 8px !important; }
  .wb-batch-chips { gap: 6px !important; }
  .wb-batch-chip { font-size: 11px !important; }
  .wb-batch-save-row { flex-direction: column !important; gap: 8px !important; align-items: stretch !important; }

  /* Flat grid results (key-value pairs inside result cards) */
  .wb-flat-grid { grid-template-columns: 1fr !important; gap: 8px !important; }

  /* Tables inside results  stack into cards */
  .wb-table-wrap { margin-bottom: 10px !important; }
  .wb-table th { font-size: 10px !important; padding: 5px 6px !important; }
  .wb-table td { font-size: 11.5px !important; padding: 5px 6px !important; white-space: normal !important; }

  /* Diff rows  stack before/after */
  .wb-diff-row { flex-direction: column !important; gap: 8px !important; }
  .wb-diff-box { min-width: 0 !important; }

  /* Stream filters  scrollable */
  .wb-filters { overflow-x: auto !important; flex-wrap: nowrap !important; -webkit-overflow-scrolling: touch; scrollbar-width: none; padding-bottom: 4px; }
  .wb-filters::-webkit-scrollbar { display: none; }
  .wb-filter-pill { flex-shrink: 0 !important; font-size: 11.5px !important; }

  /* Actions row  wrap buttons */
  .wb-actions-row { gap: 6px !important; }
  .wb-btn-ghost, .wb-btn-primary { font-size: 11.5px !important; padding: 6px 10px !important; }

  /* Saved Results view */
  .wb-saved-wrap { padding: 16px 12px 80px !important; }
  .wb-project-card { padding: 14px !important; }
  .wb-project-row { gap: 8px !important; }
  .wb-loose-row { padding: 10px 12px !important; gap: 8px !important; }

  /* Floating Assistant  bottom-sheet (phones; tablet uses page's own 640px rule) */
  .wb-assistant-panel {
    left: 0 !important; right: 0 !important; bottom: 0 !important; top: auto !important;
    width: 100% !important; height: 70vh !important; max-height: calc(100vh - 60px) !important;
    border-radius: 18px 18px 0 0 !important; resize: none !important;
  }
  .wb-assistant-head { cursor: default !important; }
  .wb-assistant-grip, .wb-assistant-resize { display: none !important; }
  .wb-assistant-body { padding: 12px 14px !important; }
  .wb-msg-bubble { max-width: 90% !important; font-size: 13px !important; }
  .wb-assistant-input-row { padding: 10px 12px calc(env(safe-area-inset-bottom, 8px) + 10px) !important; }

  /* FAB  smaller on phone, stay above bottom-sheet */
  .wb-assistant-toggle { right: 14px !important; bottom: 14px !important; width: 46px !important; height: 46px !important; }

  /* Monitors add-form inside right rail  full-width fields */
  .wb-phone-wrap { border-radius: 8px !important; }
  .wb-dial-dropdown { left: 12px !important; right: 12px !important; width: auto !important; max-width: none !important; }

  /* Modal  full-width on phones */
  .wb-modal { padding: 20px 16px !important; max-width: calc(100vw - 24px) !important; border-radius: 14px !important; }
  .wb-toast { left: 12px !important; right: 12px !important; bottom: 16px !important; transform: none !important; text-align: center !important; }

  /* Gate/access screens */
  .wb-gate-wrap { min-height: 50vh !important; padding: 30px 16px !important; }

  /* Empty state */
  .wb-empty { padding: 36px 16px !important; }

  /* New section button */
  .wb-new-section { padding: 10px !important; font-size: 12px !important; }

  /* Code blocks inside results  allow scroll */
  .wb-code-text { font-size: 11.5px !important; padding-right: 40px !important; }

  /* Tool pages  the tool nav rail collapses to a horizontal scroller */
  .tool-nav, .tool-nav-list, .sidebar-tools {
    display: flex !important; flex-direction: row !important; overflow-x: auto !important;
    white-space: nowrap; gap: 8px !important; padding: 8px !important;
    -webkit-overflow-scrolling: touch; scrollbar-width: none;
  }
  .tool-nav::-webkit-scrollbar { display: none; }
  .tool-nav-link { flex: 0 0 auto !important; }

  /* Result panels on tool pages */
  .result-panel, .output-panel, pre.result, .terminal { font-size: 13px !important; }

  /* Key/value result rows (subnet calc, SSL checker, JWT decoder, hash
     generator, etc.)  stack label above value instead of forcing a fixed
     label column that crushes the value into a sliver and, combined with
     word-break:break-all, wraps it one character per line. */
  .kv-row {
    flex-direction: column !important; align-items: flex-start !important;
    gap: 4px !important; padding: 10px 14px !important;
  }
  .kv-label { flex: none !important; width: 100% !important; font-weight: 600 !important; }
  .kv-value { flex: none !important; width: 100% !important; }

  /* Real multi-row results tables (.data-table  DNS propagation, MX/NS
     lookup, port scanner, traceroute, etc.)  collapse into stacked cards
     instead of a horizontally-scrolling grid. Relies on each <td> carrying
     a data-label attribute matching its column header (see individual
     tool pages' render functions). */
  .data-table { display: block !important; width: 100% !important; border: none !important; }
  .data-table thead { display: none !important; }
  .data-table tbody, .data-table tr { display: block !important; width: 100% !important; }
  .data-table tr {
    margin-bottom: 10px !important; border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 10px !important; padding: 4px 12px !important;
    background: rgba(255,255,255,0.02) !important;
  }
  .data-table td {
    display: flex !important; justify-content: space-between !important; align-items: center !important;
    gap: 12px !important; padding: 8px 0 !important; border-bottom: 1px solid rgba(255,255,255,0.06) !important;
    text-align: right !important; white-space: normal !important;
  }
  .data-table tr td:last-child { border-bottom: none !important; }
  .data-table td::before {
    content: attr(data-label); font-weight: 600; color: #9ca3af; font-size: 0.72rem;
    text-transform: uppercase; letter-spacing: 0.02em; flex: 0 0 auto; text-align: left; padding-right: 10px;
  }
  body.light-mode .data-table tr { border-color: rgba(0,0,0,0.08) !important; background: rgba(0,0,0,0.015) !important; }
  body.light-mode .data-table td { border-bottom-color: rgba(0,0,0,0.06) !important; }
  body.light-mode .data-table td::before { color: #6b7280; }

  /* Auth pages (login/signup/forgot/reset) */
  .auth-card, .cr-auth-card { width: 100% !important; max-width: 420px !important; margin: 24px auto !important; padding: 22px !important; }

  /* Splash screen scale on small phones */
  .cr-splash .cr-lockup { transform: scale(0.85); }

  /* Long words / URLs shouldn't blow out cards */
  p, li, td, dd, .card, .tool-card, .s-card { overflow-wrap: anywhere; }

  /* Buttons never wrap to two lines from padding on narrow screens */
  .btn, button { white-space: normal; }

  /* Absolute-positioned decorative blobs often push scrollbars  contain them */
  .decor, .bg-blob, .cr-blob, [data-decor] { max-width: 100vw; overflow: hidden; }

  /* ---- Homepage (index.html) ts-* specific overrides ---- */
  .ts-nav-inner { padding: 0 14px !important; height: 56px !important; }
  .ts-nav-links, .ts-nav-right .ts-cta, .ts-nav-right .ts-btn-primary { display: none !important; }
  .ts-menu-btn { display: inline-flex !important; }
  .ts-hero, .ts-hero-inner { padding: 32px 16px 40px !important; }
  .ts-hero-grid { grid-template-columns: 1fr !important; gap: 24px !important; }
  .ts-search { padding: 32px 16px 40px !important; }
  .ts-cats { padding: 40px 16px !important; }
  .ts-cats-grid { grid-template-columns: 1fr !important; gap: 14px !important; }
  .ts-sec { padding: 40px 16px !important; }
  .ts-sec-head { flex-direction: column !important; align-items: flex-start !important; gap: 14px !important; }
  .ts-footer { padding: 36px 16px 28px !important; }
  .ts-footer-grid, .ts-footer-inner .grid { grid-template-columns: 1fr !important; gap: 22px !important; }
  .ts-price-grid, .ts-features-grid, .ts-pillars-grid { grid-template-columns: 1fr !important; gap: 16px !important; }
  .ts-wb-mock-side { display: none !important; }
  .ts-wb-mock-main { width: 100% !important; }
  .ts-mon-panel, .ts-chipcard { padding: 16px !important; }
  .ts-slider-frame, .ts-window-wrap { max-width: 100% !important; }

  /* Newsletter box  tighten padding/margins so the section doesn't eat a
     full extra screen of scrolling on phones. */
  .ts-newsletter-box { padding: 28px 18px !important; }
  .ts-newsletter-box h2 { font-size: 24px !important; margin-bottom: 8px !important; }
  .ts-newsletter-box p.sub { font-size: 14px !important; margin-bottom: 16px !important; }
  .ts-newsletter-tags { margin-bottom: 16px !important; gap: 6px !important; }

  /* Newsletter "already subscribed" banner  wrap instead of overlapping
     the Subscribe/Unsubscribe button against the status text. */
  .ts-newsletter-success {
    flex-wrap: wrap !important; justify-content: center !important;
    text-align: center !important; padding: 14px 18px !important;
  }
  #newsletterToggleBtn { margin-left: 0 !important; margin-top: 6px !important; }
}

/* --- Extra tightening for very small phones (<=480px) --- */
@media (max-width: 480px) {
  body { font-size: 14.5px; }
  main, .container, .max-w-7xl, .max-w-6xl, .max-w-5xl, .max-w-4xl,
  .max-w-3xl, .max-w-2xl { padding-left: 12px !important; padding-right: 12px !important; }
  section, .section, .ts-sec { padding-top: 28px !important; padding-bottom: 28px !important; }
  h1 { font-size: clamp(22px, 7vw, 28px) !important; }
  .card, .tool-card, .ts-card, .ts-price-card, .cr-card, .s-card { padding: 16px !important; border-radius: 12px !important; }
  .ts-viewport { min-height: 320px; }
  .ts-slide { padding: 18px 14px !important; }
  .ts-slide-name { font-size: 16px !important; }
  .cr-splash .cr-lockup { transform: scale(0.75); }
}

/* --- Tablet portrait (481-768px): dashboard gets 2-col grid --- */
@media (min-width: 481px) and (max-width: 768px) {
  .wb-grid { grid-template-columns: 1fr 1fr !important; }
  .wb-sidebar-col { grid-column: 1 / -1 !important; order: -1 !important; }
  .wb-rightrail-col { grid-column: 1 / -1 !important; }
  .wb-flat-grid { grid-template-columns: 1fr 1fr !important; }
  .wb-runbar { flex-direction: row !important; flex-wrap: wrap !important; }
  .wb-run-btn { width: auto !important; }
}

/* --- Smallest phones (<=360px, e.g. iPhone SE portrait) --- */
@media (max-width: 360px) {
  body { font-size: 14px; }
  main, .container { padding-left: 10px !important; padding-right: 10px !important; }
  h1 { font-size: 22px !important; }
  h2 { font-size: 19px !important; }
  .ts-slide { padding: 16px 12px !important; }
  .ts-slide-icon { width: 36px !important; height: 36px !important; }
  .cr-splash .cr-lockup { transform: scale(0.65); }
}
</style>
<script>
/* Dropdown close-on-outside-tap (2026-07-31).
   Tap anywhere outside an open dropdown to close it. Works on both desktop
   and mobile, for all three dropdown types on every page. */
document.addEventListener('click', function (e) {
  var sel = '.cr-dd-menu.open, .wb-user-dropdown.open, .cr-credit-menu.open';
  var open = document.querySelector(sel);
  if (!open) return;
  if (open.contains(e.target)) return;
  var wrap = open.closest('.cr-nav-dropdown, .wb-user-menu-wrap, .cr-credit-wrap');
  if (wrap) {
    var btn = wrap.querySelector('.cr-dd-btn, .wb-user-btn, .cr-credit-chip');
    if (btn && btn.contains(e.target)) return;
  }
  open.classList.remove('open');
  if (wrap) {
    var b = wrap.querySelector('.cr-dd-btn, .wb-user-btn, .cr-credit-chip');
    if (b) b.setAttribute('aria-expanded', 'false');
  }
});
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  var sel = '.cr-dd-menu.open, .wb-user-dropdown.open, .cr-credit-menu.open';
  var open = document.querySelector(sel);
  if (!open) return;
  open.classList.remove('open');
  var wrap = open.closest('.cr-nav-dropdown, .wb-user-menu-wrap, .cr-credit-wrap');
  var btn = wrap && wrap.querySelector('.cr-dd-btn, .wb-user-btn, .cr-credit-chip');
  if (btn) btn.setAttribute('aria-expanded', 'false');
});
</script>
<!-- CR_MOBILE_END -->
"""

BLOCK_RE = re.compile(
    r"\n?(?:/\* CR_MOBILE_START|<!-- CR_MOBILE_START).*?<!-- CR_MOBILE_END -->\n?",
    re.DOTALL,
)


def sweep(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # Remove any previous injection
    src = BLOCK_RE.sub("", src)

    # Find </head>
    m = re.search(r"</head>", src, re.IGNORECASE)
    if not m:
        return "no-head"

    injected = src[: m.start()] + MOBILE_CSS + src[m.start():]
    if injected == src:
        return "unchanged"
    with open(path, "w", encoding="utf-8") as f:
        f.write(injected)
    return "written"


def script_syntax_check(path: str) -> list:
    """Run node --check on every non-src inline <script> and return list of failing pages."""
    fails = []
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.DOTALL):
        code = m.group(1).strip()
        if not code:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tf:
            tf.write(code)
            tmp = tf.name
        try:
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
            if r.returncode:
                fails.append(r.stderr.strip().splitlines()[-1])
        finally:
            os.unlink(tmp)
    return fails


def main():
    pages = sorted(glob.glob(os.path.join(ROOT, "**/*.html"), recursive=True))
    written = skipped = failed = 0
    for p in pages:
        try:
            outcome = sweep(p)
            if outcome == "written":
                written += 1
            elif outcome == "no-head":
                failed += 1
                print(f"NO HEAD: {p}")
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            print(f"ERROR {p}: {e}")
    print(f"sweep done: written={written} skipped={skipped} failed={failed} total={len(pages)}")

    print("running node --check on inline scripts...")
    bad = 0
    for p in pages:
        fails = script_syntax_check(p)
        if fails:
            bad += 1
            rel = os.path.relpath(p, ROOT)
            print(f"FAIL {rel}: {fails[-1]}")
    print(f"syntax-check done: {bad} pages with failures / {len(pages)} total")
    sys.exit(0 if failed == 0 and bad == 0 else 1)


if __name__ == "__main__":
    main()
