from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

PLATFORM_ICONS = {
    "linkedin":      "🔗",
    "github":        "🐙",
    "twitter":       "🐦",
    "instagram":     "📷",
    "facebook":      "📘",
    "youtube":       "▶️",
    "tiktok":        "🎵",
    "behance":       "🎨",
    "dribbble":      "🏀",
    "stackoverflow": "📚",
    "kaggle":        "📊",
    "medium":        "✍️",
    "substack":      "📬",
    "portfolio":     "🌐",
}

PLATFORM_SUGGESTIONS = [
    "LinkedIn", "GitHub", "Portfolio", "Twitter / X", "Instagram",
    "Facebook", "YouTube", "TikTok", "Behance", "Dribbble",
    "Stack Overflow", "Kaggle", "Medium", "Substack", "Personal Website",
    "Other",
]

YEARS_EXP_CHOICES = [
    ("",     "Select..."),
    ("0-1",  "Less than 1 year"),
    ("1-2",  "1–2 years"),
    ("3-5",  "3–5 years"),
    ("5-10", "5–10 years"),
    ("10+",  "10+ years"),
]


class UserProfile(models.Model):
    user             = models.OneToOneField(User, on_delete=models.CASCADE, related_name="lsuite_profile")
    phone            = models.CharField(max_length=30, blank=True)
    date_of_birth    = models.DateField(null=True, blank=True)
    id_number        = models.CharField(max_length=20, blank=True)
    city             = models.CharField(max_length=100, blank=True)
    province         = models.CharField(max_length=100, blank=True)
    country          = models.CharField(max_length=100, blank=True)
    occupation       = models.CharField(max_length=100, blank=True)
    years_experience = models.CharField(max_length=10, blank=True, choices=YEARS_EXP_CHOICES)
    industry         = models.CharField(max_length=100, blank=True)
    linkedin_url     = models.URLField(blank=True)
    github_url       = models.URLField(blank=True)
    portfolio_url    = models.URLField(blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.user.username}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


class SocialLink(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="authuser_social_links")
    platform   = models.CharField(max_length=80)
    url        = models.URLField(max_length=500)
    icon       = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["platform"]

    def __str__(self):
        return f"{self.platform}: {self.url}"

    def get_icon(self):
        if self.icon:
            return self.icon
        key = self.platform.lower().split("/")[0].strip()
        for k, v in PLATFORM_ICONS.items():
            if k in key:
                return v
        return "🔗"
