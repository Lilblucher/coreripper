from django.urls import path

from . import admin_views, views

urlpatterns = [
    path("api/accounts/signup/", views.signup_view, name="accounts-signup"),
    path("api/accounts/login/", views.login_view, name="accounts-login"),
    path("api/accounts/refresh/", views.refresh_view, name="accounts-refresh"),
    path("api/accounts/logout/", views.logout_view, name="accounts-logout"),
    path("api/accounts/verify-email/", views.verify_email_view, name="accounts-verify-email"),
    path("api/accounts/resend-verification/", views.resend_verification_view, name="accounts-resend-verification"),
    path("api/accounts/me/", views.me_view, name="accounts-me"),
    path("api/accounts/forgot-password/", views.forgot_password_view, name="accounts-forgot-password"),
    path("api/accounts/reset-password/", views.reset_password_view, name="accounts-reset-password"),
    path("api/accounts/profile/", views.profile_view, name="accounts-profile"),
    path("api/accounts/notifications/", views.notifications_view, name="accounts-notifications"),
    path("api/accounts/change-password/", views.change_password_view, name="accounts-change-password"),
    path("api/accounts/billing/", views.billing_view, name="accounts-billing"),
    path("api/accounts/invoices/<int:payment_id>/pdf/", views.invoice_pdf_view, name="accounts-invoice-pdf"),
    path("api/accounts/support/tickets/", views.support_ticket_view, name="accounts-support-tickets"),
    path("api/accounts/sessions/", views.sessions_view, name="accounts-sessions"),
    path("api/accounts/sessions/<int:session_id>/", views.revoke_session_view, name="accounts-revoke-session"),
    path("api/accounts/delete-account/", views.delete_account_view, name="accounts-delete-account"),
    path("api/accounts/google-login/", views.google_login_view, name="accounts-google-login"),
    path("api/accounts/admin/users/", admin_views.admin_users_view, name="accounts-admin-users"),
    path("api/accounts/admin/users/<int:user_id>/", admin_views.admin_user_detail_view, name="accounts-admin-user-detail"),
    path("api/accounts/admin/transactions/", admin_views.admin_transactions_view, name="accounts-admin-transactions"),
]
