from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),  # team/user management
    path("", include("explorer.urls")),
]
