"""Bloqueio temporário de login após falhas repetidas (RNF01)."""
from datetime import timedelta

from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import TentativaLogin

LIMITE_FALHAS = 5
MINUTOS_BLOQUEIO = 15


def _chave(username):
    return (username or '').strip().lower()[:150]


def esta_bloqueado(username):
    chave = _chave(username)
    if not chave:
        return False
    t = TentativaLogin.objects.filter(usuario=chave).first()
    return bool(t and t.bloqueado_ate and t.bloqueado_ate > timezone.now())


def registrar_falha(username):
    chave = _chave(username)
    if not chave:
        return
    t, _ = TentativaLogin.objects.get_or_create(usuario=chave)
    # Bloqueio expirado: recomeça a contagem
    if t.bloqueado_ate and t.bloqueado_ate <= timezone.now():
        t.falhas, t.bloqueado_ate = 0, None
    t.falhas += 1
    if t.falhas >= LIMITE_FALHAS:
        t.bloqueado_ate = timezone.now() + timedelta(minutes=MINUTOS_BLOQUEIO)
    t.save()


def limpar_falhas(username):
    TentativaLogin.objects.filter(usuario=_chave(username)).delete()


class LoginComBloqueioForm(AuthenticationForm):
    """Login que bloqueia por 15 min após 5 falhas seguidas, mesmo com senha correta."""

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Usuário ou senha inválidos.',  # genérica: não revela qual dado falhou
        'inactive': 'Usuário ou senha inválidos.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs['class'] = 'field'
        self.fields['username'].widget.attrs.update({'autocomplete': 'username', 'autocapitalize': 'none'})
        self.fields['password'].widget.attrs['autocomplete'] = 'current-password'

    def clean(self):
        username = self.data.get(self.add_prefix('username'), '')
        if esta_bloqueado(username):
            raise ValidationError(
                f'Muitas tentativas. Aguarde {MINUTOS_BLOQUEIO} minutos e tente novamente.',
                code='bloqueado',
            )
        try:
            dados = super().clean()
        except ValidationError:
            registrar_falha(username)
            raise
        limpar_falhas(username)
        return dados
