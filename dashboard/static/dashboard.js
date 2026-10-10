/**
 * Phase 7 -- Admin Dashboard client-side logic.
 *
 * Polls GET /api/status every 3 seconds and updates the DOM in place.
 * NEVER does a full-page reload.  Uses element.textContent exclusively
 * for any data that could contain log text (XSS prevention).
 *
 * On fetch failure the "Live" pill shows "Connection lost -- retrying..."
 * instead of breaking.  First paint uses server-rendered Jinja data.
 */

(function () {
  "use strict";

  // ── Constants ──────────────────────────────────────────────────────────
  var POLL_MS = 3000;
  var lastFetchEpoch = Date.now();
  var agoTimer = null;

  // ── Selectors (cached once on load) ────────────────────────────────────
  var $  = function (sel) { return document.querySelector(sel); };
  var $$ = function (sel) { return document.querySelectorAll(sel); };

  // ── "Updated N s ago" ticker ───────────────────────────────────────────
  function startAgoTicker() {
    if (agoTimer) return;
    agoTimer = setInterval(function () {
      var el = $("#live-ago");
      if (!el) return;
      var secs = Math.round((Date.now() - lastFetchEpoch) / 1000);
      el.textContent = "updated " + secs + "s ago";
    }, 1000);
  }

  // ── Severity / status helpers ──────────────────────────────────────────
  function badgeClass(severity) {
    if (!severity) return "badge badge-muted";
    var s = severity.toUpperCase();
    if (s === "HIGH" || s === "CRITICAL") return "badge badge-bad";
    if (s === "MEDIUM" || s === "WARNING") return "badge badge-warn";
    if (s === "LOW") return "badge badge-ok";
    return "badge badge-muted";
  }

  function statusLabel(status) {
    if (status === "ANOMALY") return "ANOMALY DETECTED";
    return status;
  }

  function lvlClass(level) {
    var l = (level || "").toLowerCase();
    if (l === "error")    return "lvl lvl-error";
    if (l === "critical") return "lvl lvl-critical";
    if (l === "warning")  return "lvl lvl-warning";
    if (l === "info")     return "lvl lvl-info";
    return "lvl lvl-debug";
  }

  // ── Metric card level (compares value to thresholds) ───────────────────
  function metricLevel(key, value, thresholds) {
    var t = thresholds[key];
    if (!t) return "";
    if (value >= t.anomaly_min) return "bad";
    if (value > t.normal_max)   return "warn";
    return "";
  }

  // ── Animate a number change with a short transition ────────────────────
  function setNumber(el, newVal) {
    if (!el) return;
    var txt = (newVal === null || newVal === undefined) ? "0" : String(newVal);
    if (el.textContent !== txt) {
      el.textContent = txt;
      el.style.transition = "none";
      el.style.opacity = "0.4";
      // Force reflow then animate
      void el.offsetWidth;
      el.style.transition = "opacity 300ms ease";
      el.style.opacity = "1";
    }
  }

  // ── Render the SVG trend chart ─────────────────────────────────────────
  function renderTrend(trend) {
    var wrap = $("#trend-chart");
    if (!wrap) return;

    if (!trend || trend.length < 2) {
      wrap.innerHTML = '<div class="trend-empty">Collecting data -- chart will appear shortly.</div>';
      return;
    }

    var W = 560, H = 140, PAD_T = 10, PAD_B = 22, PAD_L = 0, PAD_R = 0;
    var plotH = H - PAD_T - PAD_B;
    var plotW = W - PAD_L - PAD_R;
    var maxVal = Math.max.apply(null, trend.map(function (d) { return d.errors; }));
    if (maxVal === 0) maxVal = 1;

    var points = trend.map(function (d, i) {
      var x = PAD_L + (i / (trend.length - 1)) * plotW;
      var y = PAD_T + plotH - (d.errors / maxVal) * plotH;
      return { x: x, y: y, label: d.time, val: d.errors };
    });

    var line = points.map(function (p, i) {
      return (i === 0 ? "M" : "L") + p.x.toFixed(1) + "," + p.y.toFixed(1);
    }).join(" ");

    // Area fill: line + close along bottom
    var area = line
      + " L" + points[points.length - 1].x.toFixed(1) + "," + (PAD_T + plotH)
      + " L" + points[0].x.toFixed(1) + "," + (PAD_T + plotH) + " Z";

    // Grid lines (3 lines at 25%, 50%, 75%)
    var gridLines = "";
    for (var g = 1; g <= 3; g++) {
      var gy = PAD_T + plotH - (g / 4) * plotH;
      gridLines +=
        '<line x1="' + PAD_L + '" y1="' + gy.toFixed(1) +
        '" x2="' + (PAD_L + plotW) + '" y2="' + gy.toFixed(1) +
        '" stroke="var(--border)" stroke-width="0.7" stroke-dasharray="4 3"/>';
    }

    // Last-value dot
    var last = points[points.length - 1];
    var dotSvg =
      '<circle cx="' + last.x.toFixed(1) + '" cy="' + last.y.toFixed(1) +
      '" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>';

    // X-axis labels (first, middle, last)
    var labels = "";
    var indices = [0, Math.floor(points.length / 2), points.length - 1];
    indices.forEach(function (idx) {
      var p = points[idx];
      labels +=
        '<text x="' + p.x.toFixed(1) + '" y="' + (H - 4) +
        '" text-anchor="middle" fill="var(--muted)" font-size="10" font-family="var(--font-mono)">' +
        escapeHtml(p.label) + '</text>';
    });

    var svg =
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" aria-label="Error trend chart">' +
      '<defs><linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="var(--accent)" stop-opacity="0.25"/>' +
      '<stop offset="100%" stop-color="var(--accent)" stop-opacity="0.02"/>' +
      '</linearGradient></defs>' +
      gridLines +
      '<path d="' + area + '" fill="url(#areaGrad)"/>' +
      '<path d="' + line + '" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' +
      dotSvg + labels +
      '</svg>';

    wrap.innerHTML = svg;
  }

  // ── Simple HTML-escape (for axis labels only; log text uses textContent) ─
  function escapeHtml(str) {
    var d = document.createElement("span");
    d.textContent = str;
    return d.innerHTML;
  }

  // ── Main update function ───────────────────────────────────────────────
  function applyData(data) {
    var status   = data.status || "NORMAL";
    var severity = data.severity || "NONE";
    var reason   = data.reason || "";
    var metrics  = data.metrics || {};
    var thresholds = data.thresholds || {};

    // -- Database status pill
    var dbPill = $("#db-pill");
    var dbText = $("#db-text");
    if (dbPill && dbText) {
      if (data.db_status === "SIMULATED_FAILURE") {
        dbPill.className = "pill db-pill sim-failure pulse";
        var secs = (data.db_failure_seconds_remaining !== undefined) ? data.db_failure_seconds_remaining : 0;
        dbText.textContent = "Database: simulated failure (" + secs + "s left)";
      } else {
        dbPill.className = "pill db-pill";
        dbText.textContent = "Database online";
      }
    }

    // -- Hero card
    var hero = $("#hero");
    if (hero) hero.setAttribute("data-status", status);

    var heroDot = $("#hero-dot");
    if (heroDot) {
      heroDot.className = "hero-dot" + (status !== "NORMAL" ? " pulse" : "");
    }

    var heroStatus = $("#hero-status");
    if (heroStatus) heroStatus.textContent = statusLabel(status);

    var heroReason = $("#hero-reason");
    if (heroReason) heroReason.textContent = reason;

    var sevBadge = $("#sev-badge");
    if (sevBadge) {
      sevBadge.textContent = severity;
      sevBadge.className = badgeClass(severity);
    }

    // -- Admin alert panel
    var alertPanel = $("#admin-alert");
    if (alertPanel) {
      if (status === "ANOMALY" && data.anomalies && data.anomalies.length > 0) {
        alertPanel.classList.add("visible");
        var latest = data.anomalies[0];
        var alertType = $("#alert-type");
        if (alertType) alertType.textContent = latest.type || "Anomaly";
        var alertDetail = $("#alert-detail");
        if (alertDetail) alertDetail.textContent = latest.reason || "";
      } else {
        alertPanel.classList.remove("visible");
      }
    }

    // -- Metric cards
    var cardDefs = [
      { id: "m-requests",     key: "total_requests",            tKey: null },
      { id: "m-errors",       key: "error_count",               tKey: "error_count" },
      { id: "m-warnings",     key: "warning_count",             tKey: "warning_count" },
      { id: "m-db",           key: "database_error_count",      tKey: "database_error_count" },
      { id: "m-broadcast",    key: "broadcast_failure_count",   tKey: "broadcast_failure_count" },
      { id: "m-notif",        key: "notification_delay_count",  tKey: "notification_delay_count" },
      { id: "m-rt",           key: "average_response_time_ms",  tKey: null },
      { id: "m-anomalies",    key: null,                        tKey: null },
    ];

    cardDefs.forEach(function (cd) {
      var card = $("#" + cd.id);
      if (!card) return;
      var valEl = card.querySelector(".metric-value");
      var val;
      if (cd.id === "m-anomalies") {
        val = data.anomaly_count || 0;
      } else if (cd.id === "m-rt") {
        var raw = metrics[cd.key];
        val = (raw !== null && raw !== undefined) ? (Math.round(raw * 10) / 10) + " ms" : "0 ms";
      } else {
        val = metrics[cd.key] || 0;
      }
      setNumber(valEl, val);

      // Colour the card border
      if (cd.tKey) {
        var numVal = parseInt(metrics[cd.key], 10) || 0;
        card.setAttribute("data-level", metricLevel(cd.tKey, numVal, thresholds));
      } else if (cd.id === "m-anomalies") {
        card.setAttribute("data-level", (data.anomaly_count || 0) > 0 ? "bad" : "");
      }
    });

    // -- Trend chart
    renderTrend(data.trend);

    // -- Recent logs table
    var logBody = $("#log-body");
    if (logBody) {
      var logs = data.recent_logs || [];
      if (logs.length === 0) {
        logBody.innerHTML = '<tr><td colspan="3" class="empty-state">No log entries yet.</td></tr>';
      } else {
        var rows = "";
        logs.forEach(function (log) {
          rows += "<tr>";
          rows += '<td class="tabular">' + escapeHtml(log.timestamp) + "</td>";
          rows += '<td><span class="' + lvlClass(log.level) + '">' + escapeHtml(log.level) + "</span></td>";
          rows += '<td class="msg"></td>';
          rows += "</tr>";
        });
        logBody.innerHTML = rows;
        // Set message text via textContent (XSS safe)
        var msgCells = logBody.querySelectorAll(".msg");
        logs.forEach(function (log, i) {
          if (msgCells[i]) msgCells[i].textContent = log.message;
        });
      }
    }

    // -- Recent anomalies table
    var anomBody = $("#anomaly-body");
    if (anomBody) {
      var anoms = data.anomalies || [];
      if (anoms.length === 0) {
        anomBody.innerHTML =
          '<tr><td colspan="4" class="empty-state">No anomalies detected -- system operating normally.</td></tr>';
      } else {
        var aRows = "";
        anoms.forEach(function (a) {
          aRows += "<tr>";
          aRows += '<td class="tabular">' + escapeHtml(a.timestamp) + "</td>";
          aRows += "<td></td>"; // type -- set via textContent below
          aRows += "<td></td>"; // reason -- set via textContent below
          aRows += '<td><span class="' + badgeClass(a.severity) + '">' + escapeHtml(a.severity) + "</span></td>";
          aRows += "</tr>";
        });
        anomBody.innerHTML = aRows;
        var aRowEls = anomBody.querySelectorAll("tr");
        anoms.forEach(function (a, i) {
          if (aRowEls[i]) {
            var tds = aRowEls[i].querySelectorAll("td");
            if (tds[1]) tds[1].textContent = a.type;
            if (tds[2]) tds[2].textContent = a.reason;
          }
        });
      }
    }

    // -- Stored alerts count & table
    var countEl = $("#stored-alert-count");
    if (countEl) {
      setNumber(countEl, data.stored_alert_count || 0);
    }

    var alertBody = $("#alert-body");
    if (alertBody) {
      var alerts = data.recent_alerts || [];
      if (alerts.length === 0) {
        alertBody.innerHTML = '<tr><td colspan="5" class="empty-state">No alerts stored yet.</td></tr>';
      } else {
        var alRows = "";
        alerts.forEach(function (al) {
          alRows += "<tr>";
          alRows += '<td class="tabular"></td>';
          alRows += '<td class="tabular font-mono"></td>';
          alRows += '<td><span class="badge badge-info"></span></td>';
          alRows += '<td></td>';
          alRows += '<td><span class="badge badge-ok"></span></td>';
          alRows += "</tr>";
        });
        alertBody.innerHTML = alRows;

        var alRowEls = alertBody.querySelectorAll("tr");
        alerts.forEach(function (al, i) {
          if (alRowEls[i]) {
            var tds = alRowEls[i].querySelectorAll("td");
            if (tds[0]) tds[0].textContent = al.created_at || "";
            if (tds[1]) tds[1].textContent = al.id || "";
            if (tds[2] && tds[2].firstElementChild) tds[2].firstElementChild.textContent = al.type || "";
            if (tds[3]) tds[3].textContent = al.location || "";
            if (tds[4] && tds[4].firstElementChild) tds[4].firstElementChild.textContent = al.status || "processed";
          }
        });
      }
    }
  }

  // ── Fetch loop ─────────────────────────────────────────────────────────
  function poll() {
    fetch("/api/status")
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        lastFetchEpoch = Date.now();
        // Reset live pill to OK state
        var pill = $("#live-pill");
        if (pill) pill.classList.remove("error");
        var pillText = $("#live-text");
        if (pillText) pillText.textContent = "Live";
        applyData(data);
      })
      .catch(function () {
        // Show connection-lost state on the live pill
        var pill = $("#live-pill");
        if (pill) pill.classList.add("error");
        var pillText = $("#live-text");
        if (pillText) pillText.textContent = "Connection lost -- retrying...";
      })
      .finally(function () {
        setTimeout(poll, POLL_MS);
      });
  }

  // ── Boot ───────────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", function () {
    startAgoTicker();
    // The first paint is server-rendered; start polling after a short delay
    setTimeout(poll, POLL_MS);
  });
})();
