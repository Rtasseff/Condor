/* Learn: click-to-load video facades.

   The page ships a thumbnail and a button; the YouTube player only exists
   after someone asks for it. That keeps the public page light and means a
   visitor who just reads the glossary is never handed to a third party.
   The swap is one-way — once you press play the player stays until the
   page is reloaded — and focus follows it so keyboard users land on the
   thing they just started. */
(function () {
  "use strict";

  var EMBED = "https://www.youtube-nocookie.com/embed/";
  var ALLOW = "accelerometer; autoplay; clipboard-write; encrypted-media; " +
              "gyroscope; picture-in-picture; web-share";

  function play(facade, button) {
    var id = facade.getAttribute("data-video");
    if (!id) return;
    var frame = document.createElement("iframe");
    frame.src = EMBED + encodeURIComponent(id) + "?autoplay=1";
    frame.title = facade.getAttribute("data-title") || "Video";
    frame.allow = ALLOW;
    frame.allowFullscreen = true;
    // The site answers with Referrer-Policy: same-origin (Django's default),
    // which sends the player no referrer at all — YouTube then refuses to
    // start with "Video player configuration error, Error 153". Relaxing it
    // on this one element hands over the origin and nothing more.
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    frame.setAttribute("frameborder", "0");
    facade.classList.add("playing");
    button.replaceWith(frame);
    frame.focus();
  }

  document.querySelectorAll(".facade").forEach(function (facade) {
    var button = facade.querySelector(".facadebtn");
    if (!button) return;
    button.addEventListener("click", function () { play(facade, button); });
  });
})();
