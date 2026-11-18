from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .seguranca import LoginComBloqueioForm

urlpatterns = [
    path('', views.menu, name='menu'),
    path('entrar/', auth_views.LoginView.as_view(template_name='registration/login.html', authentication_form=LoginComBloqueioForm), name='login'),
    path('saude/', views.saude, name='saude'),
    path('sair/', auth_views.LogoutView.as_view(), name='logout'),
    path('venda/nova/', views.nova_venda, name='nova_venda'),
    path('resultado/', views.resultado, name='resultado'),
    path('relatorio/', views.relatorio, name='relatorio'),
    path('consultar/', views.consultar, name='consultar'),
    path('estoque/repor/', views.repor, name='repor'),
    path('estoque/variacao/nova/', views.nova_variacao, name='nova_variacao'),
    path('produtos/novo/', views.cadastrar_produto, name='cadastrar_produto'),
]
