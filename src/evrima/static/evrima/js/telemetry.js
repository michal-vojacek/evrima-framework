// Evrima telemetry, browser part: page views with load times, and clicks on
// phone, e-mail, external and marked (data-track) links, sent to the website
// itself with navigator.sendBeacon. Protocol: docs/protocol.md in
// evrima-telemetry.
//
// Level 1 (default): no cookies, nothing stored in the browser, nothing about
// the visitor. Level 2 (data-visitors="<consent category>"): only after the
// visitor allowed that category, a random visitor id is kept in the
// evrima_vid cookie; the server reads it with every beacon and checks the
// consent again itself.
(function () {
  "use strict";

  var script = document.currentScript;
  var endpoint = script && script.getAttribute("data-endpoint");
  if (!endpoint || !navigator.sendBeacon) { return; }
  var LABEL = /^[A-Za-z0-9_-]{1,40}$/;
  var visitors = script.getAttribute("data-visitors") || "";
  var consentVersion = script.getAttribute("data-consent-version") || "";
  var visitorDays = parseInt(script.getAttribute("data-visitor-days") || "0", 10);
  var VISITOR = "evrima_vid";

  function cookie(name) {
    var match = document.cookie.match(new RegExp("(?:^|;\\s*)" + name + "=([^;]*)"));
    return match ? match[1] : null;
  }

  // The same reading of the consent cookie as consent.js: v<version>.<category>.…
  function allowed(category) {
    var value = cookie("evrima_consent");
    if (!value) { return false; }
    var parts = value.split(".");
    return parts[0] === "v" + consentVersion && parts.indexOf(category, 1) > 0;
  }

  function secure() { return location.protocol === "https:" ? "; Secure" : ""; }

  // Created once and not extended: it expires 13 months after the first visit.
  function ensureVisitor() {
    if (!visitors || !window.crypto || !crypto.getRandomValues) { return; }
    if (!allowed(visitors)) {
      if (cookie(VISITOR) !== null) { document.cookie = VISITOR + "=; Max-Age=0; Path=/; SameSite=Lax" + secure(); }
      return;
    }
    if (cookie(VISITOR) !== null) { return; }
    var bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    var id = btoa(String.fromCharCode.apply(null, bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    document.cookie = VISITOR + "=" + id + "; Max-Age=" + (visitorDays * 86400) + "; Path=/; SameSite=Lax" + secure();
  }

  ensureVisitor();
  document.addEventListener("evrima:consent", ensureVisitor);

  function send(event) {
    try {
      navigator.sendBeacon(endpoint, new Blob([JSON.stringify(event)], { type: "application/json" }));
    } catch (e) { /* a lost event is invisible; an error here must not break the page */ }
  }

  function device() {
    var width = window.innerWidth;
    return width < 600 ? "mobile" : width < 1024 ? "tablet" : "desktop";
  }

  // A visit starts with a page view whose referrer is not this website.
  function referrer() {
    try {
      if (!document.referrer) { return { entry: true, ref: "" }; }
      var from = new URL(document.referrer);
      if (from.host === location.host) { return { entry: false, ref: "" }; }
      return { entry: true, ref: from.hostname };
    } catch (e) {
      return { entry: true, ref: "" };
    }
  }

  function pageview() {
    var from = referrer();
    var event = { t: "pageview", path: location.pathname, entry: from.entry, ref: from.ref, device: device() };
    var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
    if (nav) {
      event.ttfb = Math.round(nav.responseStart);
      event.dom = Math.round(nav.domContentLoadedEventEnd);
      event.load = Math.round(nav.loadEventEnd);
    }
    send(event);
  }

  // loadEventEnd is known only after the load handlers have finished.
  if (document.readyState === "complete") {
    setTimeout(pageview, 0);
  } else {
    window.addEventListener("load", function () { setTimeout(pageview, 0); });
  }

  document.addEventListener("click", function (e) {
    var element = e.target.closest && e.target.closest("a[href], [data-track]");
    if (!element) { return; }
    var label = element.getAttribute("data-track") || "";
    if (!LABEL.test(label)) { label = ""; }
    var href = element.tagName === "A" ? element.getAttribute("href") || "" : "";
    var event = { t: "click", kind: "track", label: label };
    var target = null;
    if (href) {
      // Resolved against the page, so "//host/…" and relative links are told apart correctly.
      try { target = new URL(href, location.href); } catch (err) { target = null; }
    }
    var scheme = target ? target.protocol : "";
    if (scheme === "tel:") {
      event.kind = "tel";
    } else if (scheme === "mailto:") {
      event.kind = "mailto";
    } else if ((scheme === "http:" || scheme === "https:") && target.host !== location.host) {
      event.kind = "external";
      event.host = target.hostname;
    } else if (!label) {
      return;                      // internal links without a label are not counted
    }
    send(event);
  }, true);
})();
