from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.main.urls', 'main')),
    path('authusers/', include('apps.authusers.urls', 'authusers')),
    path('erpnext/', include('apps.erpnext.urls', namespace='erpnext')),
    path('bridge/', include('apps.bridge.urls', namespace='bridge')),
    path('gmail/', include('apps.gmail.urls', namespace='gmail')),
    path('social/', include('social_django.urls', namespace='social')),
    path('reconciliation/', include('apps.reconciliation.urls', namespace='reconciliation')),  # ? add this

]