from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import UserProfile, SocialLink


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ('user', 'occupation', 'industry', 'city', 'country', 'years_experience', 'created_at')
    search_fields = ('user__username', 'user__email', 'occupation', 'industry', 'city', 'country')
    list_filter   = ('country', 'province', 'industry', 'years_experience')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(SocialLink)
class SocialLinkAdmin(admin.ModelAdmin):
    list_display  = ('user', 'platform', 'url', 'created_at')
    search_fields = ('user__username', 'platform', 'url')
    list_filter   = ('platform',)
    readonly_fields = ('created_at',)
