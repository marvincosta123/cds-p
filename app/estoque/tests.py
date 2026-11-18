from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from .models import ItemVenda, Produto, TentativaLogin, Variacao, Venda
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


def dados_venda(*itens, canal='whatsapp', pagamento='pago', cliente=''):
    """Monta o POST do formulário de venda com formset de itens: (variacao_id, quantidade)."""
    d = {'v-canal': canal, 'v-situacao_pagamento': pagamento, 'v-nome_cliente': cliente,
         'i-TOTAL_FORMS': str(len(itens) + 1), 'i-INITIAL_FORMS': '0',
         'i-MIN_NUM_FORMS': '1', 'i-MAX_NUM_FORMS': '8'}
    for n, (variacao_id, quantidade) in enumerate(itens):
        d[f'i-{n}-variacao'] = variacao_id
        d[f'i-{n}-quantidade'] = quantidade
    return d


class TelasTest(BaseTest):
    URLS_PROTEGIDAS = ['menu', 'nova_venda', 'resultado', 'consultar', 'cadastrar_produto']

    def test_telas_internas_exigem_login(self):
        for nome in self.URLS_PROTEGIDAS:
            resposta = self.client.get(reverse(nome))
            self.assertEqual(resposta.status_code, 302, nome)
            self.assertIn(reverse('login'), resposta['Location'])

    def test_login_valido_e_invalido(self):
        ruim = self.client.post(reverse('login'), {'username': 'jaqueline', 'password': 'errada'})
        self.assertContains(ruim, 'Usuário ou senha inválidos.')
        self.assertNotContains(ruim, 'jaqueline não')
        bom = self.client.post(reverse('login'), {'username': 'jaqueline', 'password': 'senha-de-teste-123'})
        self.assertRedirects(bom, reverse('menu'))

    def test_logout_encerra_a_sessao(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        self.client.post(reverse('logout'))
        self.assertEqual(self.client.get(reverse('menu')).status_code, 302)

    def test_servidor_recusa_venda_acima_do_saldo_mesmo_contornando_a_tela(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        resposta = self.client.post(reverse('nova_venda'), dados_venda((self.m_preta.pk, 2)))
        self.assertContains(resposta, 'Só há 1 unidade(s) em estoque. Informe 1 ou menos.')
        self.m_preta.refresh_from_db()
        self.assertEqual(self.m_preta.quantidade_estoque, 1)
        self.assertEqual(Venda.objects.count(), 0)

    def test_venda_valida_baixa_estoque_e_mostra_alerta(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        resposta = self.client.post(reverse('nova_venda'), dados_venda((self.m_preta.pk, 1)), follow=True)
        self.assertContains(resposta, 'Venda registrada. Estoque atual: 0 unidades')
        self.assertContains(resposta, 'URGENTE')

    def test_texto_com_script_e_exibido_escapado(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        Produto.objects.create(nome='<script>alert(1)</script>', preco_venda=Decimal('10'))
        p = Produto.objects.get(nome__startswith='<script>')
        Variacao.objects.create(produto=p, tamanho='M', cor='Preta', quantidade_estoque=3)
        resposta = self.client.get(reverse('consultar'), {'q': 'script'})
        self.assertNotContains(resposta, '<script>alert(1)</script>')
        self.assertContains(resposta, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_busca_com_aspas_e_sql_e_tratada_como_texto(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        resposta = self.client.get(reverse('consultar'), {'q': "' OR 1=1 --"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Nenhuma peça encontrada.')
        self.assertEqual(Produto.objects.count(), 1)

    def test_cadastro_de_produto_com_variacao_e_duplicidade(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        dados = {'nome': 'Blusa listrada', 'categoria': 'blusa', 'preco_venda': '59.90',
                 'tamanho': 'p', 'cor': 'branca', 'quantidade_estoque': 4, 'estoque_minimo': 2}
        self.assertRedirects(self.client.post(reverse('cadastrar_produto'), dados), reverse('menu'))
        v = Variacao.objects.get(produto__nome='Blusa listrada')
        self.assertEqual((v.tamanho, v.cor, v.quantidade_estoque), ('P', 'Branca', 4))
        repetido = self.client.post(reverse('cadastrar_produto'), dados)
        self.assertContains(repetido, 'já está cadastrado')

    def test_rota_de_venda_nao_aceita_metodos_inesperados(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        self.assertEqual(self.client.delete(reverse('nova_venda')).status_code, 405)

    def test_venda_com_varias_pecas_baixa_cada_uma(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        resposta = self.client.post(
            reverse('nova_venda'), dados_venda((self.m_preta.pk, 1), (self.g_azul.pk, 2)), follow=True)
        self.assertContains(resposta, 'Venda registrada com 2 peças.')
        self.m_preta.refresh_from_db(); self.g_azul.refresh_from_db()
        self.assertEqual((self.m_preta.quantidade_estoque, self.g_azul.quantidade_estoque), (0, 3))
        self.assertEqual(Venda.objects.get().itens.count(), 2)

    def test_venda_com_varias_pecas_e_uma_invalida_nao_grava_nada(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        resposta = self.client.post(reverse('nova_venda'), dados_venda((self.g_azul.pk, 1), (self.m_preta.pk, 9)))
        self.assertContains(resposta, 'Só há 1 unidade(s) em estoque')
        self.g_azul.refresh_from_db()
        self.assertEqual(self.g_azul.quantidade_estoque, 5)
        self.assertEqual(Venda.objects.count(), 0)

    def test_tela_de_venda_tem_busca_e_varias_pecas(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        resposta = self.client.get(reverse('nova_venda'))
        self.assertContains(resposta, 'Buscar peça pelo nome')
        self.assertContains(resposta, 'Peça 3 (opcional)')

    def test_venda_pendente_pela_tela_exige_cliente(self):
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        resposta = self.client.post(reverse('nova_venda'), dados_venda((self.g_azul.pk, 1), pagamento='pendente'))
        self.assertContains(resposta, 'Informe o nome do cliente para venda pendente.')
        self.assertEqual(Venda.objects.count(), 0)


class BloqueioDeLoginTest(BaseTest):
    def entrar(self, usuario, senha):
        return self.client.post(reverse('login'), {'username': usuario, 'password': senha})

    def test_bloqueia_apos_cinco_falhas_mesmo_com_senha_correta(self):
        for _ in range(5):
            self.assertContains(self.entrar('jaqueline', 'errada'), 'Usuário ou senha inválidos.')
        resposta = self.entrar('jaqueline', 'senha-de-teste-123')
        self.assertContains(resposta, 'Muitas tentativas')
        self.assertEqual(self.client.get(reverse('menu')).status_code, 302)  # continua sem acesso

    def test_quatro_falhas_nao_bloqueiam_e_o_login_correto_zera_o_contador(self):
        for _ in range(4):
            self.entrar('jaqueline', 'errada')
        self.assertRedirects(self.entrar('jaqueline', 'senha-de-teste-123'), reverse('menu'))
        self.assertFalse(TentativaLogin.objects.filter(usuario='jaqueline').exists())

    def test_bloqueio_expira_depois_do_prazo(self):
        for _ in range(5):
            self.entrar('jaqueline', 'errada')
        TentativaLogin.objects.filter(usuario='jaqueline').update(bloqueado_ate=timezone.now() - timedelta(minutes=1))
        self.assertRedirects(self.entrar('jaqueline', 'senha-de-teste-123'), reverse('menu'))

    def test_usuario_inexistente_tambem_e_bloqueado_sem_revelar_a_conta(self):
        for _ in range(5):
            self.assertContains(self.entrar('fantasma', 'x'), 'Usuário ou senha inválidos.')
        self.assertContains(self.entrar('fantasma', 'x'), 'Muitas tentativas')

    def test_bloqueio_de_um_usuario_nao_afeta_outro(self):
        get_user_model().objects.create_user('outra', password='outra-senha-123')
        for _ in range(5):
            self.entrar('jaqueline', 'errada')
        self.assertRedirects(self.entrar('outra', 'outra-senha-123'), reverse('menu'))


class RelatorioMensalTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.login(username='jaqueline', password='senha-de-teste-123')
        self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': 2}])
        self.vender([{'variacao_id': self.g_azul.pk, 'quantidade': 1}], situacao_pagamento='pendente', nome_cliente='Cliente Teste')

    def test_requer_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('relatorio')).status_code, 302)

    def test_totais_ranking_e_pendentes_do_mes_atual(self):
        resposta = self.client.get(reverse('relatorio'))
        self.assertContains(resposta, 'R$ 269,70')           # 3 x 89,90
        self.assertContains(resposta, '2 vendas')
        self.assertContains(resposta, 'Vestido floral')
        self.assertContains(resposta, '3 un.')
        self.assertContains(resposta, 'Cliente Teste')
        self.assertContains(resposta, 'Total pendente: R$ 89,90')

    def test_mes_sem_vendas_mostra_vazio(self):
        resposta = self.client.get(reverse('relatorio'), {'mes': '2020-01'})
        self.assertContains(resposta, 'Nenhuma venda neste mês.')
        self.assertContains(resposta, 'R$ 0,00')

    def test_mes_invalido_volta_ao_mes_atual_com_aviso(self):
        for ruim in ('2026-13', "'; DROP TABLE--", 'abc'):
            resposta = self.client.get(reverse('relatorio'), {'mes': ruim})
            self.assertEqual(resposta.status_code, 200)
            self.assertContains(resposta, 'Mês inválido')
        self.assertEqual(Venda.objects.count(), 2)

    def test_menu_tem_link_para_o_relatorio(self):
        self.assertContains(self.client.get(reverse('menu')), 'Relatório mensal')


class ReposicaoTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.login(username='jaqueline', password='senha-de-teste-123')

    def test_telas_de_reposicao_exigem_login(self):
        self.client.logout()
        for nome in ('repor', 'nova_variacao'):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 302, nome)

    def test_reposicao_soma_ao_saldo_e_tira_do_alerta(self):
        self.assertTrue(self.m_preta.estoque_baixo)
        resposta = self.client.post(reverse('repor'), {'variacao': self.m_preta.pk, 'quantidade': 4}, follow=True)
        self.assertContains(resposta, 'Estoque atualizado. Vestido floral M Preta: 5 unidades')
        self.m_preta.refresh_from_db()
        self.assertEqual(self.m_preta.quantidade_estoque, 5)
        self.assertFalse(self.m_preta.estoque_baixo)

    def test_reposicao_recusa_quantidade_invalida(self):
        for q in ('0', '-3', 'abc'):
            resposta = self.client.post(reverse('repor'), {'variacao': self.m_preta.pk, 'quantidade': q})
            self.assertEqual(resposta.status_code, 200)
        self.m_preta.refresh_from_db()
        self.assertEqual(self.m_preta.quantidade_estoque, 1)

    def test_servico_de_reposicao_recusa_produto_inativo(self):
        from .services import repor_estoque
        self.produto.ativo = False
        self.produto.save()
        with self.assertRaises(RegraDeNegocioError):
            repor_estoque(variacao_id=self.g_azul.pk, quantidade=2)

    def test_nova_variacao_para_produto_existente(self):
        resposta = self.client.post(reverse('nova_variacao'), {
            'produto': self.produto.pk, 'tamanho': 'p', 'cor': 'verde', 'quantidade_estoque': 3, 'estoque_minimo': 1}, follow=True)
        self.assertContains(resposta, 'Variação cadastrada: Vestido floral P Verde.')
        v = Variacao.objects.get(produto=self.produto, tamanho='P')
        self.assertEqual((v.cor, v.quantidade_estoque), ('Verde', 3))

    def test_nova_variacao_duplicada_e_recusada_com_orientacao(self):
        resposta = self.client.post(reverse('nova_variacao'), {
            'produto': self.produto.pk, 'tamanho': 'm', 'cor': 'PRETA', 'quantidade_estoque': 3, 'estoque_minimo': 1})
        self.assertContains(resposta, 'já existe para o produto. Use')
        self.assertEqual(Variacao.objects.filter(produto=self.produto).count(), 2)

    def test_menu_tem_links_de_estoque(self):
        resposta = self.client.get(reverse('menu'))
        self.assertContains(resposta, 'Repor estoque')
        self.assertContains(resposta, 'Nova variação')


class SaudeTest(TestCase):
    def test_saude_e_publica_e_informa_banco_ok(self):
        resposta = self.client.get(reverse('saude'))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {'status': 'ok', 'banco': 'ok'})

    def test_saude_devolve_503_quando_o_banco_falha(self):
        from unittest import mock
        with mock.patch('estoque.views.connection.cursor', side_effect=Exception('banco fora')):
            resposta = self.client.get(reverse('saude'))
        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(resposta.json()['status'], 'erro')
        self.assertNotIn('banco fora', resposta.content.decode())  # sem detalhes técnicos

    def test_saude_nao_expoe_dados_do_negocio(self):
        self.assertEqual(set(self.client.get(reverse('saude')).json()), {'status', 'banco'})


class ConfiguracaoDeProducaoTest(TestCase):
    def test_database_url_e_interpretada(self):
        from config.settings import _banco_por_url
        cfg = _banco_por_url('postgres://usu%40:s%23nha@banco.exemplo.com:5432/sepala')
        self.assertEqual((cfg['USER'], cfg['PASSWORD'], cfg['HOST'], cfg['PORT'], cfg['NAME']),
                         ('usu@', 's#nha', 'banco.exemplo.com', '5432', 'sepala'))
