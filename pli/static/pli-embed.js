/* PLI widget, child side: report our height to the embedding page so the
   iframe can fit. Height only — nothing else ever crosses the frame. */
(function () {
  "use strict";
  if (window.parent === window) { return; }
  function send() {
    window.parent.postMessage(
      { pli: "resize", height: document.documentElement.scrollHeight },
      "*"
    );
  }
  window.addEventListener("load", send);
  window.addEventListener("resize", send);
  send();
})();
