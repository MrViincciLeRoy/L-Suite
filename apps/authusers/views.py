from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm
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

from .models import SocialLink, UserProfile, PLATFORM_SUGGESTIONS


def _get_or_create_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


# ── Register ──────────────────────────────────────────────────────────────────

def register_view(request):
    errors = {}

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip().lower()
        username   = request.POST.get('username', '').strip()
        password1  = request.POST.get('password1', '')
        password2  = request.POST.get('password2', '')

        if not first_name:
            errors['first_name'] = 'First name is required.'
        if not last_name:
            errors['last_name'] = 'Last name is required.'
        if not email:
            errors['email'] = 'Email is required.'
        elif User.objects.filter(email__iexact=email).exists():
            errors['email'] = 'An account with this email already exists.'
        if not username:
            errors['username'] = 'Username is required.'
        elif User.objects.filter(username__iexact=username).exists():
            errors['username'] = 'That username is already taken.'
        if not password1:
            errors['password1'] = 'Password is required.'
        elif len(password1) < 8:
            errors['password1'] = 'Password must be at least 8 characters.'
        if password1 != password2:
            errors['password2'] = 'Passwords do not match.'

        if not errors:
            user = User.objects.create_user(
                username   = username,
                email      = email,
                password   = password1,
                first_name = first_name,
                last_name  = last_name,
            )

            profile = _get_or_create_profile(user)
            profile.phone            = request.POST.get('phone', '').strip()
            profile.id_number        = request.POST.get('id_number', '').strip()
            profile.city             = request.POST.get('city', '').strip()
            profile.province         = request.POST.get('province', '').strip()
            profile.country          = request.POST.get('country', '').strip()
            profile.occupation       = request.POST.get('occupation', '').strip()
            profile.years_experience = request.POST.get('years_experience', '').strip()
            profile.industry         = request.POST.get('industry', '').strip()
            profile.linkedin_url     = request.POST.get('linkedin_url', '').strip()
            profile.github_url       = request.POST.get('github_url', '').strip()
            profile.portfolio_url    = request.POST.get('portfolio_url', '').strip()

            dob = request.POST.get('date_of_birth', '').strip()
            if dob:
                try:
                    from datetime import date
                    profile.date_of_birth = date.fromisoformat(dob)
                except ValueError:
                    pass

            profile.save()

            # FIX: With multiple AUTHENTICATION_BACKENDS configured (social_django
            # + ModelBackend), Django can't infer which backend authenticated this
            # user. Specify ModelBackend explicitly so login() doesn't raise.
            login(request, user,
                  backend='django.contrib.auth.backends.ModelBackend')

            return redirect('main:index')

    return render(request, 'auth/register.html', {
        'errors': errors,
        'error_keys': list(errors.keys()),
        'post': request.POST,
    })


# ── Social auth complete ───────────────────────────────────────────────────────

@login_required
def social_complete(request):
    """
    Landing page after a successful social login for a brand-new user.
    Lets them fill in any missing fields (occupation, province, etc.)
    that the provider couldn't supply. Existing users skip straight to index.
    """
    user    = request.user
    profile = _get_or_create_profile(user)

    if profile.occupation and profile.city:
        return redirect('main:index')

    if request.method == 'POST':
        profile.phone            = request.POST.get('phone', profile.phone or '').strip()
        profile.id_number        = request.POST.get('id_number', profile.id_number or '').strip()
        profile.city             = request.POST.get('city', profile.city or '').strip()
        profile.province         = request.POST.get('province', profile.province or '').strip()
        profile.country          = request.POST.get('country', profile.country or '').strip()
        profile.occupation       = request.POST.get('occupation', profile.occupation or '').strip()
        profile.years_experience = request.POST.get('years_experience', profile.years_experience or '').strip()
        profile.industry         = request.POST.get('industry', profile.industry or '').strip()
        profile.linkedin_url     = request.POST.get('linkedin_url', profile.linkedin_url or '').strip()
        profile.github_url       = request.POST.get('github_url', profile.github_url or '').strip()
        profile.portfolio_url    = request.POST.get('portfolio_url', profile.portfolio_url or '').strip()

        dob = request.POST.get('date_of_birth', '').strip()
        if dob and not profile.date_of_birth:
            try:
                from datetime import date
                profile.date_of_birth = date.fromisoformat(dob)
            except ValueError:
                pass

        profile.save()
        return redirect('main:index')

    return render(request, 'auth/social_complete.html', {
        'profile': profile,
        'user': user,
    })


# ── Login / Logout ────────────────────────────────────────────────────────────

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


# ── Password Change ───────────────────────────────────────────────────────────

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


# ── Password Reset ────────────────────────────────────────────────────────────

def password_reset_request(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        for user in User.objects.filter(email__iexact=email):
            uid       = urlsafe_base64_encode(force_bytes(user.pk))
            token     = default_token_generator.make_token(user)
            reset_url = request.build_absolute_uri(f"/authusers/reset/{uid}/{token}/")
            body = render_to_string('auth/email/password_reset.txt', {
                'user': user, 'reset_url': reset_url,
            })
            send_mail('LSuite — Password Reset', body,
                      settings.DEFAULT_FROM_EMAIL, [user.email])
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
            return redirect('authusers:password_reset_complete')
    else:
        form = SetPasswordForm(user) if valid else None

    return render(request, 'auth/password_reset_confirm.html', {'form': form, 'valid': valid})


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

    return JsonResponse({'ok': True, 'id': link.pk, 'platform': link.platform,
                         'url': link.url, 'icon': link.get_icon()})


@login_required
@require_POST
def social_link_delete(request, pk):
    get_object_or_404(SocialLink, pk=pk, user=request.user).delete()
    return JsonResponse({'ok': True})