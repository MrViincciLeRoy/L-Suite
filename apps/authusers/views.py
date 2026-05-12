from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import (
    UserCreationForm, AuthenticationForm, PasswordChangeForm,
    PasswordResetForm, SetPasswordForm,
)
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string

from .models import SocialLink, PLATFORM_SUGGESTIONS


# ── Auth ──────────────────────────────────────────────────────────────────────

def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('main:index')
    else:
        form = UserCreationForm()
    return render(request, 'auth/register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect(request.GET.get('next', 'main:index'))
    else:
        form = AuthenticationForm()
    return render(request, 'auth/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('authusers:login')


# ── Profile ───────────────────────────────────────────────────────────────────

@login_required
def profile(request):
    social_links = SocialLink.objects.filter(user=request.user)
    return render(request, 'auth/profile.html', {
        'social_links':         social_links,
        'platform_suggestions': PLATFORM_SUGGESTIONS,
    })


# ── Password Change (while logged in) ────────────────────────────────────────

@login_required
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed successfully.')
            return redirect('authusers:profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'auth/change_password.html', {'form': form})


# ── Password Reset (logged out flow) ─────────────────────────────────────────

def password_reset_request(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        users = User.objects.filter(email__iexact=email)
        if users.exists():
            for user in users:
                uid   = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_url = request.build_absolute_uri(
                    f"/authusers/reset/{uid}/{token}/"
                )
                subject = "LSuite — Password Reset"
                body = render_to_string('auth/email/password_reset.txt', {
                    'user': user,
                    'reset_url': reset_url,
                })
                send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])
        # Always show done page (don't leak whether email exists)
        return redirect('authusers:password_reset_done')
    return render(request, 'auth/password_reset.html')


def password_reset_done(request):
    return render(request, 'auth/password_reset_done.html')


def password_reset_confirm(request, uidb64, token):
    try:
        uid  = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    valid = user is not None and default_token_generator.check_token(user, token)

    if request.method == 'POST' and valid:
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Password reset successfully. You can now log in.')
            return redirect('authusers:password_reset_complete')
    else:
        form = SetPasswordForm(user) if valid else None

    return render(request, 'auth/password_reset_confirm.html', {
        'form':  form,
        'valid': valid,
    })


def password_reset_complete(request):
    return render(request, 'auth/password_reset_complete.html')


# ── Social Links ──────────────────────────────────────────────────────────────

@login_required
@require_POST
def social_link_save(request, pk=None):
    platform = request.POST.get('platform', '').strip()
    url      = request.POST.get('url', '').strip()

    if not platform or not url:
        return JsonResponse({'ok': False, 'error': 'Platform and URL are required.'})

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    if pk:
        link = get_object_or_404(SocialLink, pk=pk, user=request.user)
        link.platform = platform
        link.url      = url
        link.save()
    else:
        link = SocialLink.objects.create(user=request.user, platform=platform, url=url)

    return JsonResponse({
        'ok':       True,
        'id':       link.pk,
        'platform': link.platform,
        'url':      link.url,
        'icon':     link.get_icon(),
    })


@login_required
@require_POST
def social_link_delete(request, pk):
    get_object_or_404(SocialLink, pk=pk, user=request.user).delete()
    return JsonResponse({'ok': True})
