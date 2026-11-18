import re
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q, Sum
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import ItemVendaFormSet, NovaVariacaoForm, ProdutoForm, ReposicaoForm, VendaForm
from .models import ItemVenda, Produto, Variacao, Venda
from .services import RegraDeNegocioError, criar_variacao, registrar_venda, repor_estoque


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


def _limites_do_mes(texto):
    """Converte 'AAAA-MM' no intervalo [início, fim) do mês, no fuso configurado."""
    if texto and re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', texto):
        ano, mes = int(texto[:4]), int(texto[5:])
    else:
        hoje = timezone.localdate()
        ano, mes = hoje.year, hoje.month
    fuso = timezone.get_current_timezone()
    inicio = datetime(ano, mes, 1, tzinfo=fuso)
    fim = datetime(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1, tzinfo=fuso)
    return ano, mes, inicio, fim


@login_required
def relatorio(request):
    """Relatório mensal: total vendido, peças mais vendidas e vendas pendentes (RF07)."""
    bruto = request.GET.get('mes', '')
    ano, mes, inicio, fim = _limites_do_mes(bruto)
    vendas = Venda.objects.filter(data_hora__gte=inicio, data_hora__lt=fim)
    total = vendas.aggregate(t=Sum('valor_total'))['t'] or 0
    mais_vendidas = (
        ItemVenda.objects.filter(venda__in=vendas)
        .values('variacao__produto__nome', 'variacao__tamanho', 'variacao__cor')
        .annotate(unidades=Sum('quantidade'))
        .order_by('-unidades', 'variacao__produto__nome')[:5]
    )
    pendentes = vendas.filter(situacao_pagamento=Venda.Pagamento.PENDENTE).order_by('data_hora')
    return render(request, 'estoque/relatorio.html', {
        'mes_valor': f'{ano:04d}-{mes:02d}', 'mes_texto': f'{mes:02d}/{ano}',
        'mes_invalido': bool(bruto) and bruto != f'{ano:04d}-{mes:02d}',
        'quantidade_vendas': vendas.count(), 'total': total,
        'mais_vendidas': mais_vendidas, 'pendentes': pendentes,
        'total_pendente': pendentes.aggregate(t=Sum('valor_total'))['t'] or 0,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def repor(request):
    """Entrada de mercadoria: soma unidades ao saldo de uma variação."""
    form = ReposicaoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            variacao = repor_estoque(variacao_id=form.cleaned_data['variacao'].pk, quantidade=form.cleaned_data['quantidade'])
        except RegraDeNegocioError as erro:
            form.add_error(None, str(erro))
        else:
            messages.success(request, f'Estoque atualizado. {variacao.produto.nome} {variacao.tamanho} {variacao.cor}: {variacao.quantidade_estoque} unidades')
            return redirect('repor')
    return render(request, 'estoque/repor.html', {'form': form})


@login_required
@require_http_methods(['GET', 'POST'])
def nova_variacao(request):
    """Acrescenta tamanho e cor a um produto já cadastrado."""
    form = NovaVariacaoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            variacao = criar_variacao(produto_id=form.cleaned_data['produto'].pk, **{k: form.cleaned_data[k] for k in ('tamanho', 'cor', 'quantidade_estoque', 'estoque_minimo')})
        except RegraDeNegocioError as erro:
            form.add_error(None, str(erro))
        else:
            messages.success(request, f'Variação cadastrada: {variacao.produto.nome} {variacao.tamanho} {variacao.cor}.')
            return redirect('nova_variacao')
    return render(request, 'estoque/nova_variacao.html', {'form': form})


def saude(request):
    """Verificação de disponibilidade para monitoramento (pública, sem dados sensíveis)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return JsonResponse({'status': 'erro', 'banco': 'indisponivel'}, status=503)
    return JsonResponse({'status': 'ok', 'banco': 'ok'})
