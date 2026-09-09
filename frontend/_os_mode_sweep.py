#!/usr/bin/env python3
"""Sweep: inject open-source-mode awareness into every page.

When the `monetization` flag is OFF (open-source mode), this snippet:
  - Hides the Pricing nav link (desktop + mobile)
  - Hides the credit chip (Sonnet-5 credits)
  - Hides "Buy credits" / credit-related CTAs in the nav dropdown

Idempotent: uses <!-- CR_OS_MODE_START --> / <!-- CR_OS_MODE_END --> markers.
Re-running replaces the block in place. index.html is SKIPPED because it has
its own, more detailed open-source handler already.

Run:  cd frontend && python3 _os_mode_sweep.py
"""
import glob, re, os

MARKER_START = '<!-- CR_OS_MODE_START -->'
MARKER_END   = '<!-- CR_OS_MODE_END -->'

# The snippet fetches /api/features/ once and hides monetization-related UI.
# Root pages use pricing.html, subdir pages use ../pricing.html — both matched.
SNIPPET = '''<!-- CR_OS_MODE_START -->
<script>
(function () {
    fetch(window.CR_API_BASE + '/api/features/')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
            if (!d || !d.features || d.features.monetization !== false) return;
            // Hide Pricing nav link (desktop + mobile)
            document.querySelectorAll('a[href="pricing.html"], a[href="../pricing.html"]').forEach(function (a) {
                if (a.textContent.trim() === 'Pricing') a.style.display = 'none';
            });
            // Hide Billing nav dropdown item (nothing to bill while monetization is off)
            document.querySelectorAll('a[href="billing.html"], a[href="../billing.html"]').forEach(function (a) {
                if (a.textContent.trim() === 'Billing') a.style.display = 'none';
            });
            // Hide credit chip
            var cc = document.getElementById('crCreditWrap');
            if (cc) cc.style.display = 'none';
            var creditCta = document.querySelector('.cr-credit-cta');
            if (creditCta) creditCta.style.display = 'none';
            // Hide "Sonnet-5 credits" label in dropdown
            document.querySelectorAll('.cr-dd-email').forEach(function (el) {
                if (el.textContent.trim() === 'Sonnet-5 credits') el.style.display = 'none';
            });
            // Dashboard: hide PREMIUM pill + credits pill
            var pill = document.getElementById('wbPlanPill');
            if (pill) pill.style.display = 'none';
            var cpill = document.getElementById('creditsPill');
            if (cpill) cpill.style.display = 'none';
        })
        .catch(function () {});
})();
</script>
<!-- CR_OS_MODE_END -->'''

SKIP = {'index.html'}  # has its own handler

def process(path):
    html = open(path, encoding='utf-8').read()

    # Remove old block if present
    html = re.sub(
        r'\s*' + re.escape(MARKER_START) + r'.*?' + re.escape(MARKER_END),
        '', html, flags=re.DOTALL
    )

    # Insert just before </body>
    if '</body>' not in html:
        return False
    html = html.replace('</body>', SNIPPET + '\n</body>', 1)

    open(path, 'w', encoding='utf-8').write(html)
    return True

count = 0
for path in sorted(glob.glob('**/*.html', recursive=True)):
    base = os.path.basename(path)
    if base.startswith('_') or base in SKIP:
        continue
    if process(path):
        count += 1

print(f'Done: injected open-source-mode snippet into {count} pages (skipped {SKIP})')
