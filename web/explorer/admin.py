"""Admin: user management for the small team, plus a read view of saves."""

from django.contrib import admin

from .models import Holding, SavedPortfolio


class HoldingInline(admin.TabularInline):
    model = Holding
    extra = 0


@admin.register(SavedPortfolio)
class SavedPortfolioAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "method", "years", "updated_at")
    list_filter = ("owner", "method")
    inlines = [HoldingInline]
