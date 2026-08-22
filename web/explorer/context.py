"""Template context: the login reminder for due contributions.

Cheap by design (two small queries, no price fetches) — it runs on
every authenticated page render so the "My account" nav link can carry
the due dot anywhere in the app.
"""

from .models import ContributionSchedule


def contribution_reminder(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    sched = ContributionSchedule.objects.filter(
        account__owner=user, enabled=True).first()
    return {"contribution_due": bool(sched and sched.due)}
