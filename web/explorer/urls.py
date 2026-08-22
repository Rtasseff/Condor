from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("login", auth_views.LoginView.as_view(
        template_name="explorer/login.html",
        redirect_authenticated_user=True), name="login"),
    path("logout", auth_views.LogoutView.as_view(next_page="login"),
         name="logout"),
    path("p/<uuid:pid>", views.shared_portfolio, name="shared_portfolio"),
    path("api/analyze", views.api_analyze, name="api_analyze"),
    path("api/portfolios", views.api_portfolios, name="api_portfolios"),
    path("api/portfolios/<uuid:pid>", views.api_portfolio, name="api_portfolio"),
]
