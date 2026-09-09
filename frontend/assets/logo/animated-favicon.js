/**
 * CoreRipper animated favicon.
 *
 * Plays the same entrance timeline as the loading screen (hexagon draws,
 * breaks, the pulse strikes through with a glow, glow holds, then dims 
 * with an ambient violet halo blooming in behind the mark as it settles)
 * directly on the favicon, then STOPS and leaves the dim+glow frame as
 * the static resting favicon. It does not loop forever  animating a favicon
 * indefinitely in a background tab burns CPU/battery for no benefit; the
 * one-shot "load" moment is the whole point here.
 *
 * No dependencies. Usage:
 *   <script src="/animated-favicon.js"></script>
 *   <script>CoreRipperFavicon.init();</script>
 *
 * Or call it right when your real app/data finishes loading if you want
 * the favicon's "settle" to line up with actual readiness rather than a
 * fixed timer  see the `onComplete` option.
 */
(function () {
  function setFavicon(href) {
    var link = document.querySelector('link[rel="icon"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.type = 'image/png';
    link.href = href;
  }

  function pathLength(points) {
    var len = 0;
    for (var i = 1; i < points.length; i++) {
      len += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    }
    return len;
  }

  function strokePolyline(ctx, points, progress, opts) {
    if (progress <= 0) return;
    var len = pathLength(points);
    ctx.save();
    ctx.strokeStyle = opts.color;
    ctx.lineWidth = opts.width;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.globalAlpha = opts.alpha != null ? opts.alpha : 1;
    if (opts.glow) {
      ctx.shadowColor = opts.glow.color;
      ctx.shadowBlur = opts.glow.blur;
    }
    ctx.setLineDash([len, len]);
    ctx.lineDashOffset = len * (1 - Math.min(1, progress));
    ctx.beginPath();
    points.forEach(function (p, i) {
      if (i === 0) ctx.moveTo(p[0], p[1]);
      else ctx.lineTo(p[0], p[1]);
    });
    ctx.stroke();
    ctx.restore();
  }

  // Same coordinates as the SVG mark (viewBox 0 0 64 64).
  var HEX = [[32, 6], [52, 18], [52, 46], [32, 58], [12, 46], [12, 18], [32, 6]];
  var FRAME_L = [[32, 6], [12, 18], [12, 46], [24, 53]];
  var FRAME_R = [[32, 58], [52, 46], [52, 18], [40, 11]];
  var PULSE = [[4, 36], [24, 20], [34, 46], [60, 18]];

  var CORE_GRAD = ['#2597E8', '#2597E8'];
  var PULSE_GRAD = ['#15A6DE', '#2597E8'];

  function grad(ctx, size, colors) {
    var g = ctx.createLinearGradient(0, 0, size, size);
    g.addColorStop(0, colors[0]);
    g.addColorStop(1, colors[1]);
    return g;
  }

  // Timeline mirrors the loading screen's CSS timing (see handoff README).
  var T_HEX_DRAW = 0.55, T_BREAK = 0.68, T_PULSE_START = 0.72, T_PULSE_END = 1.42, T_DIM_END = 3.0;
  var TOTAL = T_DIM_END;

  function render(ctx, size, t) {
    ctx.clearRect(0, 0, size, size);

    // Ambient glow that blooms in behind the mark as it settles to dim
    // (mirrors the loading screen's background glow-on-dim).
    var glowP = Math.max(0, Math.min(1, (t - (T_PULSE_END + 0.3)) / (TOTAL - (T_PULSE_END + 0.3))));
    if (glowP > 0) {
      var cx = size / 2, cy = size / 2;
      var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.62);
      g.addColorStop(0, 'rgba(37,151,232,' + (0.55 * glowP) + ')');
      g.addColorStop(1, 'rgba(10,10,10,0)');
      ctx.save();
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, size, size);
      ctx.restore();
    }

    ctx.save();
    ctx.scale(size / 64, size / 64);

    var coreColor = grad(ctx, 64, CORE_GRAD);
    var pulseColor = grad(ctx, 64, PULSE_GRAD);

    if (t < T_BREAK) {
      strokePolyline(ctx, HEX, t / T_HEX_DRAW, { color: coreColor, width: 5, alpha: 0.5 });
    } else {
      var fadeP = Math.min(1, (t - T_BREAK) / 0.12);
      strokePolyline(ctx, FRAME_L, 1, { color: coreColor, width: 5, alpha: 0.45 * fadeP });
      strokePolyline(ctx, FRAME_R, 1, { color: coreColor, width: 5, alpha: 0.45 * fadeP });
    }

    if (t >= T_PULSE_START) {
      var p = (t - T_PULSE_START) / (T_PULSE_END - T_PULSE_START);
      var glowT = Math.max(0, Math.min(1, (t - T_PULSE_END) / (TOTAL - T_PULSE_END)));
      // ramps up then settles down, matching cr-load-glow
      var blur = t < T_PULSE_END ? 3 : 3 + 20 * Math.sin(glowT * Math.PI * 0.7) * (1 - glowT * 0.6);
      strokePolyline(ctx, PULSE, p, {
        color: pulseColor, width: 7,
        glow: { color: 'rgba(37,151,232,0.9)', blur: Math.max(2, blur) }
      });
    }

    ctx.restore();
  }

  function initAnimatedFavicon(opts) {
    opts = opts || {};
    var size = opts.size || 32;
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    var ctx = canvas.getContext('2d');

    if (reduce) {
      render(ctx, size, TOTAL);
      setFavicon(canvas.toDataURL('image/png'));
      if (opts.onComplete) opts.onComplete();
      return;
    }

    var start = performance.now();
    var lastUpdate = 0;
    var frameInterval = 1000 / 12; // ~12fps is plenty for a 16-32px icon

    function frame(now) {
      var t = (now - start) / 1000;
      if (now - lastUpdate >= frameInterval) {
        render(ctx, size, Math.min(t, TOTAL));
        setFavicon(canvas.toDataURL('image/png'));
        lastUpdate = now;
      }
      if (t < TOTAL) {
        requestAnimationFrame(frame);
      } else {
        render(ctx, size, TOTAL);
        setFavicon(canvas.toDataURL('image/png'));
        if (opts.onComplete) opts.onComplete();
      }
    }
    requestAnimationFrame(frame);
  }

  window.CoreRipperFavicon = { init: initAnimatedFavicon };
})();
