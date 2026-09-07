"""Template context: the login reminder for due contributions, and the
signups-enabled flag.

`contribution_reminder` is cheap by design (two small queries, no price
fetches) — it runs on every authenticated page render so the "My account"
nav link can carry the due dot anywhere in the app.
"""

from django.conf import settings

from .models import ContributionSchedule


def contribution_reminder(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    sched = ContributionSchedule.objects.filter(
        account__owner=user, enabled=True).first()
    return {"contribution_due": bool(sched and sched.due)}


def signups_enabled(request):
    """Global so both the login page and the signup page can gate on it
    without every view remembering to pass it."""
    return {"SIGNUPS_ENABLED": settings.SIGNUPS_ENABLED}
