"""Regras de negócio do estoque, isoladas das views e do acesso a dados."""
from decimal import Decimal

from django.db import transaction

from .models import ItemVenda, Variacao, Venda


class RegraDeNegocioError(Exception):
    """Erro de regra de negócio com mensagem pronta para o usuário."""


@transaction.atomic
def registrar_venda(*, usuario, itens, canal, situacao_pagamento, nome_cliente=''):
    """Registra uma venda e dá baixa no estoque na mesma transação (RF02, RF03).

    `itens` é uma lista de dicts: {'variacao_id': int, 'quantidade': int}.
    Se qualquer item for inválido ou exceder o saldo, nada é gravado.
    """
    if not itens:
        raise RegraDeNegocioError('Informe ao menos um item.')
    if canal not in Venda.Canal.values:
        raise RegraDeNegocioError('Canal de venda inválido.')
    if situacao_pagamento not in Venda.Pagamento.values:
        raise RegraDeNegocioError('Situação de pagamento inválida.')
    nome_cliente = (nome_cliente or '').strip()
    if situacao_pagamento == Venda.Pagamento.PENDENTE and not nome_cliente:
        raise RegraDeNegocioError('Informe o nome do cliente para venda pendente.')

    ids = [i['variacao_id'] for i in itens]
    if len(set(ids)) != len(ids):
        raise RegraDeNegocioError('A mesma variação não pode repetir na venda.')

    # select_for_update evita que duas vendas simultâneas gastem o mesmo saldo
    variacoes = {
        v.pk: v
        for v in Variacao.objects.select_for_update()
        .select_related('produto')
        .filter(pk__in=ids, produto__ativo=True)
    }

    total = Decimal('0.00')
    linhas = []
    for item in itens:
        variacao = variacoes.get(item['variacao_id'])
        if variacao is None:
            raise RegraDeNegocioError('Peça não encontrada.')
        quantidade = item['quantidade']
        if not isinstance(quantidade, int) or quantidade < 1:
            raise RegraDeNegocioError('A quantidade deve ser maior que zero.')
        if quantidade > variacao.quantidade_estoque:
            raise RegraDeNegocioError(
                f'Só há {variacao.quantidade_estoque} unidade(s) em estoque. '
                f'Informe {variacao.quantidade_estoque} ou menos.'
            )
        preco = variacao.produto.preco_venda
        total += preco * quantidade
        linhas.append((variacao, quantidade, preco))

    venda = Venda.objects.create(
        usuario=usuario, canal=canal, situacao_pagamento=situacao_pagamento,
        nome_cliente=nome_cliente, valor_total=total,
    )
    for variacao, quantidade, preco in linhas:
        ItemVenda.objects.create(venda=venda, variacao=variacao, quantidade=quantidade, preco_unitario=preco)
        variacao.quantidade_estoque -= quantidade
        variacao.save(update_fields=['quantidade_estoque'])
    return venda
