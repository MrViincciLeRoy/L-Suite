from django.urls import path
from . import views

app_name='main'
urlpatterns = [
    path('',views.about,name='about'),
    path('index/',views.index,name='index'),
    #path('health/',views.health_check,name='health'),
]