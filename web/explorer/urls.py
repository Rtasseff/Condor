from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("p/<uuid:pid>", views.shared_portfolio, name="shared_portfolio"),
    path("api/analyze", views.api_analyze, name="api_analyze"),
    path("api/portfolios", views.api_portfolios, name="api_portfolios"),
    path("api/portfolios/<uuid:pid>", views.api_portfolio, name="api_portfolio"),
]
