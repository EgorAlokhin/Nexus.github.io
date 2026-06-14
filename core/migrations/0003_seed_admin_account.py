"""Move the original single-user deployment into a real per-user Account.

Creates (or reuses) a Django User for ADMIN_EMAIL, builds their encrypted
Account from the legacy UserSession + per-user Settings, and assigns every
existing Task/Grade/Notification/ChatMessage to that user. Idempotent.
"""

import json
import os

from django.conf import settings
from django.db import migrations

SECRET_KEYS = {"VERACROSS_PASSWORD", "BUZZ_PASSWORD"}
PLAIN_KEYS = {
    "VERACROSS_URL", "VERACROSS_USERNAME", "BUZZ_DOMAIN", "BUZZ_USERNAME",
    "USER_DISPLAY_NAME", "YOUR_PHONE_NUMBER", "NOTIFICATION_PREFS", "NOTIFICATION_CHANNEL",
}


def _digits(value):
    return "".join(c for c in str(value or "") if c.isdigit())


def seed(apps, schema_editor):
    from core.services.crypto import encrypt

    User = apps.get_model("auth", "User")
    Account = apps.get_model("core", "Account")
    UserSession = apps.get_model("core", "UserSession")
    Setting = apps.get_model("core", "Setting")
    Task = apps.get_model("core", "Task")
    Grade = apps.get_model("core", "Grade")
    Notification = apps.get_model("core", "Notification")
    ChatMessage = apps.get_model("core", "ChatMessage")

    email = (getattr(settings, "ADMIN_EMAIL", "") or "").strip().lower()
    legacy = UserSession.objects.first()
    if not email and legacy and legacy.google_email:
        email = legacy.google_email.strip().lower()
    if not email:
        email = "admin@nexus.local"

    username = email[:150]
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"email": email, "is_staff": True, "is_superuser": True},
    )

    def settings_value(key):
        row = Setting.objects.filter(key=key).first()
        if row and row.value:
            return row.value
        return (os.getenv(key) or "").strip()

    plain = {}
    for key in PLAIN_KEYS:
        v = settings_value(key)
        if v:
            plain[key] = v

    secrets = {}
    for key in SECRET_KEYS:
        v = settings_value(key)
        if v:
            secrets[key] = v

    google_email = ""
    if legacy:
        google_email = (legacy.google_email or "").strip().lower()
        if legacy.google_refresh_token:
            secrets["google_refresh_token"] = legacy.google_refresh_token
        if legacy.buzz_token:
            secrets["buzz_token"] = legacy.buzz_token
        if legacy.veracross_cookies:
            secrets["veracross_cookies"] = legacy.veracross_cookies
    if not google_email:
        google_email = email

    account, created = Account.objects.get_or_create(
        user=user,
        defaults={
            "google_email": google_email,
            "phone": _digits(plain.get("YOUR_PHONE_NUMBER")),
            "data_json": json.dumps(plain),
            "secrets_enc": encrypt(json.dumps(secrets)) if secrets else "",
        },
    )
    if not created:
        account.google_email = account.google_email or google_email
        account.save()

    # Claim all existing rows for the admin user.
    Task.objects.filter(user__isnull=True).update(user=user)
    Grade.objects.filter(user__isnull=True).update(user=user)
    Notification.objects.filter(user__isnull=True).update(user=user)
    ChatMessage.objects.filter(user__isnull=True).update(user=user)

    # Remove per-user secrets/values from the global Setting table so they
    # cannot leak to other users through the global config fallback.
    Setting.objects.filter(key__in=(SECRET_KEYS | PLAIN_KEYS)).delete()


def unseed(apps, schema_editor):
    # No-op: we don't want to destroy migrated user data on reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_account_remove_grade_uq_grade_source_extid_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
