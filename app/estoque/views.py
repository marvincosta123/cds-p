from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import ItemVendaFormSet, ProdutoForm, VendaForm
from .models import Produto, Variacao
from .services import RegraDeNegocioError, registrar_venda


def _estoque_baixo():
    return Variacao.objects.filter(
        produto__ativo=True, quantidade_estoque__lte=F('estoque_minimo')
    ).select_related('produto').order_by('quantidade_estoque', 'produto__nome')


@login_required
def menu(request):
    return render(request, 'estoque/menu.html', {'total_alertas': _estoque_baixo().count()})


@login_required
@require_http_methods(['GET', 'POST'])
def nova_venda(request):
    cabecalho = VendaForm(request.POST or None, prefix='v')
    itens = ItemVendaFormSet(request.POST or None, prefix='i')
    if request.method == 'POST' and cabecalho.is_valid() and itens.is_valid():
        dados = cabecalho.cleaned_data
        lista = [
            {'variacao_id': f.cleaned_data['variacao'].pk, 'quantidade': f.cleaned_data['quantidade']}
            for f in itens if f.has_changed()
        ]
        try:
            registrar_venda(
                usuario=request.user, itens=lista, canal=dados['canal'],
                situacao_pagamento=dados['situacao_pagamento'], nome_cliente=dados['nome_cliente'],
            )
        except RegraDeNegocioError as erro:
            cabecalho.add_error(None, str(erro))
        else:
            if len(lista) == 1:
                saldo = Variacao.objects.get(pk=lista[0]['variacao_id']).quantidade_estoque
                messages.success(request, f'Venda registrada. Estoque atual: {saldo} unidades')
            else:
                messages.success(request, f'Venda registrada com {len(lista)} peças.')
            return redirect('resultado')
    return render(request, 'estoque/nova_venda.html', {'cabecalho': cabecalho, 'itens': itens})


@login_required
def resultado(request):
    return render(request, 'estoque/resultado.html', {'alertas': _estoque_baixo()})


@login_required
def consultar(request):
    termo = (request.GET.get('q') or '').strip()
    variacoes = []
    if termo:
        variacoes = Variacao.objects.filter(
            Q(produto__nome__icontains=termo) | Q(produto__categoria__icontains=termo), produto__ativo=True
        ).select_related('produto')
    return render(request, 'estoque/consultar.html', {'termo': termo, 'variacoes': variacoes})


@login_required
@require_http_methods(['GET', 'POST'])
def cadastrar_produto(request):
    form = ProdutoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        dados = form.cleaned_data
        with transaction.atomic():
            produto = form.save()
            Variacao.objects.create(
                produto=produto, tamanho=dados['tamanho'], cor=dados['cor'],
                quantidade_estoque=dados['quantidade_estoque'], estoque_minimo=dados['estoque_minimo'],
            )
        messages.success(request, 'Produto cadastrado.')
        return redirect('menu')
    return render(request, 'estoque/cadastrar_produto.html', {'form': form})
