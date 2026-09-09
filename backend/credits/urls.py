from django.urls import path

from . import views

urlpatterns = [
    path("api/credits/wallet/", views.wallet_view, name="credits-wallet"),
    path("api/credits/history/", views.usage_history_view, name="credits-history"),
]
