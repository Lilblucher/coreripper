from django.urls import path

from . import admin_views, views

urlpatterns = [
    # Public
    path("api/payments/pricing/", views.pricing_view, name="payments-pricing"),
    path("api/payments/config/", views.payments_config_view, name="payments-config"),
    # Logged-in charge flow
    path("api/payments/create-charge/", views.create_charge_view, name="payments-create-charge"),
    path("api/payments/verify/<str:ref>/", views.verify_charge_view, name="payments-verify"),
    path("api/payments/submit-otp/", views.submit_otp_view, name="payments-submit-otp"),
    # Inbound gateway webhook (secret-in-path, disabled until LENCO_WEBHOOK_SECRET is set)
    path("api/payments/webhook/lenco/<str:secret>/", views.lenco_webhook_view, name="payments-lenco-webhook"),
    # Superuser price management (Engine Room Pricing tab)
    path("api/payments/admin/prices/", admin_views.admin_prices_view, name="payments-admin-prices"),
    path("api/payments/admin/prices/<int:price_id>/", admin_views.admin_price_detail_view, name="payments-admin-price-detail"),
]
