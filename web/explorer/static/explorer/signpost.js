/* Optimize's "Nothing to optimize yet" page, for a signed-in visitor.
 *
 * The server decided there was nothing to show before it could know what
 * this browser is carrying: someone who explored anonymously and has just
 * signed in still has their mix in localStorage. CondorDraft.ready()
 * imports it into their account; if it did, the page the server rendered
 * is out of date and the workbench is what they should be looking at.
 *
 * Safe to re-run: the import clears the browser copy on success, so the
 * reload lands on a page that has nothing left to import. */
"use strict";

CondorDraft.ready().then((imported) => {
  if (imported) window.location.reload();
});
