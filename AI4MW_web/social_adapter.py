from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model


class AutoConnectSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            return
        if request.user.is_authenticated:
            return
        email_addresses = sociallogin.account.extra_data.get("email")
        email = email_addresses
        if not email:
            return
        user_model = get_user_model()
        try:
            user = user_model.objects.get(email__iexact=email)
        except user_model.DoesNotExist:
            return
        sociallogin.connect(request, user)
