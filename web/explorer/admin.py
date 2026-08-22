"""Admin: user management for the small team, plus a read view of saves."""

from django.contrib import admin

from .models import (Account, AccountEvent, AccountTarget,
                     ContributionSchedule, Holding, SavedPortfolio)


class HoldingInline(admin.TabularInline):
    model = Holding
    extra = 0


@admin.register(SavedPortfolio)
class SavedPortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "method", "years", "updated_at")
    list_filter = ("owner", "method")
    inlines = [HoldingInline]


class TargetInline(admin.TabularInline):
    model = AccountTarget
    extra = 0


class EventInline(admin.TabularInline):
    model = AccountEvent
    extra = 0


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    inlines = [TargetInline, EventInline]


@admin.register(ContributionSchedule)
class ContributionScheduleAdmin(admin.ModelAdmin):
    list_display = ("account", "amount", "cadence", "next_due", "enabled")
