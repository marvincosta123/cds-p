from django import forms

from .models import Produto, Variacao, Venda


def _estilo(form):
    for campo in form.fields.values():
        campo.widget.attrs.setdefault('class', 'field')


class ProdutoForm(forms.ModelForm):
    tamanho = forms.CharField(label='Tamanho', max_length=10)
    cor = forms.CharField(label='Cor', max_length=40)
    quantidade_estoque = forms.IntegerField(label='Quantidade em estoque', min_value=0)
    estoque_minimo = forms.IntegerField(label='Estoque mínimo', min_value=0, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilo(self)

    class Meta:
        model = Produto
        fields = ['nome', 'categoria', 'preco_venda']
        labels = {'nome': 'Nome do produto', 'categoria': 'Categoria', 'preco_venda': 'Preço de venda (R$)'}

    def clean_nome(self):
        nome = self.cleaned_data['nome'].strip()
        if not nome:
            raise forms.ValidationError('Informe o nome do produto.')
        return nome

    def clean_tamanho(self):
        return self.cleaned_data['tamanho'].strip().upper()

    def clean_cor(self):
        return self.cleaned_data['cor'].strip().capitalize()

    def clean(self):
        dados = super().clean()
        nome, categoria = dados.get('nome'), (dados.get('categoria') or '').strip()
        if nome and Produto.objects.filter(nome__iexact=nome, categoria__iexact=categoria).exists():
            raise forms.ValidationError('Este produto já está cadastrado. Cadastre só uma nova variação.')
        return dados


class VendaForm(forms.Form):
    variacao = forms.ModelChoiceField(label='Peça (tamanho e cor)', queryset=Variacao.objects.none())
    quantidade = forms.IntegerField(label='Quantidade', min_value=1)
    canal = forms.ChoiceField(label='Canal da venda', choices=Venda.Canal.choices)
    situacao_pagamento = forms.ChoiceField(label='Pagamento', choices=Venda.Pagamento.choices)
    nome_cliente = forms.CharField(label='Nome do cliente (obrigatório se pendente)', max_length=80, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilo(self)
        self.fields['variacao'].queryset = Variacao.objects.filter(produto__ativo=True).select_related('produto')
        self.fields['variacao'].label_from_instance = (
            lambda v: f'{v.produto.nome} – {v.tamanho} – {v.cor} (saldo: {v.quantidade_estoque} un.)'
        )
