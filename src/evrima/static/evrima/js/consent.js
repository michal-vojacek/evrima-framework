// Evrima consent banner: saves the visitor's choice without reloading the page,
// opens the banner again from links marked data-evrima-consent-open, and tells
// the website's own scripts about the choice. The banner works without this
// script too: it is an ordinary form, and the links lead to the settings page.
//
// For the website's scripts:
//   evrimaConsent.has("analytics")   whether a category is allowed now
//   evrimaConsent.categories()       the allowed categories, or null before a choice
//   evrimaConsent.open()             show the banner with its settings
//   document "evrima:consent" event  after every change, event.detail.categories
(function () {
  "use strict";

  var script = document.currentScript;
  var version = script && script.getAttribute("data-version");

  function read() {
    var match = document.cookie.match(/(?:^|;\s*)evrima_consent=([^;]*)/);
    if (!match) { return null; }
    var parts = match[1].split(".");
    return parts[0] === "v" + version ? parts.slice(1) : null;
  }

  function banner() { return document.querySelector("[data-evrima-consent]"); }

  function open() {
    var element = banner();
    if (!element) { return false; }
    element.hidden = false;
    var details = element.querySelector("details");
    if (details) { details.open = true; }
    var heading = element.querySelector("[data-evrima-consent-title]");
    if (heading) { heading.focus(); }
    return true;
  }

  window.evrimaConsent = {
    has: function (category) { var allowed = read(); return !!allowed && allowed.indexOf(category) >= 0; },
    categories: read,
    open: open
  };

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("[data-evrima-consent-open]");
    if (link && open()) { event.preventDefault(); }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("[data-evrima-consent-form]") || !window.fetch) { return; }
    event.preventDefault();
    var submitter = event.submitter;
    var choice = submitter && submitter.name === "choice" ? submitter.value : "selected";
    var data = new FormData(form);
    data.set("choice", choice);

    fetch(form.action, {
      method: "POST", body: data, credentials: "same-origin", headers: { Accept: "application/json" }
    }).then(function (response) {
      if (!response.ok) { throw new Error(String(response.status)); }
      return response.json();
    }).then(function (result) {
      var allowed = result.categories || [];
      Array.prototype.forEach.call(form.querySelectorAll("input[name=category]"), function (box) {
        box.checked = allowed.indexOf(box.value) >= 0;
      });
      var element = banner();
      if (element && element.contains(form)) { element.hidden = true; }
      var saved = form.querySelector("[data-evrima-consent-saved]");
      if (saved) { saved.hidden = false; }
      document.dispatchEvent(new CustomEvent("evrima:consent", { detail: { categories: allowed } }));
    }).catch(function () {
      // Let the browser send the form itself; the server redirects back.
      var field = document.createElement("input");
      field.type = "hidden";
      field.name = "choice";
      field.value = choice;
      form.appendChild(field);
      form.submit();
    });
  });
})();
