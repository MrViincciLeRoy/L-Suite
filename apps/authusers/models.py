from django.db import models
from django.contrib.auth.models import User

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
