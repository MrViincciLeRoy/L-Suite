from pathlib import Path
import os
from dotenv import load_dotenv
import dj_database_url

# Load .env from project root (same level as manage.py)
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

BASE_DIR = Path(__file__).resolve().parent.parent

HUGGINGFACE_API_KEY = os.environ.get('HUGGINGFACE_API_KEY', '')

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-change-me-in-production')

DEBUG = os.environ.get('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # social auth
    "social_django",
    # local apps
    "apps.api",
    "apps.authusers",
    "apps.bridge",
    "apps.erpnext",
    "apps.gmail",
    "apps.main",
    "apps.bank_parsers",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "social_django.middleware.SocialAuthExceptionMiddleware",
]

ROOT_URLCONF = "LSuite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / 'templates'],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
            ],
        },
    },
]

WSGI_APPLICATION = "LSuite.wsgi.application"

# ?? Database ??????????????????????????????????????????????????????????????????
_DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

def _is_valid_db_url(url):
    """Returns True only if url looks like a real connection string."""
    if not url:
        return False
    if '://' not in url:
        return False
    scheme = url.split('://')[0].lower()
    if not url.split('://')[1]:
        return False
    return scheme in ('mysql', 'mysql2', 'postgres', 'postgresql', 'sqlite', 'sqlite3')

if _is_valid_db_url(_DATABASE_URL):
    _db_config = dj_database_url.parse(_DATABASE_URL, conn_max_age=600)
    if _db_config.get('ENGINE', '').endswith('mysql'):
        opts = _db_config.setdefault('OPTIONS', {})
        opts.pop('ssl-mode', None)
        opts.pop('ssl_mode', None)
        opts['ssl'] = {'ssl_disabled': False}
    DATABASES = {'default': _db_config}
elif not DEBUG:
    raise RuntimeError(
        "DATABASE_URL is missing or invalid. "
        f"Current value: {_DATABASE_URL!r}. "
        "Set it to a full connection string, e.g. "
        "mysql://user:pass@host:3306/dbname"
    )
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ?? Auth ??????????????????????????????????????????????????????????????????????
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    'social_core.backends.google.GoogleOAuth2',
    'social_core.backends.github.GithubOAuth2',
    'social_core.backends.facebook.FacebookOAuth2',
    'django.contrib.auth.backends.ModelBackend',
]

LOGIN_URL           = '/authusers/login/'
LOGIN_REDIRECT_URL  = '/'
LOGOUT_REDIRECT_URL = '/authusers/login/'

# ?? Social Auth ???????????????????????????????????????????????????????????????
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY    = os.environ.get('GOOGLE_CLIENT_ID', '')
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE  = ['openid', 'email', 'profile']

SOCIAL_AUTH_GITHUB_KEY    = os.environ.get('GITHUB_CLIENT_ID', '')
SOCIAL_AUTH_GITHUB_SECRET = os.environ.get('GITHUB_CLIENT_SECRET', '')
SOCIAL_AUTH_GITHUB_SCOPE  = ['user:email']

SOCIAL_AUTH_FACEBOOK_KEY    = os.environ.get('FACEBOOK_APP_ID', '')
SOCIAL_AUTH_FACEBOOK_SECRET = os.environ.get('FACEBOOK_APP_SECRET', '')
SOCIAL_AUTH_FACEBOOK_SCOPE  = ['email', 'public_profile']
SOCIAL_AUTH_FACEBOOK_PROFILE_EXTRA_PARAMS = {'fields': 'id,name,email,first_name,last_name'}

SOCIAL_AUTH_LOGIN_REDIRECT_URL    = '/'
SOCIAL_AUTH_NEW_USER_REDIRECT_URL = '/authusers/social/complete/'
SOCIAL_AUTH_LOGIN_ERROR_URL       = '/authusers/login/'

SOCIAL_AUTH_PIPELINE = (
    'social_core.pipeline.social_auth.social_details',
    'social_core.pipeline.social_auth.social_uid',
    'social_core.pipeline.social_auth.auth_allowed',
    'social_core.pipeline.social_auth.social_user',
    'social_core.pipeline.user.get_username',
    'social_core.pipeline.user.create_user',
    'social_core.pipeline.social_auth.associate_user',
    'social_core.pipeline.social_auth.load_extra_data',
    'social_core.pipeline.user.user_details',
    'apps.authusers.pipeline.save_social_profile',
)

# ?? i18n / timezone ???????????????????????????????????????????????????????????
LANGUAGE_CODE = "en-us"
TIME_ZONE     = "UTC"
USE_I18N      = True
USE_TZ        = True

# ?? Static files ??????????????????????????????????????????????????????????????
STATIC_URL        = "/static/"
STATICFILES_DIRS  = [BASE_DIR / 'static']
STATIC_ROOT       = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/'
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ?? Email ?????????????????????????????????????????????????????????????????????
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', '')
EMAIL_BACKEND       = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST          = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT          = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS       = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER     = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL  = os.environ.get('DEFAULT_FROM_EMAIL', 'LSuite <noreply@example.com>')

# ?? Sessions ??????????????????????????????????????????????????????????????????
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 1209600  # 2 weeks
