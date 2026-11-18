from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import ItemVenda, Produto, Variacao, Venda
from .services import RegraDeNegocioError, registrar_venda


class BaseTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('jaqueline', password='senha-de-teste-123')
        self.produto = Produto.objects.create(nome='Vestido floral', categoria='vestido', preco_venda=Decimal('89.90'))
        self.m_preta = Variacao.objects.create(produto=self.produto, tamanho='M', cor='Preta', quantidade_estoque=1, estoque_minimo=1)
        self.g_azul = Variacao.objects.create(produto=self.produto, tamanho='G', cor='Azul', quantidade_estoque=5, estoque_minimo=2)

    def vender(self, itens, **kw):
        kw.setdefault('canal', 'whatsapp')
        kw.setdefault('situacao_pagamento', 'pago')
        return registrar_venda(usuario=self.user, itens=itens, **kw)


class RegistroDeVendaTest(BaseTest):
    def test_venda_com_saldo_da_baixa_e_calcula_total(self):
        venda = self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': 2}])
        self.g_azul.refresh_from_db()
        self.assertEqual(self.g_azul.quantidade_estoque, 3)
        self.assertEqual(venda.valor_total, Decimal('179.80'))
        self.assertEqual(ItemVenda.objects.get(venda=venda).preco_unitario, Decimal('89.90'))

    def test_recusa_quantidade_maior_que_o_saldo_sem_gravar_nada(self):
        with self.assertRaisesMessage(RegraDeNegocioError, 'Só há 1 unidade(s) em estoque'):
            self.vender([{'variacao_id': self.m_preta.pk, 'quantidade': 2}])
        self.m_preta.refresh_from_db()
        self.assertEqual(self.m_preta.quantidade_estoque, 1)
        self.assertEqual(Venda.objects.count(), 0)

    def test_falha_em_um_item_nao_baixa_os_outros(self):
        with self.assertRaises(RegraDeNegocioError):
            self.vender([
                {'variacao_id': self.g_azul.pk, 'quantidade': 1},
                {'variacao_id': self.m_preta.pk, 'quantidade': 9},
            ])
        self.g_azul.refresh_from_db()
        self.assertEqual(self.g_azul.quantidade_estoque, 5)
        self.assertEqual(Venda.objects.count(), 0)

    def test_quantidade_zero_ou_negativa_e_recusada(self):
        for q in (0, -1):
            with self.assertRaises(RegraDeNegocioError):
                self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': q}])
        self.assertEqual(Venda.objects.count(), 0)

    def test_quantidade_nao_inteira_e_recusada(self):
        with self.assertRaises(RegraDeNegocioError):
            self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': '1; DROP TABLE'}])

    def test_venda_pendente_exige_nome_do_cliente(self):
        with self.assertRaises(RegraDeNegocioError):
            self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': 1}], situacao_pagamento='pendente')
        venda = self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': 1}], situacao_pagamento='pendente', nome_cliente='Cliente Teste')
        self.assertEqual(venda.situacao_pagamento, 'pendente')

    def test_canal_e_pagamento_invalidos_sao_recusados(self):
        item = [{'variacao_id': self.g_azul.pk, 'quantidade': 1}]
        with self.assertRaises(RegraDeNegocioError):
            self.vender(item, canal='telegrama')
        with self.assertRaises(RegraDeNegocioError):
            self.vender(item, situacao_pagamento='fiado')

    def test_produto_inativo_nao_pode_ser_vendido(self):
        self.produto.ativo = False
        self.produto.save()
        with self.assertRaises(RegraDeNegocioError):
            self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': 1}])

    def test_variacao_repetida_na_mesma_venda_e_recusada(self):
        with self.assertRaises(RegraDeNegocioError):
            self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': 1}, {'variacao_id': self.g_azul.pk, 'quantidade': 1}])


class RestricoesDoBancoTest(BaseTest):
    def test_variacao_duplicada_e_rejeitada(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Variacao.objects.create(produto=self.produto, tamanho='M', cor='Preta')

    def test_estoque_baixo_quando_saldo_menor_ou_igual_ao_minimo(self):
        self.assertTrue(self.m_preta.estoque_baixo)
        self.assertFalse(self.g_azul.estoque_baixo)
