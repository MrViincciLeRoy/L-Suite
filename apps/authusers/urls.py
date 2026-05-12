from django.urls import path
from . import views

app_name = 'authusers'

urlpatterns = [
    path('register/',          views.register_view,           name='register'),
    path('login/',             views.login_view,              name='login'),
    path('logout/',            views.logout_view,             name='logout'),
    path('profile/',           views.profile,                 name='profile'),
    path('change-password/',   views.change_password,         name='change_password'),

    path('reset/',                     views.password_reset_request,  name='password_reset'),
    path('reset/done/',                views.password_reset_done,     name='password_reset_done'),
    path('reset/<uidb64>/<token>/',    views.password_reset_confirm,  name='password_reset_confirm'),
    path('reset/complete/',            views.password_reset_complete, name='password_reset_complete'),

    path('links/add/',             views.social_link_save,   name='link_add'),
    path('links/<int:pk>/edit/',   views.social_link_save,   name='link_edit'),
    path('links/<int:pk>/delete/', views.social_link_delete, name='link_delete'),
]
