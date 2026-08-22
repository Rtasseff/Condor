from django.contrib.auth import views as auth_views
from django.urls import path

from . import account, views

urlpatterns = [
    path("", views.index, name="index"),
    path("login", auth_views.LoginView.as_view(
        template_name="explorer/login.html",
        redirect_authenticated_user=True), name="login"),
    path("logout", auth_views.LogoutView.as_view(next_page="login"),
         name="logout"),
    path("p/<uuid:pid>", views.shared_portfolio, name="shared_portfolio"),
    path("api/analyze", views.api_analyze, name="api_analyze"),
    path("api/forecast", views.api_forecast, name="api_forecast"),
    path("account", account.account_page, name="account"),
    path("api/account", account.api_account, name="api_account"),
    path("api/account/events", account.api_account_events,
         name="api_account_events"),
    path("api/account/events/<int:eid>", account.api_account_event,
         name="api_account_event"),
    path("api/account/target", account.api_account_target,
         name="api_account_target"),
    path("api/account/plan", account.api_account_plan,
         name="api_account_plan"),
    path("api/account/plan/confirm", account.api_account_plan_confirm,
         name="api_account_plan_confirm"),
    path("api/portfolios", views.api_portfolios, name="api_portfolios"),
    path("api/portfolios/<uuid:pid>", views.api_portfolio, name="api_portfolio"),
]
