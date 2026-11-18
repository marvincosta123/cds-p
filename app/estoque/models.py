from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class Produto(models.Model):
    nome = models.CharField(max_length=120)
    categoria = models.CharField(max_length=60, blank=True)
    preco_venda = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['nome', 'categoria'], name='produto_nome_categoria_unico'),
        ]
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Variacao(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='variacoes')
    tamanho = models.CharField(max_length=10)
    cor = models.CharField(max_length=40)
    quantidade_estoque = models.PositiveIntegerField(default=0)
    estoque_minimo = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['produto', 'tamanho', 'cor'], name='variacao_unica'),
        ]
        ordering = ['produto__nome', 'tamanho', 'cor']

    def __str__(self):
        return f'{self.produto.nome} {self.tamanho} {self.cor}'

    @property
    def estoque_baixo(self):
        return self.quantidade_estoque <= self.estoque_minimo


class Venda(models.Model):
    class Canal(models.TextChoices):
        LOJA = 'loja', 'Loja'
        WHATSAPP = 'whatsapp', 'WhatsApp'
        INSTAGRAM = 'instagram', 'Instagram'

    class Pagamento(models.TextChoices):
        PAGO = 'pago', 'Pago'
        PENDENTE = 'pendente', 'Pendente'

    data_hora = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='vendas')
    canal = models.CharField(max_length=10, choices=Canal.choices)
    situacao_pagamento = models.CharField(max_length=10, choices=Pagamento.choices)
    nome_cliente = models.CharField(max_length=80, blank=True)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2)
    observacao = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(valor_total__gte=0), name='venda_valor_nao_negativo'),
            models.CheckConstraint(
                condition=Q(situacao_pagamento='pago') | ~Q(nome_cliente=''),
                name='venda_pendente_exige_cliente',
            ),
        ]
        ordering = ['-data_hora']


class ItemVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='itens')
    variacao = models.ForeignKey(Variacao, on_delete=models.PROTECT, related_name='itens_venda')
    quantidade = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['venda', 'variacao'], name='item_unico_por_venda'),
            models.CheckConstraint(condition=Q(quantidade__gte=1), name='item_quantidade_positiva'),
        ]


class TentativaLogin(models.Model):
    """Contador de falhas de login por nome de usuário (RNF01).

    Guarda o texto digitado, exista ou não o usuário, para o bloqueio não
    revelar quais contas existem.
    """
    usuario = models.CharField(max_length=150, unique=True)
    falhas = models.PositiveIntegerField(default=0)
    bloqueado_ate = models.DateTimeField(null=True, blank=True)
