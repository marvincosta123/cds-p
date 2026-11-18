from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .seguranca import LoginComBloqueioForm

urlpatterns = [
    path('', views.menu, name='menu'),
    path('entrar/', auth_views.LoginView.as_view(template_name='registration/login.html', authentication_form=LoginComBloqueioForm), name='login'),
    path('sair/', auth_views.LogoutView.as_view(), name='logout'),
    path('venda/nova/', views.nova_venda, name='nova_venda'),
    path('resultado/', views.resultado, name='resultado'),
    path('consultar/', views.consultar, name='consultar'),
    path('produtos/novo/', views.cadastrar_produto, name='cadastrar_produto'),
]
