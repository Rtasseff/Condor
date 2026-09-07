"""The signup form: username/email/password plus the two anti-bot/legal
guards (honeypot, consent) and the inactive-user resend rule.

Kept separate from views.py because the resend rule needs form-level
`clean()` to see username and email together before deciding whether a
username collision is a resend or a real clash.
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

ALREADY_REGISTERED = "already registered — sign in or reset your password."


class SignupForm(UserCreationForm):
    email = forms.EmailField(
        required=True, max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    consent = forms.BooleanField(
        required=True,
        label="This is an educational prototype: pretend money, real "
              "market data, not investment advice.",
        error_messages={"required": "Check the box to continue."},
    )
    # Honeypot: invisible to a person (type=hidden), irresistible to a bot
    # that fills in every field it finds. Non-empty -> pretend success,
    # create nothing (handled in the view, before the form even runs).
    website = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"autocomplete": "off"}))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set only when this submission matches an existing *inactive*
        # user with the same email — a "the email never arrived" resend,
        # not a new account. The view checks this instead of calling save().
        self.retry_user = None

    def clean_username(self):
        # Skip UserCreationForm's own case-insensitive collision check —
        # a matching *inactive* user with the same email is a legitimate
        # resend, decided below in clean() once we have both fields.
        return self.cleaned_data["username"]

    def clean(self):
        cleaned = super().clean()
        username = cleaned.get("username")
        email = cleaned.get("email")
        if not username or not email:
            return cleaned

        existing = User.objects.filter(username__iexact=username).first()
        if existing is not None:
            if existing.is_active or existing.email.lower() != email.lower():
                self.add_error("username", "That username is " + ALREADY_REGISTERED)
            else:
                self.retry_user = existing
        elif User.objects.filter(email__iexact=email).exists():
            self.add_error("email", "That email is " + ALREADY_REGISTERED)
        return cleaned

    def validate_unique(self):
        # The model-level unique=True on username would otherwise reject
        # the resend case here as a plain duplicate; clean() already made
        # the real decision above.
        if self.retry_user is not None:
            return
        super().validate_unique()
